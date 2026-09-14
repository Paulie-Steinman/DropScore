"""Database setup — SQLite for local dev, configurable via DB_PATH env var."""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Default to local file; Railway volume path overrides via env
db_path = os.getenv("DB_PATH", "app.db")
db_url = f"sqlite:///{db_path}"

engine = create_engine(db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if they don't exist."""
    import app.models  # noqa: ensure models are registered
    Base.metadata.create_all(bind=engine)