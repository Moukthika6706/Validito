from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, str_enum, utcnow
from app.models.enums import FlagSource, FlagStatus, ReviewAction, RoutingDecision, RunStatus, Severity


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rule_pack_id: Mapped[int | None] = mapped_column(ForeignKey("rule_packs.id"), nullable=True)
    ml_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus), default=RunStatus.running, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    routing_decision: Mapped[RoutingDecision | None] = mapped_column(str_enum(RoutingDecision), nullable=True)
    routing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="validation_runs")
    rule_pack = relationship("RulePack")
    flags = relationship("Flag", back_populates="validation_run", cascade="all, delete-orphan")


class Flag(TimestampMixin, Base):
    """An explainable finding. Every column after `source` exists so a reviewer can
    see *why* the flag fired without consulting any code."""

    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("extracted_entities.id", ondelete="SET NULL"), nullable=True
    )

    source: Mapped[FlagSource] = mapped_column(str_enum(FlagSource), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    rule_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[Severity] = mapped_column(str_enum(Severity), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[FlagStatus] = mapped_column(
        str_enum(FlagStatus), default=FlagStatus.open, index=True, nullable=False
    )

    validation_run = relationship("ValidationRun", back_populates="flags")
    document = relationship("Document", back_populates="flags")
    entity = relationship("ExtractedEntity")
    review_actions = relationship(
        "ReviewActionRecord", back_populates="flag", cascade="all, delete-orphan",
        order_by="ReviewActionRecord.id",
    )


class ReviewActionRecord(TimestampMixin, Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flag_id: Mapped[int] = mapped_column(
        ForeignKey("flags.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    action: Mapped[ReviewAction] = mapped_column(str_enum(ReviewAction), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    flag = relationship("Flag", back_populates="review_actions")
    reviewer = relationship("User")
