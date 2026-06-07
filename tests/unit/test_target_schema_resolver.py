"""Unit tests for resolve_target_schema."""

from domains.migration.target_schema_resolver import resolve_target_schema


def test_dbo_maps_to_public_when_target_omitted():
    assert resolve_target_schema("dbo") == "public"
    assert resolve_target_schema("dbo", None) == "public"
    assert resolve_target_schema("dbo", "") == "public"


def test_non_dbo_schemas_preserve_name_when_target_omitted():
    assert resolve_target_schema("Sales") == "Sales"
    assert resolve_target_schema("Person") == "Person"
    assert resolve_target_schema("HumanResources") == "HumanResources"


def test_explicit_target_schema_is_honoured():
    assert resolve_target_schema("Sales", "sales_staging") == "sales_staging"
    assert resolve_target_schema("dbo", "app") == "app"


def test_dbo_explicit_public():
    assert resolve_target_schema("dbo", "public") == "public"


def test_legacy_public_default_remapped_for_non_dbo():
    """Old API default target_schema=public must not flatten Sales/Person into public."""
    assert resolve_target_schema("Sales", "public") == "Sales"
    assert resolve_target_schema("Person", "public") == "Person"

