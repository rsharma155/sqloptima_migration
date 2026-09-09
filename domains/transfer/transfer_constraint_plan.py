"""
Module: transfer_constraint_plan.py
Purpose: Operator-reviewed destination constraint plan for Transfer (never auto-disable).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

REVIEW_REQUIRED_MESSAGE = (
    "Review the destination constraints before starting. "
    "Nothing is disabled until you confirm."
)

_DISABLEABLE = frozenset({"check", "unique", "foreign_key", "index", "secondary", "trigger"})
_KEEP_ONLY = frozenset({"primary_key", "primary"})


def constraint_item_key(schema: str, table: str, kind: str, object_id: str) -> str:
    return f"{schema}.{table}:{kind}:{object_id}".lower()


def build_target_constraint_catalog(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten destination-only objects the operator must review."""
    items: list[dict[str, Any]] = []
    for table in tables:
        target = table.get("target") or {}
        schema = str(target.get("schema") or "")
        name = str(target.get("table") or "")
        groups = (
            table.get("constraints") or [],
            table.get("indexes") or [],
            table.get("foreign_keys") or [],
            table.get("triggers") or [],
        )
        for group in groups:
            for raw in group:
                item = _catalog_item(schema, name, raw)
                if item is not None:
                    items.append(item)
    return items


def accept_constraint_plan(
    submitted: dict[str, Any] | None,
    catalog: list[dict[str, Any]],
    *,
    on_stop: str,
    create_if_missing: bool,
) -> dict[str, Any]:
    if not submitted or not submitted.get("operator_reviewed"):
        raise ValueError(REVIEW_REQUIRED_MESSAGE)
    chosen: dict[str, str] = {}
    for raw in submitted.get("items") or []:
        key = str(raw.get("key") or _key_from_raw(raw))
        action = str(raw.get("action") or "keep")
        match = next((item for item in catalog if item["key"] == key), None)
        if match is None:
            if action == "disable":
                raise ValueError(f"Unknown destination object {key}")
            continue
        if action not in match["allowed_actions"]:
            raise ValueError(f"Cannot {action} {match['kind']} {match['object_id']} on the destination")
        chosen[key] = action
    items = []
    for cat in catalog:
        items.append({**cat, "action": chosen.get(cat["key"], "keep")})
    return {
        "on_stop": str(submitted.get("on_stop") or on_stop or "restore_now"),
        "create_if_missing": bool(create_if_missing),
        "operator_reviewed": True,
        "items": items,
    }


def disable_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (plan.get("items") or []) if item.get("action") == "disable"]


def _key_from_raw(raw: dict[str, Any]) -> str:
    return constraint_item_key(
        str(raw.get("schema") or ""),
        str(raw.get("table") or ""),
        str(raw.get("kind") or ""),
        str(raw.get("object_id") or raw.get("id") or ""),
    )


def _catalog_item(schema: str, table: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    object_id = str(raw.get("id") or raw.get("object_id") or "")
    kind = str(raw.get("kind") or "")
    if not object_id or not kind:
        return None
    keep_only = kind in _KEEP_ONLY
    allowed: tuple[str, ...] = ("keep",) if keep_only else ("keep", "disable")
    recommended = "keep" if keep_only else str(raw.get("recommended_action") or "keep")
    if recommended not in allowed:
        recommended = "keep"
    if kind not in _DISABLEABLE and kind not in _KEEP_ONLY:
        return None
    return {
        "key": constraint_item_key(schema, table, kind, object_id),
        "object_id": object_id,
        "kind": kind,
        "schema": schema,
        "table": table,
        "recommended_action": recommended,
        "allowed_actions": allowed,
        "definition": str(raw.get("definition") or ""),
        "reason": raw.get("reason"),
        "referenced": raw.get("referenced"),
    }
