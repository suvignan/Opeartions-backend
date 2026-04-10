from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    # SQLite-only: allows the same connection across threads (needed for FastAPI)
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_pre_ping=True,   # drops stale connections before using them
    echo=settings.DEBUG,  # logs all SQL in dev; set DEBUG=False in prod
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """
    FastAPI dependency. Yields a session, guarantees close even on exception.
    Usage in route: db: Session = Depends(get_db)
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()