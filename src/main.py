import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings, setup_logging
from src.routers import tasks, command_sets, executions, auth, llm, mcp, design
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
app.include_router(executions.router, prefix="/v1/executions", tags=["Executions"])
app.include_router(mcp.router, prefix="/v1/mcp", tags=["MCP"])
app.include_router(mcp_ws.router, tags=["MCP WebSocket"])  # MCP WebSocket endpoint
app.include_router(llm.router)  # LLM routes at /api/llm/* (no prefix)
app.include_router(design.router)  # Design routes at /api/design/* (no prefix)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
