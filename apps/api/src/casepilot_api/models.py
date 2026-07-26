from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaseStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class AccountSession(TimestampMixin, Base):
    __tablename__ = "account_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Space(TimestampMixin, Base):
    __tablename__ = "spaces"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SpaceMembership(TimestampMixin, Base):
    __tablename__ = "space_memberships"
    __table_args__ = (
        UniqueConstraint("space_id", "account_id", name="uq_space_membership"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="owner")


class CaseCollection(TimestampMixin, Base):
    __tablename__ = "case_collections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class TestCase(TimestampMixin, Base):
    __tablename__ = "test_cases"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    current_status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status", values_callable=enum_values),
        default=CaseStatus.PENDING,
        nullable=False,
        index=True,
    )


class TestCaseRevision(TimestampMixin, Base):
    __tablename__ = "test_case_revisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    test_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    preconditions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    steps: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list, nullable=False)
    source_refs: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list, nullable=False)


class TestCaseStatusEvent(TimestampMixin, Base):
    __tablename__ = "test_case_status_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    test_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_case_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_status: Mapped[CaseStatus | None] = mapped_column(
        Enum(CaseStatus, name="case_status", values_callable=enum_values),
    )
    to_status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status", values_callable=enum_values),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class GenerationJob(TimestampMixin, Base):
    __tablename__ = "generation_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(
            GenerationStatus,
            name="generation_status",
            values_callable=enum_values,
        ),
        default=GenerationStatus.QUEUED,
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(80), default="queued", nullable=False)
    input_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
