"""TDD: create_job persists TransferDispatchConfig (kind=transfer) into transfer_jobs.config."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from application.transfer_service import TransferError, create_job
from domains.transfer.transfer_models import TransferTableMapping, TransferThreshold
from domains.transfer.transfer_path import TransferPath

SRC = UUID("550e8400-e29b-41d4-a716-446655440001")
TGT = UUID("550e8400-e29b-41d4-a716-446655440002")


class _FakeSessionCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


class _FakeRepo:
    captured: dict | None = None
    job = None

    def __init__(self, session) -> None:
        pass

    async def create(self, **kwargs):
        _FakeRepo.captured = kwargs
        _FakeRepo.job = SimpleNamespace(
            transfer_job_id=kwargs.get("job_id") or "job",
            path=kwargs["path"],
            status="queued",
            phase="idle",
            source_project_connection_id=kwargs["source_connection_id"],
            target_project_connection_id=kwargs["target_connection_id"],
            project_id=kwargs.get("project_id"),
            tables_total=len(kwargs["tables"]),
            tables_done=0,
            rows_copied=0,
            rows_total=kwargs.get("rows_total") or 0,
            error=None,
            preflight_json=kwargs.get("preflight_json"),
            constraint_plan=kwargs.get("constraint_plan"),
            config=kwargs.get("config"),
            table_plans=[],
            runtime_settings=None,
            created_at=None,
            started_at=None,
            completed_at=None,
            updated_at=None,
        )
        return _FakeRepo.job

    async def append_log(self, *args, **kwargs):
        return None

    async def add_constraint_actions(self, *args, **kwargs):
        return None

    async def issue_command(self, *args, **kwargs):
        return None

    async def get(self, job_id):
        return _FakeRepo.job


def _entry(database: str) -> dict:
    return {
        "engine": "postgres",
        "type": "target",
        "host": "localhost",
        "port": 5432,
        "database": database,
        "project_id": "proj-1",
    }


@pytest.mark.asyncio
async def test_create_job_persists_transfer_kind_dispatch_config():
    _FakeRepo.captured = None
    preflight = {
        "can_start": True,
        "tables": [
            {
                "source": {"schema": "public", "table": "orders"},
                "row_count_source": 50,
                "columns": {
                    "matched": [
                        {"name": "id"},
                        {"name": "amount"},
                    ]
                },
            }
        ],
        "summary": {"can_start": True},
    }

    with (
        patch("application.transfer_service.run_preflight", new=AsyncMock(return_value=preflight)),
        patch(
            "application.transfer_service.get_entry",
            side_effect=lambda cid: _entry("srcdb") if cid == str(SRC) else _entry("tgtdb"),
        ),
        patch("application.transfer_service.AsyncSessionFactory", lambda: _FakeSessionCM()),
        patch("application.transfer_service.TransferJobRepository", _FakeRepo),
    ):
        result = await create_job(
            path=TransferPath.PG_TO_PG,
            source_connection_id=SRC,
            target_connection_id=TGT,
            tables=[
                TransferTableMapping(
                    source_schema="public",
                    source_table="orders",
                    target_schema="public",
                    target_table="orders",
                )
            ],
            threshold=TransferThreshold(chunk_size=25_000),
            constraint_plan={"on_stop": "restore_now", "operator_reviewed": True, "items": []},
            create_if_missing=False,
            project_id="proj-1",
        )

    captured = _FakeRepo.captured
    assert captured is not None
    config = captured["config"]
    assert config["kind"] == "transfer"
    assert "executor" not in config
    assert config["path"] == "pg_to_pg"
    assert config["tables"][0]["columns"] == ["id", "amount"]
    assert config["tables"][0]["chunk_size"] == 25_000
    assert config["file_offload"]["enabled"] is True
    assert config["file_offload"]["min_rows"] == 2_000_000
    assert captured.get("job_id") == config["job_id"]
    assert result["job_id"] == config["job_id"]
    assert captured["constraint_plan"]["operator_reviewed"] is True


@pytest.mark.asyncio
async def test_create_job_rejects_unreviewed_destination_constraints():
    _FakeRepo.captured = None
    preflight = {
        "can_start": True,
        "tables": [
            {
                "source": {"schema": "public", "table": "orders"},
                "target": {"schema": "public", "table": "orders"},
                "row_count_source": 50,
                "columns": {"matched": [{"name": "id"}]},
                "constraints": [],
                "indexes": [],
                "foreign_keys": [{"id": "orders_fk", "kind": "foreign_key", "recommended_action": "disable"}],
                "triggers": [],
            }
        ],
        "summary": {"can_start": True},
    }
    with (
        patch("application.transfer_service.run_preflight", new=AsyncMock(return_value=preflight)),
        patch(
            "application.transfer_service.get_entry",
            side_effect=lambda cid: _entry("srcdb") if cid == str(SRC) else _entry("tgtdb"),
        ),
        patch("application.transfer_service.AsyncSessionFactory", lambda: _FakeSessionCM()),
        patch("application.transfer_service.TransferJobRepository", _FakeRepo),
    ):
        with pytest.raises(TransferError, match="Review the destination"):
            await create_job(
                path=TransferPath.PG_TO_PG,
                source_connection_id=SRC,
                target_connection_id=TGT,
                tables=[
                    TransferTableMapping(
                        source_schema="public",
                        source_table="orders",
                        target_schema="public",
                        target_table="orders",
                    )
                ],
                threshold=TransferThreshold(),
                constraint_plan=None,
                create_if_missing=False,
                project_id="proj-1",
            )
    assert _FakeRepo.captured is None
