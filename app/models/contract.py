# app/models/contract.py
from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    String, Integer, Boolean, Date,
    ForeignKey, CheckConstraint, UniqueConstraint,
    Enum as SAEnum, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.enums import ContractStatus

if TYPE_CHECKING:
    from app.models.counterparty import Counterparty


class Contract(Base):
    __tablename__ = "contracts"

    __table_args__ = (
        CheckConstraint(
            "(acv_cents IS NULL OR tcv_cents IS NULL) OR (acv_cents <= tcv_cents)",
            name="ck_contract_acv_lte_tcv",
        ),
        CheckConstraint(
            "project_type IN ('WEB_APP','MOBILE_APP','ML_PROJECT','DATA_PIPELINE','OTHER')",
            name="ck_contract_project_type_allowed",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_contract_end_gte_start",
        ),
        UniqueConstraint(
            "owner_id", "counterparty_id", "start_date",
            name="uq_contract_owner_counterparty_start",
        ),
    )

    # ── Ownership ──────────────────────────────────────────────────────────────
    owner_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    # ── Audit fields ───────────────────────────────────────────────────────────
    # Populated by the service layer from the authenticated user context.
    # Nullable for now — tighten to nullable=False once auth is fully wired.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="UUID of the user who created this contract",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="UUID of the user who last modified this contract",
    )

    # ── Counterparty ───────────────────────────────────────────────────────────
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Financials ─────────────────────────────────────────────────────────────
    tcv_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acv_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # DB stores String(3); Pydantic enum validates the value at API boundary.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    # ── Core Details ───────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''"))
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contract_code: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=True,
    )
    project_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="OTHER",
        server_default=text("'OTHER'"),
    )

    # ── Timeline ───────────────────────────────────────────────────────────────
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Status ─────────────────────────────────────────────────────────────────
    # SAEnum reads the ContractStatus members and creates a DB-level enum type
    # (Postgres) or a VARCHAR with a check constraint (SQLite).
    # native_enum=False keeps it as VARCHAR in Postgres too — avoids ALTER TYPE
    # migrations when you add a new status value.
    status: Mapped[ContractStatus] = mapped_column(
        SAEnum(ContractStatus, native_enum=False, length=50),
        nullable=False,
        default=ContractStatus.PENDING_REVIEW,
        server_default=text("'PENDING_REVIEW'"),
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    counterparty: Mapped["Counterparty"] = relationship(
        "Counterparty",
        back_populates="contracts",
        lazy="selectin",
    )