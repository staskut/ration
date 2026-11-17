"""Turn the fixture YAML into domain types.

Every number arrives as a string and is converted with ``Decimal``. YAML would
otherwise hand back binary floats, which would quietly undo the precision the
whole domain layer is built on — and the resulting drift would look like an
engine bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import yaml

from ration.domain.types import (
    Catalog,
    Feedback,
    FrequencyRule,
    Ingredient,
    IngredientRule,
    Module,
    ModuleLine,
    Plan,
    PlanDay,
    PlanEntry,
    Profile,
    Rating,
    Role,
    Slot,
    SlotBudget,
    Template,
)

SEED_DIR = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class ReferenceData:
    """Everything the fixture describes, ready for an engine or a database."""

    catalog: Catalog
    profile: Profile
    plan: Plan
    feedback_by_module: dict[str, Feedback]


def load_reference(directory: Path | None = None) -> ReferenceData:
    """Load the reference plan. Pure file reading; no database involved."""
    root = directory or SEED_DIR
    catalog = Catalog(
        ingredients=_load_ingredients(root / "ingredients.yaml"),
        modules=_load_modules(root / "modules.yaml"),
    )
    profile = _load_profile(root / "profile.yaml")
    plan = _load_plan(root / "plan.yaml")
    feedback = _load_feedback(root / "feedback.yaml")
    _check_references(catalog, plan)
    return ReferenceData(catalog, profile, plan, feedback)


def load_module_claims(directory: Path | None = None) -> dict[str, tuple[Decimal, Decimal]]:
    """The kcal and protein each module *claims*, as stated in the document.

    Used by the fixture tests to check a transcription against the figures a
    human wrote, rather than against whatever the code happens to compute.
    """
    root = directory or SEED_DIR
    raw = _read(root / "modules.yaml")
    return {
        entry["slug"]: (_dec(entry["stated_kcal"]), _dec(entry["stated_protein"])) for entry in raw
    }


def _load_ingredients(path: Path) -> dict[str, Ingredient]:
    return {
        entry["slug"]: Ingredient(
            id=entry["slug"],
            names={
                locale: entry[key]
                for locale, key in (("ru", "name_ru"), ("en", "name_en"))
                if entry.get(key)
            },
            kcal_per_100g=_dec(entry["kcal_per_100g"]),
            protein_per_100g=_dec(entry["protein_per_100g"]),
            yield_factor=_dec(entry["yield_factor"]),
            package_size=_opt_dec(entry.get("package_size")),
            package_unit=entry.get("package_unit"),
            shop_section=entry.get("shop_section", "other"),
            is_staple=bool(entry.get("is_staple", False)),
            # Default by shape: anything with a yield of 1.0 is used as bought.
            yield_source=entry.get(
                "yield_source",
                "as_purchased" if _dec(entry["yield_factor"]) == 1 else "estimated",
            ),
        )
        for entry in _read(path)
    }


def _load_modules(path: Path) -> dict[str, Module]:
    return {
        entry["slug"]: Module(
            id=entry["slug"],
            name=entry["name"],
            slot=cast(Slot, entry["slot"]),
            role=cast(Role, entry.get("role", "main")),
            batch_portions=int(entry.get("batch_portions", 1)),
            tags=frozenset(entry.get("tags", [])),
            prep_notes=entry.get("prep_notes"),
            lines=tuple(
                ModuleLine(
                    ingredient_id=line["ingredient"],
                    grams_cooked=_dec(line["grams_cooked"]),
                    size_is_critical=bool(line.get("size_is_critical", False)),
                    yield_factor_override=_opt_dec(line.get("yield_factor_override")),
                )
                for line in entry["lines"]
            ),
        )
        for entry in _read(path)
    }


def _load_profile(path: Path) -> Profile:
    raw = _read(path)
    return Profile(
        id=raw["id"],
        name=raw["name"],
        locale=raw.get("locale", "ru"),
        daily_kcal_target=_dec(raw["daily_kcal_target"]),
        daily_kcal_tolerance=_dec(raw["daily_kcal_tolerance"]),
        daily_protein_min=_dec(raw["daily_protein_min"]),
        daily_protein_target=_dec(raw["daily_protein_target"]),
        slot_budgets=tuple(
            SlotBudget(
                slot=cast(Slot, b["slot"]),
                kcal_min=_dec(b["kcal_min"]),
                kcal_max=_dec(b["kcal_max"]),
                protein_min=_dec(b["protein_min"]),
                protein_max=_opt_dec(b.get("protein_max")),
                optional=bool(b.get("optional", False)),
            )
            for b in raw.get("slot_budgets", [])
        ),
        ingredient_rules=tuple(
            IngredientRule(
                ingredient_id=r["ingredient"],
                rule=r["rule"],
                threshold_g=_opt_dec(r.get("threshold_g")),
            )
            for r in raw.get("ingredient_rules", [])
        ),
        frequency_rules=tuple(
            FrequencyRule(
                tag=r["tag"],
                max_per_week=r.get("max_per_week"),
                blocked_on_templates=frozenset(
                    cast(list[Template], r.get("blocked_on_templates", []))
                ),
            )
            for r in raw.get("frequency_rules", [])
        ),
    )


def _load_plan(path: Path) -> Plan:
    raw = _read(path)
    start = date.fromisoformat(raw["start_date"])
    days = tuple(
        PlanDay(
            day_index=day["day_index"],
            date=start + timedelta(days=day["day_index"]),
            day_template=cast(Template, day.get("day_template", "normal")),
            notes=day.get("notes"),
            entries=tuple(
                PlanEntry(
                    id=f"{raw['id']}-d{day['day_index']}-{position}",
                    slot=cast(Slot, entry["slot"]),
                    module_id=entry["module"],
                    portion_factor=_dec(entry.get("portion_factor", "1")),
                    position=position,
                )
                for position, entry in enumerate(day.get("entries") or [])
            ),
        )
        for day in raw["days"]
    )
    return Plan(
        id=raw["id"],
        name=raw["name"],
        profile_id=raw["profile_id"],
        start_date=start,
        status=raw.get("status", "draft"),
        days=days,
    )


def _load_feedback(path: Path) -> dict[str, Feedback]:
    return {
        entry["module"]: Feedback(
            plan_entry_id=entry["module"],
            status=entry.get("status", "not_tried"),
            rating=cast(Rating | None, entry.get("rating")),
            bloating=entry.get("bloating"),
            satiety=entry.get("satiety"),
            note=entry.get("note"),
        )
        for entry in _read(path)
    }


def _check_references(catalog: Catalog, plan: Plan) -> None:
    """Fail loudly at load time rather than deep inside an engine."""
    for module in catalog.modules.values():
        for line in module.lines:
            if line.ingredient_id not in catalog.ingredients:
                raise ValueError(
                    f"Module {module.id} references unknown ingredient {line.ingredient_id}"
                )
    for entry in plan.all_entries:
        if entry.module_id not in catalog.modules:
            raise ValueError(f"Plan entry {entry.id} references unknown module {entry.module_id}")


def _read(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _opt_dec(value: object) -> Decimal | None:
    return None if value is None else _dec(value)
