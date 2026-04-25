import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings, setup_logging
from src.routers import tasks, command_sets, executions, auth, llm, mcp, design, command_index
from src.routers import mcp_ws  # MCP WebSocket router
from src.llm.provider_manager import LLMProviderManager
from src.llm.config_loader import LLMConfigLoader
from src.mcp.registry import MCPRegistry
from src.mcp.external_mcp import ExternalMCPServer
from src.mcp_servers.membership_mcp import MembershipMCPServer
from src.mcp_servers.test_mcp import TestMCPServer
from src.mcp_servers.kb_mcp import KBMCP
from src.mcp_servers.bpmn_mcp import BPMN_MCP
from src.mcp_servers.form_mcp import FORM_MCP
from src.services.embedding_service import EmbeddingService
from src.services.command_indexer import CommandIndexer
from src.services.command_retriever import CommandRetriever
from src.services.direct_mcp_executor import DirectMCPExecutor
from src.services.docintel_client import DocIntelClient
from src.services.docintel_command_sync import DocIntelCommandSyncService

# Setup logging
setup_logging(settings)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NL Task Planning Service",
    description="Intelligent middleware to translate natural language goals into executable plans.",
    version="1.0.0"
)

# CORS (Allowing Frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "NL-TPS", "model": settings.openai_model_name}

@app.on_event("startup")
async def startup_db_client():
    logger.info(f"Starting NL-TPS with model: {settings.openai_model_name}")
    app.mongodb_client = AsyncIOMotorClient(settings.mongodb_uri)
    app.mongodb = app.mongodb_client[settings.database_name]

    # 创建数据库索引
    from src.db_indexes import create_indexes
    await create_indexes()

    logger.info(f"Connected to MongoDB at {settings.database_name}")

    # Load LLM configuration from MongoDB
    try:
        await settings.load_llm_from_mongodb(app.mongodb)
        logger.info(f"Loaded LLM config from MongoDB: {settings.deepseek_model_name or settings.openai_model_name}")
    except Exception as e:
        logger.warning(f"Could not load LLM config from MongoDB: {e}")

    # Initialize LLM Provider Manager
    try:
        config_loader = LLMConfigLoader(use_mongodb=True)
        provider_manager = LLMProviderManager(config_loader)
        await provider_manager.initialize(app.mongodb_client)

        # Set global provider manager for dependency injection
        llm.set_provider_manager(provider_manager)
        app.provider_manager = provider_manager

        logger.info(f"Initialized LLM Provider Manager with {len(provider_manager.get_providers())} providers")

        # Initialize Async Capability Detector
        from src.llm.async_capability_detector import AsyncCapabilityDetector
        async_detector = AsyncCapabilityDetector(
            provider_manager=provider_manager,
            notification_service=llm.notification_service
        )
        llm.set_async_detector(async_detector)
        logger.info("Initialized Async Capability Detector")

    except Exception as e:
        logger.error(f"Failed to initialize LLM Provider Manager: {e}")
        # Continue without LLM manager for now

    # Initialize MCP Registry
    try:
        mcp_registry = MCPRegistry()

        # Register MCP servers
        membership_mcp = MembershipMCPServer()
        test_mcp = TestMCPServer()
        kb_mcp = KBMCP(
            kb_base_url=settings.kb_base_url,
            kb_api_key=settings.kb_api_key
        )
        bpmn_mcp = BPMN_MCP(
            membership_base_url=settings.membership_service_url,
            use_real_llm=False,
            kb_base_url=settings.kb_base_url
        )
        form_mcp = FORM_MCP(
            membership_base_url=settings.membership_service_url,
            use_real_llm=False,
            kb_base_url=settings.kb_base_url
        )

        mcp_registry.register_mcp(membership_mcp)
        mcp_registry.register_mcp(test_mcp)
        mcp_registry.register_mcp(kb_mcp)
        mcp_registry.register_mcp(bpmn_mcp)
        mcp_registry.register_mcp(form_mcp)

        # Register external MCP servers from configuration
        external_mcps_config = getattr(settings, 'external_mcps', {})
        if external_mcps_config:
            logger.info(f"Loading {len(external_mcps_config)} external MCP servers from configuration")
            for mcp_name, mcp_config in external_mcps_config.items():
                try:
                    external_mcp = ExternalMCPServer(
                        name=mcp_name,
                        command=mcp_config.get("command"),
                        args=mcp_config.get("args", []),
                        transport=mcp_config.get("transport", "stdio"),
                        url=mcp_config.get("url"),
                        env=mcp_config.get("env"),
                        timeout=mcp_config.get("timeout", 30)
                    )
                    # Keep full config for runtime metadata/query/injection usage.
                    external_mcp.external_config = mcp_config

                    # Initialize the external MCP (connects and discovers tools)
                    await external_mcp.initialize()

                    mcp_registry.register_mcp(external_mcp)
                    logger.info(f"Successfully registered external MCP '{mcp_name}'")

                except Exception as e:
                    logger.error(f"Failed to register external MCP '{mcp_name}': {e}")
                    # Continue with other MCPs

        # Set global MCP registry for dependency injection
        app.mcp_registry = mcp_registry

        # Also set in core.dependencies for WebSocket router
        from src.core.dependencies import set_mcp_registry
        set_mcp_registry(mcp_registry)

        logger.info(f"Initialized MCP Registry with {len(mcp_registry.get_all_mcps())} servers:")
        for mcp in mcp_registry.get_all_mcps():
            logger.info(f"  - {mcp.name} (v{mcp.version}): {len(mcp.get_tools())} tools")
    except Exception as e:
        logger.error(f"Failed to initialize MCP Registry: {e}")
        # Continue without MCP registry for now

    if settings.command_retrieval_enabled:
        provider_manager = getattr(app, "provider_manager", None)
        if not provider_manager:
            error = ValueError("Provider manager is required for command retrieval")
            logger.error(f"Failed to initialize command retrieval services: {error}")
            if not settings.command_retrieval_fallback_to_full_inventory:
                raise error
        else:
            embedding_service = EmbeddingService(provider_manager=provider_manager)
            app.embedding_service = embedding_service

            docintel_client = None
            local_retrieval_client = None
            if settings.docintel_enabled and settings.docintel_base_url:
                try:
                    docintel_client = DocIntelClient(
                        base_url=settings.docintel_base_url,
                        search_path=settings.docintel_search_path,
                        command_sync_path=settings.docintel_command_sync_path,
                        command_delete_path=settings.docintel_command_delete_path,
                        api_key=settings.docintel_api_key,
                        timeout_ms=settings.docintel_timeout_ms,
                        category_prefix=settings.docintel_command_category_prefix,
                    )
                    app.docintel_client = docintel_client
                    app.docintel_command_sync = DocIntelCommandSyncService(
                        client=docintel_client,
                        db=app.mongodb,
                        category_prefix=settings.docintel_command_category_prefix,
                        default_user_id=settings.docintel_default_user_id,
                    )
                    logger.info("Initialized DocIntel command sync client: %s", settings.docintel_base_url)
                    if settings.docintel_sync_enabled and settings.docintel_api_key:
                        try:
                            synced_commands = await app.docintel_command_sync.rebuild_from_mongo()
                            logger.info("Synced %s Mongo commands to DocIntel command corpus", synced_commands)
                            if hasattr(app, "mcp_registry"):
                                synced_mcp = await app.docintel_command_sync.sync_mcp_tools(app.mcp_registry)
                                logger.info("Synced %s MCP tools to DocIntel command corpus", synced_mcp)
                        except Exception as sync_error:
                            logger.warning("DocIntel startup sync failed: %s", sync_error)
                    elif settings.docintel_sync_enabled:
                        logger.info("Skipping DocIntel startup sync because DOCINTEL_API_KEY is not configured")
                except Exception as e:
                    logger.error("Failed to initialize DocIntel client: %s", e)

            if settings.local_retrieval_enabled and settings.local_retrieval_base_url:
                try:
                    local_retrieval_client = DocIntelClient(
                        base_url=settings.local_retrieval_base_url,
                        search_path=settings.local_retrieval_search_path,
                        command_sync_path=settings.local_retrieval_command_sync_path,
                        command_delete_path=settings.local_retrieval_command_delete_path,
                        timeout_ms=settings.local_retrieval_timeout_ms,
                        category_prefix=settings.docintel_command_category_prefix,
                    )
                    app.local_retrieval_client = local_retrieval_client
                    app.local_command_sync = DocIntelCommandSyncService(
                        client=local_retrieval_client,
                        db=app.mongodb,
                        category_prefix=settings.docintel_command_category_prefix,
                        default_user_id=settings.docintel_default_user_id,
                    )
                    logger.info("Initialized local retrieval command sync client: %s", settings.local_retrieval_base_url)
                except Exception as e:
                    logger.error("Failed to initialize local retrieval client: %s", e)

            command_indexer = None
            if settings.elasticsearch_url:
                try:
                    command_indexer = CommandIndexer(
                        es_url=settings.elasticsearch_url,
                        index_name=settings.command_search_index,
                        embedding_service=embedding_service,
                        db=app.mongodb,
                        api_key=settings.elasticsearch_api_key,
                    )
                    await command_indexer.ensure_index()
                    indexed_commands = await command_indexer.rebuild_from_mongo()
                    logger.info("Indexed %s Mongo commands into '%s'", indexed_commands, settings.command_search_index)

                    if hasattr(app, "mcp_registry"):
                        await command_indexer.upsert_mcp_tools(app.mcp_registry)

                    app.command_indexer = command_indexer
                except Exception as e:
                    logger.error("Failed to initialize local ES command indexer: %s", e)
            else:
                logger.info("Skipping local ES command indexer because ELASTICSEARCH_URL is not configured")

            try:
                app.command_retriever = CommandRetriever(
                    es_url=settings.elasticsearch_url,
                    index_name=settings.command_search_index,
                    embedding_service=embedding_service,
                    docintel_client=docintel_client,
                    local_retrieval_client=local_retrieval_client,
                    api_key=settings.elasticsearch_api_key,
                    retrieval_top_k=settings.command_retrieval_top_k,
                    prompt_top_k=settings.command_prompt_top_k,
                    prefer_remote=settings.docintel_prefer_remote_retrieval,
                    remote_min_results=settings.docintel_remote_min_results,
                    remote_min_top_score=settings.docintel_remote_min_top_score,
                )
                if hasattr(app, "mcp_registry"):
                    app.direct_mcp_executor = DirectMCPExecutor(
                        command_retriever=app.command_retriever,
                        mcp_registry=app.mcp_registry
                    )
                logger.info("Initialized command retrieval services with index '%s'", settings.command_search_index)
            except Exception as e:
                logger.error(f"Failed to initialize command retrieval services: {e}")
                if not settings.command_retrieval_fallback_to_full_inventory:
                    raise

@app.on_event("shutdown")
async def shutdown_db_client():
    # Close external MCP servers
    if hasattr(app, 'mcp_registry'):
        mcp_registry = app.mcp_registry
        for mcp in mcp_registry.get_all_mcps():
            if isinstance(mcp, ExternalMCPServer):
                try:
                    await mcp.close()
                    logger.info(f"Closed external MCP '{mcp.name}'")
                except Exception as e:
                    logger.error(f"Error closing external MCP '{mcp.name}': {e}")

    app.mongodb_client.close()
    logger.info("Disconnected from MongoDB")

app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(tasks.router, prefix="/v1/tasks", tags=["Tasks"])
app.include_router(command_sets.router, prefix="/v1/command-sets", tags=["Command Sets"])
app.include_router(command_index.router, prefix="/v1/command-index", tags=["Command Index"])
app.include_router(executions.router, prefix="/v1/executions", tags=["Executions"])
app.include_router(mcp.router, prefix="/v1/mcp", tags=["MCP"])
app.include_router(mcp_ws.router, tags=["MCP WebSocket"])  # MCP WebSocket endpoint
app.include_router(llm.router)  # LLM routes at /api/llm/* (no prefix)
app.include_router(design.router)  # Design routes at /api/design/* (no prefix)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        ws_max_size=settings.ws_max_size,
    )
