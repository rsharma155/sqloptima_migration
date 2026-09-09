"""TDD: destination constraint review must be explicit; disable is never implied."""

from __future__ import annotations

import pytest

from domains.transfer.preflight import (
    ColumnInventory,
    ObjectInventory,
    TableInventory,
    compare_table,
)
from domains.transfer.transfer_constraint_plan import (
    REVIEW_REQUIRED_MESSAGE,
    accept_constraint_plan,
    build_target_constraint_catalog,
    disable_items,
)
from domains.transfer.transfer_path import TransferPath


def _table_report() -> dict:
    source = TableInventory(
        schema="public",
        table="orders",
        exists=True,
        columns=[ColumnInventory(name="id", type_name="bigint", nullable=False)],
    )
    target = TableInventory(
        schema="public",
        table="orders",
        exists=True,
        columns=[ColumnInventory(name="id", type_name="bigint", nullable=False)],
        constraints=[
            ObjectInventory(object_id="orders_pkey", kind="primary_key", extra={"is_primary_key": True}),
            ObjectInventory(
                object_id="orders_amount_check",
                kind="check",
                extra={"definition": "CHECK ((amount > 0))"},
            ),
        ],
        indexes=[
            ObjectInventory(
                object_id="ix_orders_customer",
                kind="index",
                extra={"is_primary_key": False, "definition": 'CREATE INDEX ix_orders_customer ON public.orders USING btree (customer_id)'},
            ),
        ],
        foreign_keys=[
            ObjectInventory(
                object_id="orders_customer_fk",
                kind="foreign_key",
                extra={
                    "referenced": "public.customers",
                    "definition": "FOREIGN KEY (customer_id) REFERENCES public.customers(id)",
                },
            ),
        ],
        triggers=[
            ObjectInventory(object_id="trg_orders_ai", kind="trigger", extra={"timing": "insert"}),
        ],
    )
    return compare_table(
        path=TransferPath.PG_TO_PG,
        source=source,
        target=target,
        create_if_missing=False,
        tables_in_job={"public.customers"},
    )


def test_catalog_lists_only_destination_objects():
    catalog = build_target_constraint_catalog([_table_report()])
    kinds = {item["kind"] for item in catalog}
    ids = {item["object_id"] for item in catalog}
    assert "primary_key" in kinds
    assert ids == {"orders_pkey", "orders_amount_check", "ix_orders_customer", "orders_customer_fk", "trg_orders_ai"}
    pk = next(i for i in catalog if i["kind"] == "primary_key")
    assert pk["allowed_actions"] == ("keep",)
    assert pk["recommended_action"] == "keep"
    fk = next(i for i in catalog if i["object_id"] == "orders_customer_fk")
    assert fk["recommended_action"] == "disable"
    assert fk["definition"].startswith("FOREIGN KEY")


def test_accept_requires_operator_review():
    catalog = build_target_constraint_catalog([_table_report()])
    with pytest.raises(ValueError, match="Review the destination"):
        accept_constraint_plan(None, catalog, on_stop="restore_now", create_if_missing=False)
    with pytest.raises(ValueError, match="Review the destination"):
        accept_constraint_plan(
            {"operator_reviewed": False, "items": []},
            catalog,
            on_stop="restore_now",
            create_if_missing=False,
        )


def test_unreviewed_disable_is_rejected_even_if_items_present():
    catalog = build_target_constraint_catalog([_table_report()])
    fk_key = next(i["key"] for i in catalog if i["object_id"] == "orders_customer_fk")
    with pytest.raises(ValueError, match=REVIEW_REQUIRED_MESSAGE.split(".")[0]):
        accept_constraint_plan(
            {
                "operator_reviewed": False,
                "items": [{"key": fk_key, "action": "disable"}],
            },
            catalog,
            on_stop="restore_now",
            create_if_missing=False,
        )


def test_default_action_is_keep_until_operator_opts_in():
    catalog = build_target_constraint_catalog([_table_report()])
    plan = accept_constraint_plan(
        {"operator_reviewed": True, "items": []},
        catalog,
        on_stop="restore_now",
        create_if_missing=False,
    )
    assert plan["operator_reviewed"] is True
    assert disable_items(plan) == []
    assert all(item["action"] == "keep" for item in plan["items"])


def test_operator_can_disable_recommended_destination_objects():
    catalog = build_target_constraint_catalog([_table_report()])
    fk_key = next(i["key"] for i in catalog if i["object_id"] == "orders_customer_fk")
    plan = accept_constraint_plan(
        {
            "operator_reviewed": True,
            "on_stop": "restore_now",
            "items": [{"key": fk_key, "action": "disable"}],
        },
        catalog,
        on_stop="restore_now",
        create_if_missing=False,
    )
    disabled = disable_items(plan)
    assert [i["object_id"] for i in disabled] == ["orders_customer_fk"]
    assert disabled[0]["definition"].startswith("FOREIGN KEY")


def test_primary_key_cannot_be_disabled():
    catalog = build_target_constraint_catalog([_table_report()])
    pk_key = next(i["key"] for i in catalog if i["kind"] == "primary_key")
    with pytest.raises(ValueError, match="primary"):
        accept_constraint_plan(
            {
                "operator_reviewed": True,
                "items": [{"key": pk_key, "action": "disable"}],
            },
            catalog,
            on_stop="restore_now",
            create_if_missing=False,
        )


def test_unknown_destination_object_cannot_be_disabled():
    catalog = build_target_constraint_catalog([_table_report()])
    with pytest.raises(ValueError, match="Unknown destination object"):
        accept_constraint_plan(
            {
                "operator_reviewed": True,
                "items": [{"key": "public.orders:foreign_key:not_real", "action": "disable"}],
            },
            catalog,
            on_stop="restore_now",
            create_if_missing=False,
        )
