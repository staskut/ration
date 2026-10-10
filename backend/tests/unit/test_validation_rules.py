"""Weekly tag limits and day-template gates, both driven by profile data."""

from ration.domain.types import FrequencyRule
from ration.domain.validation import validate
from tests.unit.conftest import (
    make_catalog,
    make_entry,
    make_module,
    make_plan,
    make_profile,
)

LIVER_ONCE = (FrequencyRule(tag="liver", max_per_week=1),)
TREAT_THREE = (FrequencyRule(tag="treat", max_per_week=3),)
NO_WINE_ON_TRAINING = (
    FrequencyRule(
        tag="alcohol",
        max_per_week=1,
        blocked_on_templates=frozenset({"training", "duty_24h"}),
    ),
)

LIVER = make_module("liver", tags=frozenset({"liver"}))
TREAT = make_module("treat", slot="treat", tags=frozenset({"treat"}))
WINE = make_module("wine", slot="treat", tags=frozenset({"treat", "alcohol"}))
PLAIN = make_module("plain")


class TestFrequencyLimits:
    def test_a_tag_at_its_limit_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("liver"),)})
        findings = validate(plan, make_profile(frequency_rules=LIVER_ONCE), make_catalog(LIVER))
        assert "FREQUENCY_EXCEEDED" not in codes(findings)

    def test_one_over_the_limit_is_an_error(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("liver"),), 1: (make_entry("liver"),)})
        findings = validate(plan, make_profile(frequency_rules=LIVER_ONCE), make_catalog(LIVER))
        assert "FREQUENCY_EXCEEDED" in codes(findings)

    def test_the_finding_reports_the_count_and_the_limit(self) -> None:
        plan = make_plan({i: (make_entry("treat", "treat"),) for i in range(5)})
        finding = next(
            f
            for f in validate(plan, make_profile(frequency_rules=TREAT_THREE), make_catalog(TREAT))
            if f.code == "FREQUENCY_EXCEEDED"
        )
        assert finding.params == {"tag": "treat", "actual": "5", "max": "3"}
        assert finding.level == "error"

    def test_a_rule_without_a_maximum_imposes_no_count_limit(self, codes) -> None:  # type: ignore[no-untyped-def]
        rules = (FrequencyRule(tag="liver", max_per_week=None),)
        plan = make_plan({i: (make_entry("liver"),) for i in range(5)})
        findings = validate(plan, make_profile(frequency_rules=rules), make_catalog(LIVER))
        assert "FREQUENCY_EXCEEDED" not in codes(findings)

    def test_an_untagged_module_is_unaffected(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({i: (make_entry("plain"),) for i in range(5)})
        findings = validate(plan, make_profile(frequency_rules=LIVER_ONCE), make_catalog(PLAIN))
        assert "FREQUENCY_EXCEEDED" not in codes(findings)

    def test_a_module_with_two_tags_counts_under_both_rules(self) -> None:
        rules = (
            FrequencyRule(tag="treat", max_per_week=1),
            FrequencyRule(tag="alcohol", max_per_week=1),
        )
        plan = make_plan({0: (make_entry("wine", "treat"),), 1: (make_entry("wine", "treat"),)})
        tags = {
            f.params["tag"]
            for f in validate(plan, make_profile(frequency_rules=rules), make_catalog(WINE))
            if f.code == "FREQUENCY_EXCEEDED"
        }
        assert tags == {"treat", "alcohol"}

    def test_counting_is_per_entry_not_per_day(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan(
            {0: (make_entry("liver"), make_entry("liver", "lunch", position=1))},
        )
        findings = validate(plan, make_profile(frequency_rules=LIVER_ONCE), make_catalog(LIVER))
        assert "FREQUENCY_EXCEEDED" in codes(findings)


class TestTemplateGates:
    def test_wine_on_a_training_day_is_blocked(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("wine", "treat"),)}, templates={0: "training"})
        findings = validate(
            plan, make_profile(frequency_rules=NO_WINE_ON_TRAINING), make_catalog(WINE)
        )
        assert "TEMPLATE_GATE_VIOLATED" in codes(findings)

    def test_the_same_wine_on_a_normal_day_is_allowed(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("wine", "treat"),)}, templates={0: "normal"})
        findings = validate(
            plan, make_profile(frequency_rules=NO_WINE_ON_TRAINING), make_catalog(WINE)
        )
        assert "TEMPLATE_GATE_VIOLATED" not in codes(findings)

    def test_duty_days_block_it_too(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("wine", "treat"),)}, templates={0: "duty_24h"})
        findings = validate(
            plan, make_profile(frequency_rules=NO_WINE_ON_TRAINING), make_catalog(WINE)
        )
        assert "TEMPLATE_GATE_VIOLATED" in codes(findings)

    def test_the_finding_names_the_tag_and_the_template(self) -> None:
        plan = make_plan({0: (make_entry("wine", "treat"),)}, templates={0: "training"})
        finding = next(
            f
            for f in validate(
                plan, make_profile(frequency_rules=NO_WINE_ON_TRAINING), make_catalog(WINE)
            )
            if f.code == "TEMPLATE_GATE_VIOLATED"
        )
        assert finding.params["tag"] == "alcohol"
        assert finding.params["template"] == "training"
        assert finding.level == "error"

    def test_a_module_without_the_blocked_tag_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("treat", "treat"),)}, templates={0: "training"})
        findings = validate(
            plan, make_profile(frequency_rules=NO_WINE_ON_TRAINING), make_catalog(TREAT)
        )
        assert "TEMPLATE_GATE_VIOLATED" not in codes(findings)
