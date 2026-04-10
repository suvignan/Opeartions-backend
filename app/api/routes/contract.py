# app/api/routes/contracts.py
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.enums import ContractStatus
from app.core.exceptions import (
    ContractBaseError,
    ContractNotFoundError,
    CounterpartyNotFoundError,
    ContractValidationError,
    DuplicateContractError,
    DuplicateCounterpartyError,
)
from app.schemas.contract import (
    CreateContractRequest,
    UpdateContractStatusRequest,
    UpdateContractRequest,
    ContractResponse,
)
from app.schemas.pagination import (
    PaginatedContractResponse as ContractListResponse,
    PaginationMeta,
)
from app.services import contract_service

router = APIRouter(prefix="/contracts", tags=["Contracts"])


# ── Dependencies ───────────────────────────────────────────────────────────────

def get_owner_id() -> uuid.UUID:
    """
    Placeholder until JWT middleware is wired.
    Replace with bearer token decode in production.
    Every route receives owner_id from this dependency —
    never from the request body, so callers cannot spoof ownership.
    """
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_actor_id() -> uuid.UUID:
    """
    Same UUID as owner for now.
    Will diverge when service accounts or admin impersonation are supported.
    """
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


# Annotated aliases — keeps route signatures readable, not boilerplate-heavy.
DBSession = Annotated[Session,   Depends(get_db)]
OwnerID   = Annotated[uuid.UUID, Depends(get_owner_id)]
ActorID   = Annotated[uuid.UUID, Depends(get_actor_id)]


# ── Exception → HTTP mapper ────────────────────────────────────────────────────

def _handle_error(e: Exception) -> None:
    """
    Translates domain exceptions to HTTP responses.
    One place to update when status codes change.

        ContractNotFoundError       → 404
        CounterpartyNotFoundError   → 404
        DuplicateContractError      → 409
        DuplicateCounterpartyError  → 409
        ContractValidationError     → 400
        ContractBaseError (others)  → 500
    """
    if isinstance(e, (ContractNotFoundError, CounterpartyNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    if isinstance(e, (DuplicateContractError, DuplicateCounterpartyError)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message)
    if isinstance(e, ContractValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    if isinstance(e, ContractBaseError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unhandled domain error: {e.message}",
        )


# ── Allowed status transitions ─────────────────────────────────────────────────
# Route-layer concern: which transitions are permitted via the API.
# Kept here (not in the service) because this is an API contract decision,
# not a storage decision. The service just applies whatever status it receives.

_ALLOWED_TRANSITIONS: dict[ContractStatus, set[ContractStatus]] = {
    ContractStatus.PENDING_REVIEW: {ContractStatus.ACTIVE},
    ContractStatus.ACTIVE:         {ContractStatus.ARCHIVED, ContractStatus.EXPIRED},
    ContractStatus.ARCHIVED:       {ContractStatus.ACTIVE},   # restore supported
    ContractStatus.EXPIRED:        set(),                      # terminal — no transitions out
}


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new contract",
    responses={
        201: {"description": "Contract created successfully"},
        400: {"description": "Validation error (e.g. acv > tcv, bad dates)"},
        404: {"description": "Referenced counterparty not found"},
        409: {"description": "Duplicate contract or counterparty conflict"},
    },
)
def create_contract(
    payload:  CreateContractRequest,
    db:       DBSession,
    owner_id: OwnerID,
    actor_id: ActorID,
) -> ContractResponse:
    """
    Create a new contract for the authenticated owner.

    **Counterparty resolution:**
    - Pass `counterparty_id` to link an existing counterparty.
    - Pass `counterparty.name` to create one inline (idempotent by normalized name).
    - Passing both or neither is a validation error.
    """
    try:
        return contract_service.create_contract(db, owner_id, payload, actor_id=actor_id)
    except Exception as e:
        _handle_error(e)
        raise  # unreachable — keeps type checkers satisfied


@router.get(
    "/",
    response_model=ContractListResponse,
    summary="List contracts with pagination and optional filters",
    responses={
        200: {"description": "Paginated contract list"},
        400: {"description": "Invalid status filter value"},
    },
)
def list_contracts(
    db:       DBSession,
    owner_id: OwnerID,
    page: Annotated[
        int,
        Query(ge=1, description="Page number, 1-indexed"),
    ] = 1,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Results per page (max 100)"),
    ] = 10,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter by contract status. "
                "Valid values: PENDING_REVIEW, ACTIVE, EXPIRED, ARCHIVED, ALL. "
                "Omitting this param excludes ARCHIVED contracts by default."
            ),
        ),
    ] = None,
    counterparty_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter results to a specific counterparty UUID"),
    ] = None,
) -> ContractListResponse:
    """
    Returns a paginated list of contracts owned by the authenticated user.

    **Status filter behaviour:**
    | `status` param  | What is returned                        |
    |-----------------|-----------------------------------------|
    | Omitted         | All statuses except ARCHIVED (default)  |
    | `ACTIVE`        | Active contracts only                   |
    | `ARCHIVED`      | Archived contracts only                 |
    | `PENDING_REVIEW`| Pending review contracts only           |
    | `EXPIRED`       | Expired contracts only                  |
    | `ALL`           | Every contract regardless of status     |

    **Pagination:** offset-based. `offset = (page - 1) * limit`.
    `meta.total` is the count of all matching rows before pagination,
    so the client can compute total pages as `ceil(total / limit)`.
    """

    # ── Resolve status filter ─────────────────────────────────────────────────
    include_all     = False
    exclude_archived = False
    resolved_status: ContractStatus | None = None

    if status_filter is None:
        # Default: exclude ARCHIVED so standard list views only show live contracts.
        exclude_archived = True

    elif status_filter.upper() == "ALL":
        include_all = True

    else:
        try:
            resolved_status = ContractStatus(status_filter.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"'{status_filter}' is not a valid status filter. "
                    f"Valid values: {[s.value for s in ContractStatus] + ['ALL']}."
                ),
            )

    # ── Call service ──────────────────────────────────────────────────────────
    try:
        contracts, total = contract_service.list_contracts(
            db=db,
            owner_id=owner_id,
            status=resolved_status,
            include_all=include_all,
            exclude_archived=exclude_archived,
            counterparty_id=counterparty_id,
            offset=(page - 1) * limit,
            limit=limit,
        )
    except Exception as e:
        _handle_error(e)
        raise

    return ContractListResponse(
        data=contracts,
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get(
    "/{contract_id}",
    response_model=ContractResponse,
    summary="Get a contract by ID",
    responses={
        200: {"description": "Contract found"},
        404: {"description": "Contract not found"},
    },
)
def get_contract_route(
    contract_id: uuid.UUID,
    db:          DBSession,
    owner_id:    OwnerID,
) -> ContractResponse:
    """
    Retrieves a single contract by ID.
    Returns 404 if the contract does not exist or does not belong to the owner.
    """
    try:
        return contract_service.get_contract(db, owner_id, contract_id)
    except Exception as e:
        _handle_error(e)
        raise

@router.patch(
    "/{contract_id}",
    response_model=ContractResponse,
    summary="Partially update a contract's fields",
    responses={
        200: {"description": "Contract updated successfully"},
        400: {"description": "Validation error (e.g. merged dates invalid)"},
        404: {"description": "Contract or counterparty not found"},
        409: {"description": "Update would create a duplicate contract"},
    },
)
def update_contract(
    contract_id: uuid.UUID,
    payload:     Annotated[UpdateContractRequest, Body(...)],
    db:          DBSession,
    owner_id:    OwnerID,
    actor_id:    ActorID,
) -> ContractResponse:
    """
    Partially update a contract's counterparty, financials, or timeline.

    Only fields you include are written — omitting a field leaves the
    current database value unchanged.

    Cross-field rules (acv <= tcv, end >= start) are validated AFTER
    merging your changes with existing DB values, so sending only
    one side of a pair is still fully validated.

    Does NOT change status — use PATCH /{id}/status for that.
    """
    try:
        return contract_service.update_contract(
            db=db,
            owner_id=owner_id,
            contract_id=contract_id,
            request=payload,
            actor_id=actor_id,
        )
    except Exception as e:
        _handle_error(e)
        raise


@router.patch(
    "/{contract_id}/status",
    response_model=ContractResponse,
    summary="Transition a contract's status",
    responses={
        200: {"description": "Status updated successfully"},
        400: {"description": "Invalid or disallowed status transition"},
        404: {"description": "Contract not found"},
        409: {"description": "Conflict"},
    },
)
def update_contract_status(
    contract_id: uuid.UUID,
    payload:     Annotated[UpdateContractStatusRequest, Body(...)],
    db:          DBSession,
    owner_id:    OwnerID,
    actor_id:    ActorID,
) -> ContractResponse:
    """
    Transition a contract to a new status.

    **Allowed transitions:**
    | From             | To                        |
    |------------------|---------------------------|
    | `PENDING_REVIEW` | `ACTIVE`                  |
    | `ACTIVE`         | `ARCHIVED`, `EXPIRED`     |
    | `ARCHIVED`       | `ACTIVE` *(restore)*      |
    | `EXPIRED`        | *(none — terminal state)* |

    Attempting any other transition returns HTTP 400.
    Attempting to update a contract that does not belong to the authenticated
    owner returns HTTP 404 (not 403) to avoid leaking resource existence.
    """

    # Fetch current state to validate transition before hitting the service.
    try:
        current = contract_service.get_contract(db, owner_id, contract_id)
    except Exception as e:
        _handle_error(e)
        raise

    # ── Transition guard ──────────────────────────────────────────────────────
    allowed = _ALLOWED_TRANSITIONS.get(current.status, set())
    if payload.status not in allowed:
        allowed_labels = [s.value for s in allowed]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot transition '{current.status.value}' → '{payload.status.value}'. "
                f"Allowed transitions from '{current.status.value}': "
                f"{allowed_labels if allowed_labels else 'none (terminal state)'}."
            ),
        )

    try:
        return contract_service.update_contract_status(
            db=db,
            owner_id=owner_id,
            contract_id=contract_id,
            new_status=payload.status,
            actor_id=actor_id,
        )
    except Exception as e:
        _handle_error(e)
        raise