# app/schemas/pagination.py
from pydantic import BaseModel
from app.schemas.contract import ContractResponse


class PaginationMeta(BaseModel):
    """
    Carries pagination context alongside the data array.
    `total` is the count of all matching rows (ignoring limit/offset)
    so the frontend can calculate total pages without a second request.
    """
    page:  int
    limit: int
    total: int


class PaginatedContractResponse(BaseModel):
    data: list[ContractResponse]
    meta: PaginationMeta