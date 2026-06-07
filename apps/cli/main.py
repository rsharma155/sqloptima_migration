"""
Module: apps/cli/main.py
Purpose: CLI tool for the migration platform using argparse
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from shared.logging.structured_logging import configure_logging, get_logger

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migration-platform",
        description="SQL Server to PostgreSQL Migration Platform CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # discover
    discover_p = sub.add_parser("discover", help="Discover database objects")
    discover_p.add_argument("--connection-id", required=True, help="Source connection UUID")
    discover_p.add_argument("--schema", default="dbo", help="Schema to scan")

    # migrate
    migrate_p = sub.add_parser("migrate", help="Run a migration")
    migrate_p.add_argument("--source-connection", required=True, help="Source connection UUID")
    migrate_p.add_argument("--target-connection", required=True, help="Target connection UUID")
    migrate_p.add_argument("--tables", nargs="+", required=True, help="Tables to migrate")
    migrate_p.add_argument("--schema", default="dbo", help="Source schema")
    migrate_p.add_argument("--strategy", default="chunked", choices=["chunked", "parallel", "streaming"])
    migrate_p.add_argument("--chunk-size", type=int, default=10000)
    migrate_p.add_argument("--workers", type=int, default=4)
    migrate_p.add_argument("--validate", action="store_true", default=True)

    # convert
    convert_p = sub.add_parser("convert", help="Convert T-SQL to PL/pgSQL")
    convert_p.add_argument("--input", "-i", required=True, help="Input SQL file")
    convert_p.add_argument("--output", "-o", help="Output file (default: stdout)")
    convert_p.add_argument("--type", default="auto",
                           choices=["auto", "raw", "procedure", "function", "trigger"])
    convert_p.add_argument("--name", default="usp_example", help="Object name")
    convert_p.add_argument("--schema", default="dbo")

    # provision-tables
    provision_p = sub.add_parser(
        "provision-tables",
        help="Create missing PostgreSQL target tables for an existing migration job",
    )
    provision_p.add_argument("--job-id", required=True, help="Migration job UUID")

    # validate
    validate_p = sub.add_parser("validate", help="Validate migration results")
    validate_p.add_argument("--source-connection", required=True)
    validate_p.add_argument("--target-connection", required=True)
    validate_p.add_argument("--tables", nargs="+", required=True)

    # analyze
    analyze_p = sub.add_parser("analyze", help="Analyze T-SQL complexity")
    analyze_p.add_argument("--input", "-i", required=True, help="Input SQL file")
    analyze_p.add_argument("--output", "-o", help="Output JSON file")

    # analyze-cfg
    cfg_p = sub.add_parser("analyze-cfg", help="Build Control Flow Graph from T-SQL")
    cfg_p.add_argument("--input", "-i", required=True, help="Input SQL file")
    cfg_p.add_argument("--format", default="mermaid", choices=["mermaid", "json"])
    cfg_p.add_argument("--output", "-o", help="Output file")

    # analyze-vars
    vars_p = sub.add_parser("analyze-vars", help="Analyze variable scopes in T-SQL")
    vars_p.add_argument("--input", "-i", required=True, help="Input SQL file")
    vars_p.add_argument("--unused", action="store_true", help="Show unused variables only")

    # server
    server_p = sub.add_parser("server", help="Start the FastAPI server")
    server_p.add_argument("--host", default="0.0.0.0")
    server_p.add_argument("--port", type=int, default=8508)
    server_p.add_argument("--reload", action="store_true")

    return parser


async def cmd_convert(args: argparse.Namespace) -> None:
    from domains.transpilation.procedural_converter import ProceduralConverter

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    sql = input_path.read_text(encoding="utf-8")
    converter = ProceduralConverter()

    if args.type == "auto":
        result = converter.auto_convert(sql)
    elif args.type == "raw":
        result = converter.convert_adhoc(sql)
    elif args.type == "procedure":
        result = converter.convert_procedure(args.schema, args.name, [], sql)
    elif args.type == "function":
        result = converter.convert_function(args.schema, args.name, [], sql)
    elif args.type == "trigger":
        result = converter.convert_trigger(args.schema, args.name, args.name,
                                            "BEFORE", "INSERT OR UPDATE OR DELETE", sql)

    output = result.converted_sql
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)

    if result.warnings:
        print("\n--- Warnings ---", file=sys.stderr)
        for w in result.warnings:
            print(w, file=sys.stderr)
    if result.errors:
        print("\n--- Errors ---", file=sys.stderr)
        for e in result.errors:
            print(e, file=sys.stderr)
        sys.exit(1)


async def cmd_analyze(args: argparse.Namespace) -> None:
    from domains.transpilation.procedural_converter import (
        DynamicSqlAnalyzer,
        TSqlPatternMatcher,
    )

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    sql = input_path.read_text(encoding="utf-8")

    difficulty = TSqlPatternMatcher.detect_difficulty(sql)
    patterns = TSqlPatternMatcher.detect_patterns(sql)

    analyzer = DynamicSqlAnalyzer()
    occurrences = analyzer.analyze(sql)
    remediations = analyzer.generate_remediation(occurrences)

    report = {
        "difficulty": difficulty.value,
        "patterns": patterns,
        "dynamic_sql_count": len(occurrences),
        "remediations": remediations,
    }

    output = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


async def cmd_analyze_cfg(args: argparse.Namespace) -> None:
    from domains.transpilation.procedural_converter import ControlFlowGraphBuilder

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    sql = input_path.read_text(encoding="utf-8")
    builder = ControlFlowGraphBuilder()
    cfg = builder.build(sql)

    if args.format == "mermaid":
        output = builder.to_mermaid(cfg)
    else:
        output = json.dumps({
            "nodes": [
                {"id": n.node_id, "label": n.label, "type": n.statement_type}
                for n in cfg.nodes
            ],
            "edges": [
                {"from": n.node_id, "to": c.node_id}
                for n in cfg.nodes for c in n.children
            ],
        }, indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


async def cmd_analyze_vars(args: argparse.Namespace) -> None:
    from domains.transpilation.procedural_converter import VariableScopeResolver

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    sql = input_path.read_text(encoding="utf-8")
    resolver = VariableScopeResolver()
    resolver.resolve(sql)

    variables = resolver.find_unused_variables() if args.unused else resolver.get_all_variables()

    if not variables:
        print("No variables found.")
        return

    for v in variables:
        print(f"  {v.name}: {v.data_type} (line {v.declared_line})")
        if v.used_in_lines:
            print(f"      Used at lines: {v.used_in_lines}")
        if args.unused:
            print("      ** UNUSED **")


async def main(args: argparse.Namespace) -> None:
    if args.command == "convert":
        await cmd_convert(args)
    elif args.command == "analyze":
        await cmd_analyze(args)
    elif args.command == "analyze-cfg":
        await cmd_analyze_cfg(args)
    elif args.command == "analyze-vars":
        await cmd_analyze_vars(args)
    elif args.command == "discover":
        from infrastructure.sqlserver.sqlserver_connector import (
            SqlServerConnectionConfig,
            SqlServerConnector,
        )
        from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

        config = SqlServerConnectionConfig(
            host="localhost", port=1433, database="source_db",
            username="user", password="",
        )
        connector = SqlServerConnector(config)
        try:
            await connector.connect()
        except Exception as exc:
            logger.error("Failed to connect to source database", error=str(exc))
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            discovery = SqlServerMetadataDiscovery(connector)
            tables = await discovery.discover_tables("source_db", args.schema)
            logger.info("Discovery completed", schema=args.schema, tables_found=len(tables))
            print(f"Discovered {len(tables)} tables in {args.schema}:")
            for t in tables:
                print(f"  {t.object_name} ({len(t.columns)} columns)")
        except Exception as exc:
            logger.error("Discovery failed", schema=args.schema, error=str(exc))
            print(f"Error: {exc}", file=sys.stderr)
        finally:
            await connector.disconnect()
    elif args.command == "migrate":
        from domains.orchestration.activities import migrate_table

        result = await migrate_table(
            schema=args.schema,
            table=args.tables[0],
            columns=["*"],
            chunk_size=args.chunk_size,
            parallel_workers=args.workers,
        )
        print(f"Migration result: {result.get('status')} — {result.get('rows_migrated', 0)} rows")
    elif args.command == "provision-tables":
        from uuid import UUID

        from application.go_engine_migration.provision_job_tables import (
            provision_tables_for_job_id,
        )
        from application.migration_service import load_jobs
        from infrastructure.metadata_db.session import init_db

        await init_db()
        await load_jobs()
        job_id = UUID(args.job_id)
        try:
            created = await provision_tables_for_job_id(job_id)
        except KeyError:
            print(f"Error: migration job not found: {job_id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if created:
            print(f"Provisioned {len(created)} table(s): {', '.join(created)}")
        else:
            print("All target tables already exist — nothing created")
    elif args.command == "validate":
        from domains.orchestration.activities import validate_table

        result = await validate_table(
            source_conn=args.source_connection,
            target_conn=args.target_connection,
            schema="dbo",
            table=args.tables[0],
        )
        print(f"Validation result: {result.get('status')} — source={result.get('source_count')}, target={result.get('target_count')}")


if __name__ == "__main__":
    configure_logging(level=os.environ.get("MIGRATION_LOG_LEVEL", "INFO"))
    _parser = build_parser()
    _args = _parser.parse_args()

    if _args.command == "server":
        import uvicorn
        uvicorn.run("apps.api.main:app", host=_args.host, port=_args.port, reload=_args.reload)
    else:
        asyncio.run(main(_args))
