from typing import Optional, Any
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from bson import ObjectId

class CommandSet(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str
    description: Optional[str] = None
    tenant_id: str
    source_type: str = "manual"
    source_uri: Optional[str] = None
    version: str = "1.0.0"
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        """Convert MongoDB ObjectId to string before validation"""
        if isinstance(data, dict) and '_id' in data:
            if isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
        return data

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
