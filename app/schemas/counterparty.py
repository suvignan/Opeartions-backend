# app/schemas/counterparty.py
import uuid
from pydantic import BaseModel, field_validator


class CounterpartyCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Counterparty name cannot be blank")
        return v


class CounterpartyInContract(BaseModel):
    """
    Nested inside ContractResponse.
    Exposes only id + name — normalized_name is an internal
    implementation detail and must never appear in API responses.
    """
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}