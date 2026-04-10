# app/models/counterparty.py
import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Counterparty(Base):
    __tablename__ = "counterparties"

    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_name",
            name="uq_counterparty_owner_name",
        ),
    )

    # ── Ownership ──────────────────────────────────────────────────────────────
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    # ── Audit fields ───────────────────────────────────────────────────────────
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="UUID of the user who created this counterparty",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="UUID of the user who last modified this counterparty",
    )

    # ── Fields ─────────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    contracts: Mapped[list["Contract"]] = relationship(
        "Contract",
        back_populates="counterparty",
        lazy="select",
    )