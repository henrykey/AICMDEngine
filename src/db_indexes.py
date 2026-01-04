from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings

async def create_indexes():
    """创建数据库索引以优化查询性能"""
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.database_name]

    try:
        # 执行记录索引
        await db["executions"].create_index("tenant_id")
        await db["executions"].create_index("status")
        await db["executions"].create_index([("tenant_id", 1), ("status", 1)])
        await db["executions"].create_index("started_at", -1)

        # 步骤执行记录索引
        await db["step_executions"].create_index("execution_id")
        await db["step_executions"].create_index("step_number")
        await db["step_executions"].create_index("status")
        await db["step_executions"].create_index([("execution_id", 1), ("step_number", 1)])

        # 审计日志索引
        await db["events"].create_index("tenant_id")
        await db["events"].create_index("category")
        await db["events"].create_index("occurred_at", -1)
        await db["events"].create_index([("tenant_id", 1), ("occurred_at", -1)])

        print("Database indexes created successfully")
    except Exception as e:
        print(f"Warning: Some indexes may have failed to create: {e}")
    finally:
        client.close()