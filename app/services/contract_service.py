# app/services/contract_service.py
import uuid
from datetime import date    # ← add this if not already present

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.contract import Contract
from app.models.counterparty import Counterparty
from app.core.enums import ContractStatus
from app.core.exceptions import (
    ContractValidationError,
    ContractNotFoundError,
    CounterpartyNotFoundError,
    DuplicateContractError,
    DuplicateCounterpartyError,
)
from app.core.project_types import get_project_type_code, get_company_code
from app.schemas.contract import CreateContractRequest, ContractResponse,UpdateContractRequest

MAX_CONTRACT_CODE_RETRIES = 5


# ── Internal helpers ───────────────────────────────────────────────────────────

def _fetch_counterparty_by_normalized(
    db: Session,
    owner_id: uuid.UUID,
    normalized_name: str,
) -> Counterparty | None:
    return (
        db.query(Counterparty)
        .filter(
            Counterparty.owner_id == owner_id,
            Counterparty.normalized_name == normalized_name,
        )
        .first()
    )


def _resolve_counterparty(
    db: Session,
    owner_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    request: CreateContractRequest,
) -> Counterparty:
    # ── Path A: existing counterparty by ID ───────────────────────────────────
    if request.counterparty_id:
        cp = (
            db.query(Counterparty)
            .filter(
                Counterparty.id == request.counterparty_id,
                Counterparty.owner_id == owner_id,
            )
            .first()
        )
        if not cp:
            raise CounterpartyNotFoundError(
                f"Counterparty '{request.counterparty_id}' not found for this owner. "
                "Verify the ID belongs to your account."
            )
        return cp

    # ── Path B: inline create with SAVEPOINT-based race handling ──────────────
    raw_name   = request.counterparty.name
    normalized = raw_name.strip().lower()

    # Happy path: already exists, no insert needed.
    existing = _fetch_counterparty_by_normalized(db, owner_id, normalized)
    if existing:
        return existing

    # Attempt insert inside a SAVEPOINT so that an IntegrityError from a
    # concurrent insert only rolls back to this point — the outer transaction
    # (which may have already flushed other objects) remains intact and usable.
    try:
        with db.begin_nested():   # ← issues SAVEPOINT; releases on clean exit,
                                  #   rolls back to SAVEPOINT on exception
            new_cp = Counterparty(
                id=uuid.uuid4(),
                owner_id=owner_id,
                name=raw_name.strip(),
                normalized_name=normalized,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(new_cp)
            db.flush()   # sends INSERT within the savepoint
        return new_cp    # savepoint released — row is visible in outer transaction

    except IntegrityError as e:
        # Only handle the specific counterparty uniqueness violation.
        # Any other IntegrityError propagates normally.
        if "uq_counterparty_owner_name" not in str(e.orig).lower():
            raise

        # Savepoint was rolled back automatically by the context manager.
        # Outer transaction is clean. Re-fetch the row the winning request inserted.
        recovered = _fetch_counterparty_by_normalized(db, owner_id, normalized)
        if recovered:
            return recovered   # transparent recovery — caller is unaware of the race

        # Constraint fired but row is gone (winner deleted immediately — pathological).
        raise DuplicateCounterpartyError(
            f"Counterparty '{raw_name.strip()}' could not be created or recovered. "
            "Please retry the request."
        ) from e
def _validate_merged_financials(
    acv_cents: int | None,
    tcv_cents: int | None,
) -> None:
    """
    Run AFTER merging request + DB values. Catches violations where only
    one side was in the request but the combined result breaks the rule.
    e.g. existing tcv=1000, request sends acv=1200 only → violation.
    """
    if acv_cents is not None and tcv_cents is not None:
        if acv_cents > tcv_cents:
            raise ContractValidationError(
                f"acv_cents ({acv_cents}) cannot exceed tcv_cents ({tcv_cents}) "
                "after applying this update."
            )


def _validate_merged_timeline(
    start_date: date,
    end_date: date | None,
) -> None:
    """
    Run AFTER merging request + DB values. Catches violations where only
    one side was in the request.
    e.g. existing end=2024-12-31, request sends start=2025-06-01 only → violation.
    """
    if end_date is not None and end_date < start_date:
        raise ContractValidationError(
            f"end_date ({end_date}) must be on or after start_date ({start_date}) "
            "after applying this update."
        )


def _is_contract_code_unique_conflict(error_str: str) -> bool:
    return "uq_contract_contract_code" in error_str or (
        "contract_code" in error_str and "unique" in error_str
    )

# ── Public service functions ───────────────────────────────────────────────────


def create_contract(
    db: Session,
    owner_id: uuid.UUID,
    request: CreateContractRequest,
    actor_id: uuid.UUID | None = None,
) -> ContractResponse:
    try:
        for attempt in range(MAX_CONTRACT_CODE_RETRIES):
            try:
                counterparty = _resolve_counterparty(db, owner_id, actor_id, request)
                contract = Contract(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    counterparty_id=counterparty.id,
                    title=request.title,
                    type=request.type,
                    project_type=request.project_type,
                    tcv_cents=request.financials.tcv_cents,
                    acv_cents=request.financials.acv_cents,
                    currency=request.financials.currency,
                    start_date=request.timeline.start_date,
                    end_date=request.timeline.end_date,
                    auto_renew=request.timeline.auto_renew,
                    status=ContractStatus.PENDING_REVIEW,
                    created_by=actor_id,
                    updated_by=actor_id,
                )

                print("DEBUG: starting contract_code generation")

                last_contract = (
                    db.query(Contract)
                    .filter(Contract.contract_code != None)
                    .order_by(Contract.created_at.desc())
                    .first()
                )

                next_seq = 1

                if last_contract and last_contract.contract_code:
                    try:
                        last_seq = int(last_contract.contract_code.split("_")[-1])
                        next_seq = last_seq + 1
                    except:
                        next_seq = 1

                try:
                    short_code = get_project_type_code(contract.project_type)
                except ValueError:
                    short_code = "OTH"

                    
                company_code = get_company_code()
                contract.contract_code = f"{company_code}_{short_code}_{next_seq:03d}"

                print("DEBUG: generated contract_code =", contract.contract_code)

                db.add(contract)
                db.commit()
                db.refresh(contract)
                return ContractResponse.from_orm_model(contract)

            except IntegrityError as e:
                db.rollback()
                error_str = str(e.orig).lower()

                if "uq_contract_owner_counterparty_start" in error_str:
                    raise DuplicateContractError(
                        "A contract with this counterparty and start date already exists "
                        "for your account."
                    ) from e

                if _is_contract_code_unique_conflict(error_str):
                    if attempt < MAX_CONTRACT_CODE_RETRIES - 1:
                        continue
                    raise ContractValidationError(
                        "Unable to generate a unique contract_code after retries. "
                        "Please retry the request."
                    ) from e

                raise ContractValidationError(
                    f"A database constraint was violated: {e.orig}"
                ) from e

    except (
        CounterpartyNotFoundError,
        ContractNotFoundError,
        ContractValidationError,
        DuplicateContractError,
        DuplicateCounterpartyError,
    ):
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise ContractValidationError(
            f"Unexpected error while creating contract: {str(e)}"
        ) from e

def update_contract(
    db: Session,
    owner_id: uuid.UUID,
    contract_id: uuid.UUID,
    request: UpdateContractRequest,
    actor_id: uuid.UUID | None = None,
) -> ContractResponse:
    """
    Partial update — only fields in the request are written.
    Fields absent from the payload retain their current DB values.

    model_fields_set is the Pydantic v2 mechanism that tells us which
    fields the caller actually sent, distinguishing:
      - Sent as null  →  in model_fields_set  →  write null  (explicit clear)
      - Not sent      →  not in model_fields_set  →  keep DB value (no-op)
    """
    try:
        # ── 1. Fetch + ownership check ────────────────────────────────────────
        contract = (
            db.query(Contract)
            .filter(
                Contract.id == contract_id,
                Contract.owner_id == owner_id,
            )
            .first()
        )
        if not contract:
            raise ContractNotFoundError(
                f"Contract '{contract_id}' not found. "
                "Verify the ID belongs to your account."
            )

        # ── 2. Core Updates (Counterparty, Title, Type) ───────────────────────
        if request.wants_counterparty_change:
            resolved = _resolve_counterparty(db, owner_id, actor_id, request)
            contract.counterparty_id = resolved.id
            
        fields_set = request.model_fields_set
        
        if "title" in fields_set:
            contract.title = request.title
            
        if "type" in fields_set:
            contract.type = request.type

        if "project_type" in fields_set:
            contract.project_type = request.project_type

        # ── 3. Financials — merge then validate ───────────────────────────────
        if request.financials is not None:
            fin        = request.financials
            fields_set = fin.model_fields_set

            new_tcv = fin.tcv_cents if "tcv_cents" in fields_set else contract.tcv_cents
            new_acv = fin.acv_cents if "acv_cents" in fields_set else contract.acv_cents
            new_cur = fin.currency  if "currency"  in fields_set else contract.currency

            _validate_merged_financials(new_acv, new_tcv)

            contract.tcv_cents = new_tcv
            contract.acv_cents = new_acv
            contract.currency  = new_cur

        # ── 4. Timeline — merge then validate ─────────────────────────────────
        if request.timeline is not None:
            tl         = request.timeline
            fields_set = tl.model_fields_set

            new_start = tl.start_date if "start_date" in fields_set else contract.start_date
            new_end   = tl.end_date   if "end_date"   in fields_set else contract.end_date
            new_auto  = tl.auto_renew if "auto_renew" in fields_set else contract.auto_renew

            _validate_merged_timeline(new_start, new_end)

            contract.start_date = new_start
            contract.end_date   = new_end
            contract.auto_renew = new_auto

        # ── 5. Audit + commit ─────────────────────────────────────────────────
        contract.updated_by = actor_id
        # updated_at handled automatically by onupdate= on the column

        db.commit()
        db.refresh(contract)
        return ContractResponse.from_orm_model(contract)

    except (
        ContractNotFoundError,
        CounterpartyNotFoundError,
        ContractValidationError,
        DuplicateCounterpartyError,
    ):
        db.rollback()
        raise

    except IntegrityError as e:
        db.rollback()
        error_str = str(e.orig).lower()
        if "uq_contract_owner_counterparty_start" in error_str:
            raise DuplicateContractError(
                "This update would create a duplicate contract "
                "(same counterparty and start date already exists)."
            ) from e
        raise ContractValidationError(
            f"A database constraint was violated: {e.orig}"
        ) from e

    except Exception as e:
        db.rollback()
        raise ContractValidationError(
            f"Unexpected error while updating contract: {str(e)}"
        ) from e

def update_contract_status(
    db: Session,
    owner_id: uuid.UUID,
    contract_id: uuid.UUID,
    new_status: ContractStatus,
    actor_id: uuid.UUID | None = None,
) -> ContractResponse:
    try:
        contract = (
            db.query(Contract)
            .filter(
                Contract.id == contract_id,
                Contract.owner_id == owner_id,
            )
            .first()
        )
        if not contract:
            raise ContractNotFoundError(
                f"Contract '{contract_id}' not found. "
                "Verify the ID belongs to your account."
            )

        contract.status     = new_status
        contract.updated_by = actor_id
        db.commit()
        db.refresh(contract)
        return ContractResponse.from_orm_model(contract)

    except (ContractNotFoundError, ContractValidationError):
        db.rollback()
        raise

    except Exception as e:
        db.rollback()
        raise ContractValidationError(
            f"Unexpected error while updating contract status: {str(e)}"
        ) from e


def get_contract(
    db: Session,
    owner_id: uuid.UUID,
    contract_id: uuid.UUID,
) -> ContractResponse:
    contract = (
        db.query(Contract)
        .filter(
            Contract.id == contract_id,
            Contract.owner_id == owner_id,
        )
        .first()
    )
    if not contract:
        raise ContractNotFoundError(
            f"Contract '{contract_id}' not found. "
            "Verify the ID belongs to your account."
        )
    return ContractResponse.from_orm_model(contract)


def list_contracts(
    db: Session,
    owner_id: uuid.UUID,
    status: ContractStatus | None = None,
    include_all: bool = False,
    exclude_archived: bool = False,
    counterparty_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 10,
) -> tuple[list[ContractResponse], int]:
    query = (
        db.query(Contract)
        .filter(Contract.owner_id == owner_id)
    )
    
    if not include_all:
        if status is not None:
            query = query.filter(Contract.status == status)
        elif exclude_archived:
            query = query.filter(Contract.status != ContractStatus.ARCHIVED)
            
    if counterparty_id is not None:
        query = query.filter(Contract.counterparty_id == counterparty_id)

    total = query.count()
    contracts = query.order_by(Contract.created_at.desc()).offset(offset).limit(limit).all()
    return [ContractResponse.from_orm_model(c) for c in contracts], total