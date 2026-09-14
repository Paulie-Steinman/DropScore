"""SQLAlchemy models for DropScore."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Index

from app.database import Base


class Variant(Base):
    """One jigged address variant with scoring."""
    __tablename__ = "variants"

    id = Column(Integer, primary_key=True)
    base_raw = Column(String, default="")       # original input
    line1 = Column(String, nullable=False)
    line2 = Column(String, default="")
    city = Column(String, default="")
    state = Column(String, default="")
    zip5 = Column(String, default="")
    zip4 = Column(String, default="")
    full_address = Column(String, nullable=False)
    retailer = Column(String, default="")
    format_type = Column(String, default="")
    attempts = Column(Integer, default=0)
    successes = Column(Integer, default=0)
    score = Column(Float, default=0.5)
    status = Column(String, default="active")   # active, flagged, retired
    last_drop = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_variant_full_addr", "full_address"),
        Index("idx_variant_retailer", "retailer"),
        Index("idx_variant_score", "score"),
        Index("idx_variant_status", "status"),
    )

    @property
    def bayesian_score(self) -> float:
        return round((self.successes + 1) / (self.attempts + 2), 3)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "base_raw": self.base_raw,
            "line1": self.line1,
            "line2": self.line2,
            "city": self.city,
            "state": self.state,
            "zip": f"{self.zip5}-{self.zip4}" if self.zip4 else self.zip5,
            "full_address": self.full_address,
            "retailer": self.retailer,
            "format_type": self.format_type,
            "attempts": self.attempts,
            "successes": self.successes,
            "score": self.score,
            "status": self.status,
            "last_drop": self.last_drop.isoformat() if self.last_drop else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }