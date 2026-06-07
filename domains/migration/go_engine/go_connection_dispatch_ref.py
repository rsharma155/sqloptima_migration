"""
Module: go_connection_dispatch_ref.py
Purpose: Reference to a stored project connection for Go job dispatch.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GoConnectionDispatchRef:
    """Pointer to a connection row in project_connections (credentials resolved by Go worker)."""

    connection_id: UUID
    schema: str

    def to_dict(self) -> dict[str, str]:
        return {
            "connection_id": str(self.connection_id),
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GoConnectionDispatchRef:
        return cls(
            connection_id=UUID(str(data["connection_id"])),
            schema=str(data["schema"]),
        )
