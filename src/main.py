import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings, setup_logging
from src.routers import tasks, command_sets

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
    logger.info(f"Connected to MongoDB at {settings.database_name}")

@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()
    logger.info("Disconnected from MongoDB")

app.include_router(tasks.router, prefix="/v1/tasks", tags=["Tasks"])
app.include_router(command_sets.router, prefix="/v1/command-sets", tags=["Command Sets"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
