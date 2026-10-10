"""Exclusions and caution thresholds, both configured on the profile."""

from decimal import Decimal

from ration.domain.types import IngredientRule
from ration.domain.validation import validate
from tests.unit.conftest import (
    make_catalog,
    make_entry,
    make_module,
    make_plan,
    make_profile,
)

EXCLUDED = (IngredientRule("chicken_breast", "excluded"),)
CAUTION_60 = (IngredientRule("hummus", "caution", threshold_g=Decimal(60)),)


class TestExclusions:
    def test_an_excluded_ingredient_is_an_error(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="chicken_breast")
        plan = make_plan({0: (make_entry("m"),)})
        findings = validate(plan, make_profile(ingredient_rules=EXCLUDED), make_catalog(module))
        assert "EXCLUDED_INGREDIENT" in codes(findings)
        assert findings[0].level == "error"

    def test_the_finding_locates_the_entry_and_names_the_ingredient(self) -> None:
        module = make_module("m", ingredient="chicken_breast")
        entry = make_entry("m")
        plan = make_plan({0: (entry,)})
        finding = next(
            f
            for f in validate(plan, make_profile(ingredient_rules=EXCLUDED), make_catalog(module))
            if f.code == "EXCLUDED_INGREDIENT"
        )
        assert finding.entry_id == entry.id
        assert finding.slot == "dinner"
        assert finding.day_index == 0
        assert finding.params["ingredient"] == "chicken_breast"

    def test_an_ingredient_with_no_rule_is_never_flagged(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="plain")
        plan = make_plan({0: (make_entry("m"),)})
        findings = validate(plan, make_profile(ingredient_rules=EXCLUDED), make_catalog(module))
        assert "EXCLUDED_INGREDIENT" not in codes(findings)

    def test_a_caution_rule_does_not_exclude(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="hummus", grams="10")
        plan = make_plan({0: (make_entry("m"),)})
        findings = validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(module))
        assert "EXCLUDED_INGREDIENT" not in codes(findings)


class TestCautionThresholds:
    def test_under_the_threshold_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="hummus", grams="50")
        plan = make_plan({0: (make_entry("m"),)})
        findings = validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(module))
        assert "CAUTION_THRESHOLD_EXCEEDED" not in codes(findings)

    def test_exactly_on_the_threshold_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="hummus", grams="60")
        plan = make_plan({0: (make_entry("m"),)})
        findings = validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(module))
        assert "CAUTION_THRESHOLD_EXCEEDED" not in codes(findings)

    def test_over_the_threshold_is_a_warning(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="hummus", grams="61")
        plan = make_plan({0: (make_entry("m"),)})
        findings = [
            f
            for f in validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(module))
            if f.code == "CAUTION_THRESHOLD_EXCEEDED"
        ]
        assert findings[0].level == "warning"
        assert findings[0].params == {
            "ingredient": "hummus",
            "actual": "61.0",
            "threshold": "60.0",
        }

    def test_two_modules_each_under_can_breach_together(self, codes) -> None:  # type: ignore[no-untyped-def]
        """The reason cautions sum per day rather than per module."""
        lunch = make_module("lunch_m", slot="lunch", ingredient="hummus", grams="40")
        dinner = make_module("dinner_m", ingredient="hummus", grams="40")
        plan = make_plan({0: (make_entry("lunch_m", "lunch"), make_entry("dinner_m"))})
        findings = validate(
            plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(lunch, dinner)
        )
        assert "CAUTION_THRESHOLD_EXCEEDED" in codes(findings)

    def test_the_same_amount_on_two_days_does_not_accumulate(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="hummus", grams="50")
        plan = make_plan({0: (make_entry("m"),), 1: (make_entry("m"),)})
        findings = validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(module))
        assert "CAUTION_THRESHOLD_EXCEEDED" not in codes(findings)

    def test_portion_factor_scales_the_amount_counted(self, codes) -> None:  # type: ignore[no-untyped-def]
        module = make_module("m", ingredient="hummus", grams="100")
        plan = make_plan({0: (make_entry("m", portion="0.5"),)})
        findings = validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(module))
        assert "CAUTION_THRESHOLD_EXCEEDED" not in codes(findings)

    def test_one_finding_per_ingredient_not_per_module(self) -> None:
        a = make_module("a", slot="lunch", ingredient="hummus", grams="40")
        b = make_module("b", ingredient="hummus", grams="40")
        plan = make_plan({0: (make_entry("a", "lunch"), make_entry("b"))})
        findings = [
            f
            for f in validate(plan, make_profile(ingredient_rules=CAUTION_60), make_catalog(a, b))
            if f.code == "CAUTION_THRESHOLD_EXCEEDED"
        ]
        assert len(findings) == 1
        assert findings[0].params["actual"] == "80.0"
