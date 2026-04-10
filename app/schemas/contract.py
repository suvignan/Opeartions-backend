# app/schemas/contract.py
import uuid
from datetime import date, datetime

from pydantic import BaseModel, field_validator, model_validator

from app.core.enums import ContractStatus, Currency
from app.schemas.counterparty import CounterpartyCreate, CounterpartyInContract


# ── Sub-schemas ────────────────────────────────────────────────────────────────

class FinancialsSchema(BaseModel):
    tcv_cents: int | None = None
    acv_cents: int | None = None
    currency: Currency = Currency.USD

    @field_validator("tcv_cents", "acv_cents")
    @classmethod
    def must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Financial values must be non-negative")
        return v

    @model_validator(mode="after")
    def acv_lte_tcv(self) -> "FinancialsSchema":
        if self.acv_cents is not None and self.tcv_cents is not None:
            if self.acv_cents > self.tcv_cents:
                raise ValueError("acv_cents cannot exceed tcv_cents")
        return self


class TimelineSchema(BaseModel):
    start_date: date
    end_date: date | None = None
    auto_renew: bool = False

    @model_validator(mode="after")
    def end_after_start(self) -> "TimelineSchema":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self
# ── Partial sub-schemas (update — every field optional) ───────────────────────

class UpdateFinancialsSchema(BaseModel):
    """
    All fields optional. Cross-field validation only runs when both
    values are present in THIS request. Mixed-value validation
    (one from request, one from DB) happens in the service layer.
    """
    tcv_cents: int | None = None
    acv_cents: int | None = None
    currency: Currency | None = None

    model_config = {"extra": "forbid"}

    @field_validator("tcv_cents", "acv_cents")
    @classmethod
    def must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Financial values must be non-negative")
        return v

    @model_validator(mode="after")
    def acv_lte_tcv(self) -> "UpdateFinancialsSchema":
        if self.acv_cents is not None and self.tcv_cents is not None:
            if self.acv_cents > self.tcv_cents:
                raise ValueError("acv_cents cannot exceed tcv_cents")
        return self


class UpdateTimelineSchema(BaseModel):
    """
    All fields optional. end_date >= start_date only enforced when
    both are sent in the same request. Mixed-value validation happens
    in the service after merging with existing DB values.
    """
    start_date: date | None = None
    end_date: date | None = None
    auto_renew: bool | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def end_after_start(self) -> "UpdateTimelineSchema":
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("end_date must be on or after start_date")
        return self


class UpdateContractRequest(BaseModel):
    """
    All fields optional — send only what you want to change.
    Omitting a field means 'leave the current DB value untouched'.

    Counterparty rule (only enforced when you want to change it):
      - Supply counterparty_id OR counterparty.name, never both.
      - Omitting both means 'do not change the counterparty'.
    """
    title: str | None = None
    type: str | None = None
    counterparty_id: uuid.UUID | None = None
    counterparty: CounterpartyCreate | None = None
    financials: UpdateFinancialsSchema | None = None
    timeline: UpdateTimelineSchema | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def counterparty_xor(self) -> "UpdateContractRequest":
        has_id  = self.counterparty_id is not None
        has_obj = self.counterparty is not None
        if has_id and has_obj:
            raise ValueError(
                "Provide either 'counterparty_id' or 'counterparty', not both"
            )
        return self

    @property
    def wants_counterparty_change(self) -> bool:
        """True when the caller explicitly sent a counterparty field."""
        return self.counterparty_id is not None or self.counterparty is not None


# ── Request schemas ────────────────────────────────────────────────────────────

class CreateContractRequest(BaseModel):
    title: str
    type: str | None = None
    counterparty_id: uuid.UUID | None = None
    counterparty: CounterpartyCreate | None = None
    financials: FinancialsSchema
    timeline: TimelineSchema

    @model_validator(mode="after")
    def exactly_one_counterparty(self) -> "CreateContractRequest":
        has_id  = self.counterparty_id is not None
        has_obj = self.counterparty is not None
        if has_id == has_obj:
            raise ValueError(
                "Provide either 'counterparty_id' or 'counterparty', not both (or neither)"
            )
        return self


class UpdateContractStatusRequest(BaseModel):
    """
    Fix 1: dedicated request body schema for PATCH /contracts/{id}/status.

    Without this, FastAPI infers that a bare `ContractStatus` parameter is a
    query param (because it is not a BaseModel). Wrapping it in a BaseModel
    forces FastAPI to read it from the JSON request body, which is the correct
    HTTP semantics for a PATCH operation — status changes are mutations, not
    filters, and do not belong in the URL or query string.
    """
    status: ContractStatus


# ── Response schemas ───────────────────────────────────────────────────────────

class AuditSchema(BaseModel):
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractResponse(BaseModel):
    id: uuid.UUID
    title: str
    type: str | None = None
    status: ContractStatus
    owner_id: uuid.UUID
    counterparty: CounterpartyInContract
    financials: FinancialsSchema
    timeline: TimelineSchema
    audit: AuditSchema

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, contract) -> "ContractResponse":
        return cls(
            id=contract.id,
            title=contract.title,
            type=contract.type,
            owner_id=contract.owner_id,
            status=contract.status,
            counterparty=CounterpartyInContract.model_validate(contract.counterparty),
            financials=FinancialsSchema(
                tcv_cents=contract.tcv_cents,
                acv_cents=contract.acv_cents,
                currency=contract.currency,
            ),
            timeline=TimelineSchema(
                start_date=contract.start_date,
                end_date=contract.end_date,
                auto_renew=contract.auto_renew,
            ),
            audit=AuditSchema(
                created_by=contract.created_by,
                updated_by=contract.updated_by,
                created_at=contract.created_at,
                updated_at=contract.updated_at,
            ),
        )