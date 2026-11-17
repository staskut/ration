"""The contract is valid, and keeps the promises the design documents make.

These guard properties that are easy to break by hand-editing a large YAML file
and that would not show up until the generated client misbehaved.
"""

from pathlib import Path

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

SPEC_PATH = Path(__file__).parents[3] / "openapi.yaml"
SPEC, _ = read_from_filename(str(SPEC_PATH))


def operations():  # type: ignore[no-untyped-def]
    for path, item in SPEC["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                yield path, method, operation


def test_the_spec_is_valid_openapi() -> None:
    validate(SPEC)


def test_every_operation_has_an_operation_id() -> None:
    """The generated client's method names come from these."""
    missing = [f"{m.upper()} {p}" for p, m, op in operations() if "operationId" not in op]
    assert missing == []


def test_operation_ids_are_unique() -> None:
    ids = [op["operationId"] for _, _, op in operations()]
    assert len(ids) == len(set(ids))


def test_no_nutrition_field_is_a_json_number() -> None:
    """Decimals travel as strings.

    A JSON number is an IEEE-754 double, and round-tripping one would
    reintroduce exactly the drift the domain layer uses Decimal to avoid.
    """
    numeric_names = {
        "kcal",
        "protein_g",
        "kcal_per_100g",
        "protein_per_100g",
        "yield_factor",
        "grams_cooked",
        "package_size",
        "portion_factor",
        "kcal_min",
        "kcal_max",
        "protein_min",
        "protein_max",
        "threshold_g",
        "daily_kcal_target",
        "daily_kcal_tolerance",
        "daily_protein_min",
        "daily_protein_target",
        "needed_raw_g",
        "purchase_amount",
        "overage_g",
    }
    offenders = []
    for schema_name, schema in SPEC["components"]["schemas"].items():
        for field, definition in (schema.get("properties") or {}).items():
            if field in numeric_names and definition.get("type") == "number":
                offenders.append(f"{schema_name}.{field}")
    assert offenders == []


def test_computed_module_totals_are_read_only() -> None:
    """Calories are derived from the lines; accepting them would let a client
    submit a module whose stated totals disagree with its ingredients."""
    module = SPEC["components"]["schemas"]["Module"]["properties"]
    assert module["kcal"]["readOnly"] is True
    assert module["protein_g"]["readOnly"] is True


def test_module_input_does_not_accept_totals() -> None:
    module_input = SPEC["components"]["schemas"]["ModuleInput"]["properties"]
    assert "kcal" not in module_input
    assert "protein_g" not in module_input


@pytest.mark.parametrize("schema_name", ["Ingredient", "Module", "Profile", "SlotBudget", "Error"])
def test_core_schemas_are_present(schema_name: str) -> None:
    assert schema_name in SPEC["components"]["schemas"]


def test_every_authenticated_operation_declares_401() -> None:
    missing = [
        f"{m.upper()} {p}"
        for p, m, op in operations()
        if op.get("security") != [] and "401" not in op["responses"]
    ]
    assert missing == []


# Reaching the API without a session. Kept as an explicit list, so widening it
# is a deliberate edit here rather than a `security: []` nobody reviewed.
#
# `getDemoAccess` and `signInAsDemo` are public because the sign-in page has to
# ask before anyone has signed in. `signInAsDemo` issues a session for the
# asking, which is only acceptable because it refuses outside a non-production
# deployment that the seed has actually run in — see the handler.
PUBLIC_OPERATIONS = ["getDemoAccess", "login", "signInAsDemo"]


def test_only_sign_in_is_unauthenticated() -> None:
    public = [op["operationId"] for _, _, op in operations() if op.get("security") == []]
    assert sorted(public) == PUBLIC_OPERATIONS


# Mutations both roles may perform. Everything else must be able to answer 403.
# Kept as an explicit list rather than inferred, so adding a both-roles mutation
# is a deliberate edit here instead of a silently widened permission.
MUTATIONS_OPEN_TO_BOTH_ROLES = {
    "logout",
    "setShoppingItemChecked",  # the follower ticks items off in a shop
}


def test_role_restricted_mutations_declare_a_forbidden_response() -> None:
    """Planner-only routes must be able to say 403 to a follower."""
    missing = [
        op["operationId"]
        for _, method, op in operations()
        if method in {"post", "put", "patch", "delete"}
        and op.get("security") != []
        and op["operationId"] not in MUTATIONS_OPEN_TO_BOTH_ROLES
        and "403" not in op["responses"]
    ]
    assert missing == []


def test_the_both_roles_list_names_only_real_operations() -> None:
    """Stops the allowlist outliving the operations it excuses."""
    all_ids = {op["operationId"] for _, _, op in operations()}
    assert all_ids >= MUTATIONS_OPEN_TO_BOTH_ROLES


def test_the_not_found_response_explains_that_it_hides_existence() -> None:
    description = SPEC["components"]["responses"]["NotFound"]["description"]
    assert "another profile" in description


def test_session_cookie_is_the_security_scheme() -> None:
    schemes = SPEC["components"]["securitySchemes"]
    assert schemes["sessionCookie"]["in"] == "cookie"
    assert SPEC["security"] == [{"sessionCookie": []}]


class TestPlansAndDerived:
    def test_a_plan_is_always_exactly_seven_days(self) -> None:
        days = SPEC["components"]["schemas"]["Plan"]["properties"]["days"]
        assert days["minItems"] == 7
        assert days["maxItems"] == 7

    def test_day_index_is_bounded_to_the_week(self) -> None:
        bounded = [
            parameter
            for path_item in SPEC["paths"].values()
            for parameter in path_item.get("parameters", [])
            if parameter["name"] == "dayIndex"
        ]
        assert bounded, "no dayIndex parameters found"
        for parameter in bounded:
            assert parameter["schema"]["minimum"] == 0
            assert parameter["schema"]["maximum"] == 6

    def test_a_finding_carries_a_key_and_params_not_a_sentence(self) -> None:
        finding = SPEC["components"]["schemas"]["Finding"]["properties"]
        assert "message_key" in finding
        assert "message" not in finding
        assert finding["params"]["additionalProperties"] == {"type": "string"}

    def test_entry_mutations_return_fresh_validation(self) -> None:
        """A planner must never see a changed plan beside a stale report."""
        for operation_id in ("createPlanEntry", "updatePlanEntry"):
            operation = next(op for _, _, op in operations() if op["operationId"] == operation_id)
            response = next(iter(operation["responses"].values()))
            ref = response["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("PlanEntryWithValidation")

    def test_entry_creation_can_report_a_conflict(self) -> None:
        """A second `main` in one slot is a 409, not a silent accept."""
        operation = next(op for _, _, op in operations() if op["operationId"] == "createPlanEntry")
        assert "409" in operation["responses"]

    def test_feedback_status_is_inferred_rather_than_submitted(self) -> None:
        assert SPEC["components"]["schemas"]["Feedback"]["properties"]["status"]["readOnly"]
        assert "status" not in SPEC["components"]["schemas"]["FeedbackInput"]["properties"]

    def test_feedback_requires_only_a_rating(self) -> None:
        """One tap. Bloating and satiety went unreported for a whole pilot."""
        assert SPEC["components"]["schemas"]["FeedbackInput"]["required"] == ["rating"]

    def test_the_shopping_line_surfaces_a_critical_size(self) -> None:
        line = SPEC["components"]["schemas"]["ShoppingLine"]["properties"]
        assert "size_is_critical" in line
        assert "overage_g" in line

    def test_the_websocket_message_carries_no_payload(self) -> None:
        message = SPEC["components"]["schemas"]["WebSocketMessage"]["properties"]
        assert set(message) == {"type", "plan_id", "changed"}
