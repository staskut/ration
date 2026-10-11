"""A worksheet for reviewing and changing yield factors.

Yield factors are parameters, not constants. They bundle trim loss, water
exchange during cooking, and the ice glaze on frozen seafood, so they vary with
method, equipment and supplier and can only really be established by weighing.

This prints what each factor currently implies for the reference plan, so a
measurement can be compared against it without reading any code:

    uv run ration-yields                    the worksheet
    uv run ration-yields --what-if turkey_thigh=0.72
                                            what one change moves
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from ration.domain.shopping import shopping_list
from ration.domain.types import Catalog
from ration.seed.loader import ReferenceData, load_reference

# What section 12 of docs/sample-plan-6-days.md asks for, where it gives a number
# that can be compared. Midpoint where it gives a range.
SECTION_12_RAW = {
    "turkey_thigh": Decimal(550),
    "chicken_thigh": Decimal(550),
    "white_fish": Decimal(475),
    "shrimp": Decimal(300),
    "squid": Decimal(325),
    "salted_salmon": Decimal(100),
    "herring_fillet": Decimal(120),
    "carrot": Decimal(600),
    "pumpkin": Decimal(325),
    "rice_noodles": Decimal(180),
}


def cooked_requirements(reference: ReferenceData) -> dict[str, Decimal]:
    """Total cooked grams the plan needs, per ingredient. Independent of yield."""
    needed: dict[str, Decimal] = {}
    for entry in reference.plan.all_entries:
        for line in reference.catalog.module(entry.module_id).lines:
            cooked = line.grams_cooked * entry.portion_factor
            needed[line.ingredient_id] = needed.get(line.ingredient_id, Decimal(0)) + cooked
    return needed


def raw_for(reference: ReferenceData, catalog: Catalog) -> dict[str, Decimal]:
    return {
        line.ingredient_id: line.needed_raw_g for line in shopping_list(reference.plan, catalog)
    }


def worksheet(reference: ReferenceData) -> str:
    cooked = cooked_requirements(reference)
    raw = raw_for(reference, reference.catalog)

    rows = [
        ingredient
        for ingredient in reference.catalog.ingredients.values()
        if ingredient.yield_source != "as_purchased"
    ]
    rows.sort(key=lambda i: (i.yield_source != "estimated", i.id))

    lines = [
        "Yield factors needing review",
        "",
        "Weigh raw going in and cooked coming out during a cook that is happening",
        "anyway, then divide cooked by raw. Edit yield_factor in",
        "src/ration/seed/ingredients.yaml and set yield_source: measured.",
        "",
        f"{'ingredient':22}{'factor':>8}{'source':>12}{'cooked':>10}{'raw now':>10}"
        f"{'doc §12':>10}{'gap':>8}",
        "-" * 80,
    ]
    for ingredient in rows:
        need_cooked = cooked.get(ingredient.id, Decimal(0))
        need_raw = raw.get(ingredient.id, Decimal(0))
        stated = SECTION_12_RAW.get(ingredient.id)
        if stated and need_raw:
            gap = f"{(need_raw - stated) / stated * 100:+.0f}%"
            stated_text = f"{stated:.0f}"
        else:
            gap, stated_text = "-", "-"
        lines.append(
            f"{ingredient.id:22}{ingredient.yield_factor:>8}{ingredient.yield_source:>12}"
            f"{need_cooked:>10.0f}{need_raw:>10.0f}{stated_text:>10}{gap:>8}"
        )

    estimated = sum(1 for i in rows if i.yield_source == "estimated")
    lines += [
        "-" * 80,
        f"{estimated} still estimated, {len(rows) - estimated} measured.",
        "",
        "'cooked' is what the plan needs and does not depend on the factor.",
        "'raw now' is what the current factor says to buy.",
        "A large gap against the document is worth investigating rather than",
        "averaging away: on frozen seafood it usually means ice glaze, which is a",
        "purchasing problem rather than a cooking one.",
    ]
    return "\n".join(lines)


def what_if(reference: ReferenceData, changes: dict[str, Decimal]) -> str:
    """Show what changing one or more factors does to the shopping list."""
    before = raw_for(reference, reference.catalog)

    swapped = dict(reference.catalog.ingredients)
    for slug, factor in changes.items():
        if slug not in swapped:
            raise KeyError(f"Unknown ingredient: {slug}")
        swapped[slug] = replace(swapped[slug], yield_factor=factor, yield_source="measured")
    after = raw_for(reference, Catalog(ingredients=swapped, modules=reference.catalog.modules))

    lines = [
        "Effect on the shopping list",
        "",
        f"{'ingredient':22}{'was':>10}{'now':>10}{'change':>10}",
        "-" * 52,
    ]
    for slug in sorted(changes):
        old, new = before.get(slug, Decimal(0)), after.get(slug, Decimal(0))
        factor = reference.catalog.ingredient(slug).yield_factor
        lines.append(f"{slug:22}{old:>10.0f}{new:>10.0f}{new - old:>+10.0f}")
        lines.append(f"{'  ' + str(factor) + ' -> ' + str(changes[slug]):22}")
    lines += [
        "-" * 52,
        "Nothing else moves: a yield factor only affects its own ingredient.",
    ]
    return "\n".join(lines)


def _parse_change(text: str) -> tuple[str, Decimal]:
    slug, _, value = text.partition("=")
    if not slug or not value:
        raise argparse.ArgumentTypeError(f"expected slug=factor, got {text!r}")
    try:
        factor = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if not Decimal(0) < factor <= Decimal(5):
        raise argparse.ArgumentTypeError(f"yield factor must be in (0, 5], got {factor}")
    return slug, factor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--what-if",
        type=_parse_change,
        action="append",
        metavar="SLUG=FACTOR",
        help="Show what changing a factor does. Repeatable.",
    )
    args = parser.parse_args(argv)

    reference = load_reference()
    if args.what_if:
        print(what_if(reference, dict(args.what_if)))
    else:
        print(worksheet(reference))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
