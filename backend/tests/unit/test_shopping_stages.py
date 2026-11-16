"""The pipeline split must not have changed the answer.

`domain.shopping.shopping_list()` is the engine's own composition and the one
the golden test exercises. `api/pipelines.py` runs the same stages one at a
time so each can be a span (#56). Two compositions of the same stages is one
more than is safe to leave unguarded, so this asserts they agree — on the
reference plan, line for line, Decimal for Decimal.
"""

from __future__ import annotations

from decimal import Decimal

from ration.domain.shopping import (
    convert_to_raw,
    expand_entries,
    group_by_shop_section,
    merge_by_ingredient,
    round_to_packages,
    shopping_list,
)
from ration.seed import load_reference

REFERENCE = load_reference()


def _by_hand(locale: str = "ru"):  # type: ignore[no-untyped-def]
    cooked = expand_entries(REFERENCE.plan, REFERENCE.catalog)
    raw = convert_to_raw(cooked)
    merged = merge_by_ingredient(raw)
    rounded = round_to_packages(merged, REFERENCE.catalog, locale)
    return group_by_shop_section(rounded)


def test_stages_compose_to_the_same_list() -> None:
    assert _by_hand() == shopping_list(REFERENCE.plan, REFERENCE.catalog)


def test_stages_compose_identically_in_another_locale() -> None:
    # Names come from the catalog at the rounding stage, and the sort that
    # follows is by name — so a locale change is the case where a split
    # pipeline could reorder without changing any number.
    assert _by_hand("en") == shopping_list(REFERENCE.plan, REFERENCE.catalog, locale="en")


def test_every_value_stays_decimal() -> None:
    for line in _by_hand():
        assert isinstance(line.needed_raw_g, Decimal)
        assert isinstance(line.purchase_amount, Decimal)
        assert isinstance(line.overage_g, Decimal)


def test_expand_does_not_multiply_by_batch_portions() -> None:
    """PRD §6.4 — the one mistake this engine exists to not make."""
    entries = len(REFERENCE.plan.all_entries)
    lines_per_entry = sum(
        len(REFERENCE.catalog.module(entry.module_id).lines) for entry in REFERENCE.plan.all_entries
    )
    expanded = expand_entries(REFERENCE.plan, REFERENCE.catalog)
    assert entries > 0
    assert len(expanded) == lines_per_entry


def test_merge_keeps_first_appearance_order() -> None:
    raw = convert_to_raw(expand_entries(REFERENCE.plan, REFERENCE.catalog))
    merged = merge_by_ingredient(raw)
    first_seen: list[str] = []
    for demand in raw:
        if demand.ingredient_id not in first_seen:
            first_seen.append(demand.ingredient_id)
    assert [d.ingredient_id for d in merged] == first_seen


def test_empty_plan_runs_every_stage_without_dividing_by_zero() -> None:
    from dataclasses import replace

    empty = replace(
        REFERENCE.plan,
        days=tuple(replace(day, entries=()) for day in REFERENCE.plan.days),
    )
    cooked = expand_entries(empty, REFERENCE.catalog)
    assert cooked == ()
    assert (
        group_by_shop_section(
            round_to_packages(merge_by_ingredient(convert_to_raw(cooked)), REFERENCE.catalog)
        )
        == ()
    )
