"""The frozen types every engine operates on.

Two rules hold throughout, and both exist to stop whole classes of bug:

*   Everything is frozen and uses tuples rather than lists. A plan that cannot
    be mutated in place cannot be half-updated by one engine while another reads it.
*   Every nutrition, weight, and factor value is a ``Decimal``. Floats drift, and
    drift in a shopping list is the kind of error nobody spots until they are
    standing in a shop with the wrong amount of fish.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

Slot = Literal["breakfast", "lunch", "snack", "dinner", "treat"]
Role = Literal["main", "side"]
Template = Literal["normal", "long_shift", "training", "duty_24h"]
Level = Literal["error", "warning", "info"]
FeedbackStatus = Literal["not_tried", "tried"]
Rating = Literal["liked", "neutral", "disliked"]
Satiety = Literal["too_little", "right", "too_much"]
# `as_purchased` is not a weak `estimated`: a yield of 1.0 means the item is eaten
# as bought, which is definitional rather than approximate. Separating the two is
# what makes the calibration backlog the six ingredients that matter rather than
# all forty.
YieldSource = Literal["as_purchased", "estimated", "measured"]

SLOTS: tuple[Slot, ...] = ("breakfast", "lunch", "snack", "dinner", "treat")
DAYS_PER_PLAN = 7

HUNDRED_GRAMS = Decimal(100)

# Dry goods absorb water: rice noodles roughly triple, oats more. The ceiling is a
# sanity bound against a transcription slip, not a statement about cooking.
MAX_YIELD_FACTOR = Decimal(5)


@dataclass(frozen=True, slots=True)
class Totals:
    """Calories and protein for anything from one line to a whole day."""

    kcal: Decimal = Decimal(0)
    protein_g: Decimal = Decimal(0)

    def __add__(self, other: Totals) -> Totals:
        return Totals(self.kcal + other.kcal, self.protein_g + other.protein_g)

    def scaled_by(self, factor: Decimal) -> Totals:
        return Totals(self.kcal * factor, self.protein_g * factor)


ZERO_TOTALS = Totals()


@dataclass(frozen=True, slots=True)
class Ingredient:
    """A catalog item, with the nutrition and shopping facts the engines need.

    ``yield_factor`` is cooked weight divided by raw weight. Meat and fish lose
    water and land below 1 (turkey thigh is 0.65); anything eaten as purchased is
    1.0; dry goods that absorb water go well above 1 (rice noodles are about
    2.85, since 180 g dry yields 510 g cooked). The shopping engine divides by it
    to turn a cooked portion back into something buyable.

    It is a **parameter, not a constant**. Yield bundles trim loss, water exchange
    during cooking, and the ice glaze on frozen seafood, so it varies with method,
    equipment and supplier and can only really be established by weighing.
    ``yield_source`` records whether a factor has been measured, is still an
    estimate, or does not apply because the item is eaten as bought — so what
    remains to review is visible rather than remembered.
    """

    id: str
    names: Mapping[str, str]
    kcal_per_100g: Decimal
    protein_per_100g: Decimal
    yield_factor: Decimal = Decimal(1)
    package_size: Decimal | None = None
    package_unit: str | None = None
    shop_section: str = "other"
    is_staple: bool = False
    yield_source: YieldSource = "as_purchased"

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", MappingProxyType(dict(self.names)))
        if self.yield_factor == Decimal(1) and self.yield_source == "estimated":
            raise ValueError(
                f"{self.id}: a yield of 1.0 is as_purchased, not estimated. "
                "Marking it estimated would put it in the calibration backlog for no reason."
            )
        if not Decimal(0) < self.yield_factor <= MAX_YIELD_FACTOR:
            raise ValueError(
                f"yield_factor for {self.id} must be in (0, {MAX_YIELD_FACTOR}], "
                f"got {self.yield_factor}"
            )
        if self.package_size is not None and self.package_size <= 0:
            raise ValueError(f"package_size for {self.id} must be positive")

    def name(self, locale: str = "ru") -> str:
        """Localised name, falling back to any available name, then the id."""
        return self.names.get(locale) or next(iter(self.names.values()), self.id)


@dataclass(frozen=True, slots=True)
class ModuleLine:
    """One ingredient in a module, in **cooked** grams (PRD 6.1).

    ``size_is_critical`` marks a line where the package size is structural rather
    than a shopping convenience: a module built on a 75 g flatbread does not work
    with a 45 g one, because the filling will not wrap (PRD 6.7).

    ``yield_factor_override`` exists because yield is a property of an ingredient
    *and a preparation*, not of an ingredient alone. The same pepper is bought
    whole and used raw in one dish and roasted in another; roasting costs about a
    third of its weight and being raw costs nothing. One factor per ingredient
    cannot express both, and averaging them is wrong in both directions. Null
    means "use the ingredient's own factor", which covers almost every line.
    """

    ingredient_id: str
    grams_cooked: Decimal
    size_is_critical: bool = False
    yield_factor_override: Decimal | None = None

    def __post_init__(self) -> None:
        if self.grams_cooked <= 0:
            raise ValueError(f"grams_cooked for {self.ingredient_id} must be positive")
        if self.yield_factor_override is not None and not (
            Decimal(0) < self.yield_factor_override <= MAX_YIELD_FACTOR
        ):
            raise ValueError(
                f"yield_factor_override for {self.ingredient_id} must be in "
                f"(0, {MAX_YIELD_FACTOR}], got {self.yield_factor_override}"
            )


@dataclass(frozen=True, slots=True)
class Module:
    """A reusable meal — the unit the planner thinks in.

    Calories and protein are never stored here. They are computed from the lines,
    so correcting an ingredient's nutrition corrects every module that uses it.
    """

    id: str
    name: str
    slot: Slot
    lines: tuple[ModuleLine, ...]
    role: Role = "main"
    batch_portions: int = 1
    tags: frozenset[str] = frozenset()
    prep_notes: str | None = None

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError(f"Module {self.id} has no lines")
        if not 1 <= self.batch_portions <= DAYS_PER_PLAN:
            raise ValueError(
                f"batch_portions for {self.id} must be 1..{DAYS_PER_PLAN}, "
                f"got {self.batch_portions}"
            )


@dataclass(frozen=True, slots=True)
class SlotBudget:
    """Calorie and protein bounds for one slot. Applies to the slot's sum.

    ``optional`` marks a slot that is not expected every day. The treat slot is
    the case: the profile allows three treats a week, so a day without one is
    correct rather than incomplete, and reporting it would be noise.

    ``protein_max`` is nullable because for this kind of plan protein is a floor,
    not a band. Calories need an upper bound — exceeding them defeats the goal.
    Exceeding a protein target does not, so a ceiling would flag a plan for being
    better than asked. Null means no ceiling. See docs/decisions.md D2.
    """

    slot: Slot
    kcal_min: Decimal
    kcal_max: Decimal
    protein_min: Decimal
    protein_max: Decimal | None = None
    optional: bool = False


@dataclass(frozen=True, slots=True)
class IngredientRule:
    """A profile's position on one ingredient: excluded, or allowed up to a limit."""

    ingredient_id: str
    rule: Literal["excluded", "caution"]
    threshold_g: Decimal | None = None

    def __post_init__(self) -> None:
        if self.rule == "caution" and self.threshold_g is None:
            raise ValueError(f"caution rule for {self.ingredient_id} needs a threshold_g")


@dataclass(frozen=True, slots=True)
class FrequencyRule:
    """A weekly limit on a module tag, or a ban on certain day templates.

    Data rather than code: "liver at most once a week" is a row the planner can
    edit, not a branch somebody has to find and change.
    """

    tag: str
    max_per_week: int | None = None
    blocked_on_templates: frozenset[Template] = frozenset()


@dataclass(frozen=True, slots=True)
class Profile:
    """Targets and rules. Set by the planner; Ration never computes them (PRD 7)."""

    id: str
    name: str
    daily_kcal_target: Decimal
    daily_protein_min: Decimal
    daily_protein_target: Decimal
    daily_kcal_tolerance: Decimal = Decimal(50)
    locale: str = "ru"
    slot_budgets: tuple[SlotBudget, ...] = ()
    ingredient_rules: tuple[IngredientRule, ...] = ()
    frequency_rules: tuple[FrequencyRule, ...] = ()

    def budget_for(self, slot: Slot) -> SlotBudget | None:
        return next((b for b in self.slot_budgets if b.slot == slot), None)

    def rule_for(self, ingredient_id: str) -> IngredientRule | None:
        return next((r for r in self.ingredient_rules if r.ingredient_id == ingredient_id), None)


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """One module in one slot on one day.

    A slot holds several of these — one ``main`` and any number of ``side``
    (PRD 3.6). Budgets and validation always apply to the slot's sum.
    """

    id: str
    slot: Slot
    module_id: str
    portion_factor: Decimal = Decimal(1)
    position: int = 0

    def __post_init__(self) -> None:
        if not Decimal("0.5") <= self.portion_factor <= Decimal("1.5"):
            raise ValueError(
                f"portion_factor for entry {self.id} must be 0.5..1.5, got {self.portion_factor}"
            )


@dataclass(frozen=True, slots=True)
class PlanDay:
    """One day of a plan. May be unplanned — that is normal, not broken."""

    day_index: int
    date: date
    day_template: Template = "normal"
    entries: tuple[PlanEntry, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.day_index < DAYS_PER_PLAN:
            raise ValueError(f"day_index must be 0..{DAYS_PER_PLAN - 1}, got {self.day_index}")

    def entries_in(self, slot: Slot) -> tuple[PlanEntry, ...]:
        return tuple(e for e in self.entries if e.slot == slot)

    @property
    def is_planned(self) -> bool:
        return bool(self.entries)


@dataclass(frozen=True, slots=True)
class Plan:
    """Exactly seven days (PRD 3.6), so "per week" needs no rolling-window logic."""

    id: str
    name: str
    profile_id: str
    start_date: date
    days: tuple[PlanDay, ...]
    status: Literal["draft", "active", "archived"] = "draft"

    def __post_init__(self) -> None:
        if len(self.days) != DAYS_PER_PLAN:
            raise ValueError(f"A plan has exactly {DAYS_PER_PLAN} days, got {len(self.days)}")
        indexes = [d.day_index for d in self.days]
        if indexes != list(range(DAYS_PER_PLAN)):
            raise ValueError(f"Plan days must be indexed 0..{DAYS_PER_PLAN - 1}, got {indexes}")

    @property
    def all_entries(self) -> tuple[PlanEntry, ...]:
        return tuple(entry for day in self.days for entry in day.entries)


@dataclass(frozen=True, slots=True)
class Feedback:
    """The follower's verdict on one planned meal.

    ``status`` and ``rating`` lead because that is what the real pilot produced;
    bloating and satiety went unreported for a whole week (PRD 3.7).
    """

    plan_entry_id: str
    status: FeedbackStatus = "not_tried"
    rating: Rating | None = None
    bloating: int | None = None
    satiety: Satiety | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.bloating is not None and not 0 <= self.bloating <= 3:
            raise ValueError(f"bloating must be 0..3, got {self.bloating}")


@dataclass(frozen=True, slots=True)
class Catalog:
    """Everything an engine needs to look up while computing."""

    ingredients: Mapping[str, Ingredient] = MappingProxyType({})
    modules: Mapping[str, Module] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "ingredients", MappingProxyType(dict(self.ingredients)))
        object.__setattr__(self, "modules", MappingProxyType(dict(self.modules)))

    def ingredient(self, ingredient_id: str) -> Ingredient:
        try:
            return self.ingredients[ingredient_id]
        except KeyError:
            raise KeyError(f"Unknown ingredient: {ingredient_id}") from None

    def module(self, module_id: str) -> Module:
        try:
            return self.modules[module_id]
        except KeyError:
            raise KeyError(f"Unknown module: {module_id}") from None
