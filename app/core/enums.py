# app/core/enums.py
from enum import Enum


class ContractStatus(str, Enum):
    """
    str + Enum so FastAPI serializes values as plain strings ("ACTIVE")
    in JSON and OpenAPI docs, and SQLAlchemy stores them as VARCHAR.
    """
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE         = "ACTIVE"
    EXPIRED        = "EXPIRED"
    ARCHIVED       = "ARCHIVED"


class Currency(str, Enum):
    """
    Common ISO 4217 currency codes validated at the API boundary.
    DB stores String(3) — add new currencies here with no migration needed.
    """
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    INR = "INR"
    AED = "AED"
    SGD = "SGD"
    JPY = "JPY"