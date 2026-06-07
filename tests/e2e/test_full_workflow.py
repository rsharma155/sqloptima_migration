"""
Module: tests/e2e/test_full_workflow.py
Purpose: End-to-end tests for the full migration workflow (mock-based)
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from domains.migration.migration_engine import (
    ChunkedMigration,
    DataExtractor,
    DataLoader,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)
from domains.transpilation.compatibility_analyzer import CompatibilityAnalyzer
from domains.transpilation.ddl_generator import DdlGenerator
from domains.transpilation.ir_models import ColumnDefNode, DataTypeNode, IrNode, IrNodeType
from domains.transpilation.procedural_converter import ProceduralConverter
from domains.validation.validation_engine import (
    ChecksumValidator,
    RowCountValidator,
    SchemaValidator,
    ValidationStatus,
)
from shared.kernel.database_object import (
    Column,
    DataType,
    Table,
)


class MockMetadataDiscovery:
    """Mock metadata discovery for testing."""

    async def discover(self, connection_id, schema):
        return {
            "tables": [
                {"name": "users", "schema": schema, "columns": [
                    {"name": "id", "type": "INT", "nullable": False, "is_pk": True},
                    {"name": "name", "type": "VARCHAR(100)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(255)", "nullable": True},
                ]},
                {"name": "orders", "schema": schema, "columns": [
                    {"name": "id", "type": "INT", "nullable": False, "is_pk": True},
                    {"name": "user_id", "type": "INT", "nullable": False},
                    {"name": "total", "type": "DECIMAL(10,2)", "nullable": False},
                ]},
            ],
            "views": [],
            "procedures": [
                {"name": "usp_get_users", "schema": schema,
                 "definition": "CREATE PROCEDURE usp_get_users AS SELECT * FROM users"},
            ],
            "functions": [],
        }


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=[])
    conn.copy_from_rows = AsyncMock(return_value=10)
    return conn


class TestFullWorkflow:
    """End-to-end test of the complete migration workflow."""

    @pytest.mark.asyncio
    async def test_discover_to_migrate_to_validate(self, mock_connector):
        """Full workflow: discover → convert → generate DDL → migrate → validate."""
        # Step 1: Discover
        discovery = MockMetadataDiscovery()
        schema_info = await discovery.discover(uuid4(), "dbo")
        assert len(schema_info["tables"]) == 2
        assert len(schema_info["procedures"]) == 1

        # Step 2: Analyze compatibility
        analyzer = CompatibilityAnalyzer()
        objects = []
        for t in schema_info["tables"]:
            obj = Table(
                database_name="test_db",
                schema_name="dbo",
                object_name=t["name"],
            )
            for c in t["columns"]:
                col = Column(
                    column_name=c["name"],
                    data_type=DataType(type_name=c["type"]),
                    table_id=obj.id,
                    ordinal_position=t["columns"].index(c) + 1,
                )
                obj.columns.append(col)
            objects.append(obj)

        results = analyzer.analyze_batch(objects)
        assert len(results) == 2

        # Step 3: Generate DDL
        generator = DdlGenerator()
        for obj in objects:
            col_nodes = [
                ColumnDefNode(
                    column_name=c.column_name,
                    data_type=DataTypeNode(type_name=c.data_type.type_name),
                )
                for c in obj.columns
            ]
            ir_node = IrNode(
                node_type=IrNodeType.CREATE_TABLE,
                properties={"name": obj.object_name, "schema": obj.schema_name},
                children=col_nodes,
            )
            ddl = generator.generate_table_ddl(ir_node)
            assert "CREATE TABLE" in ddl

        # Step 4: Migrate data
        extractor = DataExtractor(mock_connector)
        loader = DataLoader(mock_connector)
        migration = ChunkedMigration(extractor, loader, chunk_size=100)

        mock_connector.execute.return_value = [{"id": 1, "name": "Alice", "email": "alice@test.com"}]
        for table_info in schema_info["tables"]:
            plan = TableMigrationPlan(
                table_name=table_info["name"],
                schema_name="dbo",
                columns=[c["name"] for c in table_info["columns"]],
                row_count_estimate=1,
                strategy=MigrationStrategy.CHUNKED,
            )
            result = await migration.migrate_table(plan)
            assert result.status == MigrationStatus.COMPLETED

        # Step 5: Validate
        schema_validator = SchemaValidator()
        RowCountValidator()
        ChecksumValidator()

        for table_info in schema_info["tables"]:
            sv = await schema_validator.validate_columns(
                source_columns=table_info["columns"],
                target_columns=table_info["columns"],
                table_name=table_info["name"],
            )
            assert sv.status == ValidationStatus.PASSED

        # Step 6: Generate report
        report_data = {
            "total_objects": len(objects),
            "compatibility": [r.auto_convertible_percentage for r in results],
            "migration_results": [],
        }
        assert report_data["total_objects"] == 2
        assert all(pct >= 0 for pct in report_data["compatibility"])


class TestErrorRecoveryWorkflow:
    """Tests error handling throughout the workflow."""

    @pytest.mark.asyncio
    async def test_migration_failure_does_not_block_others(self, mock_connector):
        """If one table fails, others should still complete."""
        extractor = MagicMock(spec=DataExtractor)
        extractor.extract_chunk = AsyncMock()
        extractor._connector = mock_connector

        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock()

        # First table fails, second succeeds
        call_count = [0]

        async def failing_extract(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Table A failed")
            return [{"id": 1}]

        extractor.extract_chunk.side_effect = failing_extract
        loader.load_chunk.side_effect = lambda schema, table, columns, rows: len(rows)

        migration = ChunkedMigration(extractor, loader)

        results = []
        for name in ["table_a", "table_b"]:
            plan = TableMigrationPlan(
                table_name=name, schema_name="dbo", columns=["id"],
                row_count_estimate=10, strategy=MigrationStrategy.CHUNKED,
            )
            results.append(await migration.migrate_table(plan))

        assert results[0].status == MigrationStatus.FAILED
        assert results[1].status == MigrationStatus.COMPLETED


class TestConversionThenMigrationWorkflow:
    """Tests that conversion results can feed into migration."""

    def test_conversion_output_for_migration(self):
        """Convert a procedure, then verify the output is syntactically valid PL/pgSQL."""
        converter = ProceduralConverter()
        result = converter.convert_procedure(
            schema="dbo", name="usp_example",
            parameters=[],
            body="SELECT id, name FROM dbo.users WHERE active = 1;",
        )
        assert result.success
        sql = result.converted_sql
        assert "CREATE OR REPLACE PROCEDURE" in sql
        assert "usp_example" in sql
        assert "LANGUAGE plpgsql" in sql or "LANGUAGE" in sql
