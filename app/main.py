# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.db.session import engine
from app.db.base import Base
from app.api.routes import contract
from app.core.config import settings

app = FastAPI(
    title="Contract Management API",
    version="1.0.0",
    description="Production-ready contract management backend.",
)

# Structured CORS configuration for deployment.
# Toggle origins in app/core/config.py or via environment variables.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def create_tables() -> None:
    """
    Creates all tables that don't yet exist.
    Fine for development and small deployments.
    Use Alembic migrations in production so schema changes are versioned.
    """
    Base.metadata.create_all(bind=engine)
    _ensure_contract_columns()


def _ensure_contract_columns() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("contracts")}

    with engine.begin() as conn:
        if "project_type" not in existing_columns:
            conn.execute(
                text(
                    "ALTER TABLE contracts ADD COLUMN project_type VARCHAR(50) NOT NULL DEFAULT 'OTHER'"
                )
            )

        if "contract_code" not in existing_columns:
            conn.execute(
                text(
                    "ALTER TABLE contracts ADD COLUMN contract_code VARCHAR(64)"
                )
            )

        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_contract_code ON contracts (contract_code)"
            )
        )


# Register routers
app.include_router(contract.router, prefix="/api")


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}