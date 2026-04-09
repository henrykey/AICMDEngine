from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from bson import ObjectId

class CommandSet(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str
    description: Optional[str] = None
    tenant_id: Optional[int] = None  # Will be set from X-Tenant-ID header
    source_type: str = "manual"
    source_uri: Optional[str] = None
    version: str = "1.0.0"
    storage_status: Optional[Dict[str, bool]] = Field(default=None, alias="storageStatus")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        """Convert MongoDB ObjectId to string before validation"""
        if isinstance(data, dict):
            if '_id' in data and isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
        return data

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
