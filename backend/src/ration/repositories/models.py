"""SQLAlchemy models.

Portable types only. The same schema runs on SQLite in development and Postgres
everywhere else (HLD AD-4), so there are no JSON columns, no arrays, and no
Postgres-only types. Ids are CHAR(36) rather than a native UUID for the same
reason.

Every nutrition and weight column is Numeric, never Float. The domain layer uses
Decimal throughout to keep a shopping list exact, and a Float column would undo
that at the storage boundary — the one place it would be hardest to notice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ID = String(36)

# Nutrition values: generous precision, because they are per 100 g and get
# multiplied by portion weights before anything is rounded.
MONEYLIKE = Numeric(12, 4)


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (CheckConstraint("role IN ('planner', 'follower')", name="ck_user_role"),)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    planner_user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    follower_user_id: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"))
    locale: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)

    daily_kcal_target: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    daily_kcal_tolerance: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    daily_protein_min: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    daily_protein_target: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    slot_budgets: Mapped[list[SlotBudget]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    ingredient_rules: Mapped[list[ProfileIngredientRule]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    frequency_rules: Mapped[list[FrequencyRule]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class SlotBudget(Base):
    __tablename__ = "slot_budgets"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ID, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    kcal_min: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    kcal_max: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    protein_min: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    # Nullable: protein is a floor, not a band (docs/decisions.md D2).
    protein_max: Mapped[Decimal | None] = mapped_column(MONEYLIKE)
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    profile: Mapped[Profile] = relationship(back_populates="slot_budgets")

    __table_args__ = (UniqueConstraint("profile_id", "slot", name="uq_slot_budget"),)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kcal_per_100g: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    protein_per_100g: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    yield_factor: Mapped[Decimal] = mapped_column(MONEYLIKE, default=Decimal(1), nullable=False)
    package_size: Mapped[Decimal | None] = mapped_column(MONEYLIKE)
    package_unit: Mapped[str | None] = mapped_column(String(8))
    shop_section: Mapped[str] = mapped_column(String(24), default="other", nullable=False)
    is_staple: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    names: Mapped[list[IngredientName]] = relationship(
        back_populates="ingredient", cascade="all, delete-orphan", lazy="selectin"
    )
    aliases: Mapped[list[IngredientAlias]] = relationship(
        back_populates="ingredient", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (CheckConstraint("yield_factor > 0", name="ck_ingredient_yield_positive"),)


class IngredientName(Base):
    __tablename__ = "ingredient_names"

    ingredient_id: Mapped[str] = mapped_column(
        ID, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    ingredient: Mapped[Ingredient] = relationship(back_populates="names")


class IngredientAlias(Base):
    __tablename__ = "ingredient_aliases"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    ingredient_id: Mapped[str] = mapped_column(
        ID, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    alias: Mapped[str] = mapped_column(String(120), nullable=False)

    ingredient: Mapped[Ingredient] = relationship(back_populates="aliases")

    __table_args__ = (UniqueConstraint("locale", "alias", name="uq_alias"),)


class ProfileIngredientRule(Base):
    """Exclusions and cautions belong to the profile, not the ingredient.

    The same catalog can then serve a second person who tolerates something this
    one does not.
    """

    __tablename__ = "profile_ingredient_rules"

    profile_id: Mapped[str] = mapped_column(
        ID, ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        ID, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    rule: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold_g: Mapped[Decimal | None] = mapped_column(MONEYLIKE)

    profile: Mapped[Profile] = relationship(back_populates="ingredient_rules")

    __table_args__ = (
        CheckConstraint("rule IN ('excluded', 'caution')", name="ck_ingredient_rule"),
    )


class FrequencyRule(Base):
    __tablename__ = "frequency_rules"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ID, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(32), nullable=False)
    max_per_week: Mapped[int | None] = mapped_column(SmallInteger)
    # Comma-separated rather than JSON, to stay portable across SQLite and
    # Postgres (HLD AD-4). The list is at most four short enum values.
    blocked_on_templates: Mapped[str | None] = mapped_column(String(255))

    profile: Mapped[Profile] = relationship(back_populates="frequency_rules")

    __table_args__ = (UniqueConstraint("profile_id", "tag", name="uq_frequency_rule"),)


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    role: Mapped[str] = mapped_column(String(8), default="main", nullable=False)
    batch_portions: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    prep_notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    lines: Mapped[list[ModuleLine]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="ModuleLine.position",
        lazy="selectin",
    )
    tags: Mapped[list[ModuleTag]] = relationship(
        back_populates="module", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("role IN ('main', 'side')", name="ck_module_role"),
        CheckConstraint("batch_portions BETWEEN 1 AND 7", name="ck_module_batch"),
    )


class ModuleLine(Base):
    __tablename__ = "module_lines"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    module_id: Mapped[str] = mapped_column(
        ID, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(ID, ForeignKey("ingredients.id"), nullable=False)
    # Cooked weight (PRD 6.1): what gets weighed when packing a container.
    grams_cooked: Mapped[Decimal] = mapped_column(MONEYLIKE, nullable=False)
    size_is_critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Yield is a property of an ingredient AND a preparation: the same pepper is
    # raw in one dish and roasted in another. Null means use the ingredient's own
    # factor, which covers almost every line (docs/decisions.md D4).
    yield_factor_override: Mapped[Decimal | None] = mapped_column(MONEYLIKE)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    module: Mapped[Module] = relationship(back_populates="lines")

    __table_args__ = (
        UniqueConstraint("module_id", "position", name="uq_module_line_position"),
        CheckConstraint("grams_cooked > 0", name="ck_module_line_grams"),
    )


class ModuleTag(Base):
    __tablename__ = "module_tags"

    module_id: Mapped[str] = mapped_column(
        ID, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(32), primary_key=True)

    module: Mapped[Module] = relationship(back_populates="tags")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True)
    profile_id: Mapped[str] = mapped_column(ID, ForeignKey("profiles.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    days: Mapped[list[PlanDay]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanDay.day_index",
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_plan_status"),
    )


class PlanDay(Base):
    __tablename__ = "plan_days"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(
        ID, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    day_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    day_template: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[Plan] = relationship(back_populates="days")
    entries: Mapped[list[PlanEntry]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="PlanEntry.position",
    )

    __table_args__ = (
        UniqueConstraint("plan_id", "day_index", name="uq_plan_day"),
        CheckConstraint("day_index BETWEEN 0 AND 6", name="ck_plan_day_index"),
    )


class PlanEntry(Base):
    """One module in one slot on one day.

    A slot holds at most one `main` and any number of `side`. That is enforced in
    the service layer rather than by a partial unique index, which SQLite cannot
    express portably.
    """

    __tablename__ = "plan_entries"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    plan_day_id: Mapped[str] = mapped_column(
        ID, ForeignKey("plan_days.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    module_id: Mapped[str] = mapped_column(ID, ForeignKey("modules.id"), nullable=False)
    portion_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal(1), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    day: Mapped[PlanDay] = relationship(back_populates="entries")
    feedback: Mapped[Feedback | None] = relationship(
        back_populates="entry", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("plan_day_id", "slot", "position", name="uq_plan_entry_position"),
        CheckConstraint("portion_factor >= 0.5 AND portion_factor <= 1.5", name="ck_entry_portion"),
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    plan_entry_id: Mapped[str] = mapped_column(
        ID, ForeignKey("plan_entries.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), default="tried", nullable=False)
    rating: Mapped[str | None] = mapped_column(String(12))
    bloating: Mapped[int | None] = mapped_column(SmallInteger)
    satiety: Mapped[str | None] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    entry: Mapped[PlanEntry] = relationship(back_populates="feedback")

    __table_args__ = (
        CheckConstraint("status IN ('not_tried', 'tried')", name="ck_feedback_status"),
        CheckConstraint(
            "bloating IS NULL OR bloating BETWEEN 0 AND 3", name="ck_feedback_bloating"
        ),
    )


class ShoppingCheckState(Base):
    """Ticked-off items, stored server-side rather than in the browser.

    The follower may shop on a different device than they planned on, and nothing
    in the system may depend on them maintaining anything (PRD 2.1).
    """

    __tablename__ = "shopping_check_state"

    plan_id: Mapped[str] = mapped_column(
        ID, ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        ID, ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    checked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


ALL_TABLES = tuple(sorted(Base.metadata.tables))
