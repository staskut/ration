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


def test_login_is_the_only_unauthenticated_operation() -> None:
    public = [op["operationId"] for _, _, op in operations() if op.get("security") == []]
    assert public == ["login"]


def test_role_restricted_mutations_declare_a_forbidden_response() -> None:
    """Planner-only routes must be able to say 403 to a follower.

    Auth operations are excluded: signing out is something both roles do, so a
    403 there would be describing a rule that does not exist.
    """
    missing = [
        op["operationId"]
        for _, method, op in operations()
        if method in {"post", "put", "patch", "delete"}
        and op.get("security") != []
        and "auth" not in op.get("tags", [])
        and "403" not in op["responses"]
    ]
    assert missing == []


def test_the_not_found_response_explains_that_it_hides_existence() -> None:
    description = SPEC["components"]["responses"]["NotFound"]["description"]
    assert "another profile" in description


def test_session_cookie_is_the_security_scheme() -> None:
    schemes = SPEC["components"]["securitySchemes"]
    assert schemes["sessionCookie"]["in"] == "cookie"
    assert SPEC["security"] == [{"sessionCookie": []}]
