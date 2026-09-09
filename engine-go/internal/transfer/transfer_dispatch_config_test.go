// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"encoding/json"
	"testing"
)

func TestParseTransferDispatchConfig_valid(t *testing.T) {
	raw := json.RawMessage(`{
		"job_id": "550e8400-e29b-41d4-a716-446655440000",
		"kind": "transfer",
		"path": "pg_to_pg",
		"source": {"connection_id": "550e8400-e29b-41d4-a716-446655440001", "schema": "public", "engine": "postgres"},
		"target": {"connection_id": "550e8400-e29b-41d4-a716-446655440002", "schema": "public", "engine": "postgres"},
		"tables": [{
			"source_schema": "public",
			"source_table": "orders",
			"target_schema": "public",
			"target_table": "orders",
			"columns": ["id", "amount"],
			"chunk_size": 10000,
			"order_column": "id"
		}]
	}`)
	cfg, err := ParseTransferDispatchConfig(raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Kind != "transfer" || cfg.Path != "pg_to_pg" {
		t.Fatalf("unexpected header: %+v", cfg)
	}
	if cfg.FileOffload == nil || !cfg.FileOffload.Enabled || cfg.FileOffload.MinRows != 2_000_000 {
		t.Fatalf("expected default file offload settings, got %+v", cfg.FileOffload)
	}
	if len(cfg.Tables) != 1 || cfg.Tables[0].SourceTable != "orders" {
		t.Fatalf("unexpected tables: %+v", cfg.Tables)
	}
}

func TestParseTransferDispatchConfig_rejects_migration_kind(t *testing.T) {
	raw := json.RawMessage(`{"job_id":"550e8400-e29b-41d4-a716-446655440000","kind":"go","path":"pg_to_pg","tables":[{"source_schema":"public","source_table":"t","target_schema":"public","target_table":"t","columns":["id"]}]}`)
	if _, err := ParseTransferDispatchConfig(raw); err == nil {
		t.Fatal("expected error for migration kind")
	}
}

func TestParseTransferDispatchConfig_rejects_empty_tables(t *testing.T) {
	raw := json.RawMessage(`{"job_id":"550e8400-e29b-41d4-a716-446655440000","kind":"transfer","path":"pg_to_pg","source":{"connection_id":"550e8400-e29b-41d4-a716-446655440001","schema":"public","engine":"postgres"},"target":{"connection_id":"550e8400-e29b-41d4-a716-446655440002","schema":"public","engine":"postgres"},"tables":[]}`)
	if _, err := ParseTransferDispatchConfig(raw); err == nil {
		t.Fatal("expected error for empty tables")
	}
}

func TestPathSupportsDataPlane(t *testing.T) {
	if !PathSupportsDataPlane("pg_to_pg") {
		t.Fatal("pg_to_pg must be implemented")
	}
	if !PathSupportsDataPlane("mssql_to_pg") {
		t.Fatal("mssql_to_pg reuses existing extract/COPY")
	}
	if PathSupportsDataPlane("pg_to_mssql") {
		t.Fatal("pg_to_mssql is not in this slice")
	}
	if !PathSupportsDataPlane("mssql_to_mssql") {
		t.Fatal("mssql_to_mssql must be implemented in slice 4")
	}
}

func TestShouldFileOffload(t *testing.T) {
	settings := DefaultFileOffloadSettings()
	if ShouldFileOffload(true, settings, 10_000_000, 4000) {
		t.Fatal("same-server must never file-offload")
	}
	if !ShouldFileOffload(false, settings, 2_000_000, 10) {
		t.Fatal("row threshold should enable offload")
	}
	disabled := settings
	disabled.Enabled = false
	if ShouldFileOffload(false, disabled, 10_000_000, 4000) {
		t.Fatal("app-level disable must skip offload")
	}
}

func TestParseTransferDispatchConfig_file_offload_snapshot(t *testing.T) {
	raw := json.RawMessage(`{
		"job_id": "550e8400-e29b-41d4-a716-446655440000",
		"kind": "transfer",
		"path": "pg_to_pg",
		"source": {"connection_id": "550e8400-e29b-41d4-a716-446655440001", "schema": "public", "engine": "postgres"},
		"target": {"connection_id": "550e8400-e29b-41d4-a716-446655440002", "schema": "public", "engine": "postgres"},
		"tables": [{"source_schema": "public", "source_table": "orders", "target_schema": "public", "target_table": "orders", "columns": ["id"]}],
		"file_offload": {"enabled": false, "min_rows": 5000000, "min_mb": 512, "staging_path": "D:/offload"}
	}`)
	cfg, err := ParseTransferDispatchConfig(raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.FileOffload.Enabled || cfg.FileOffload.MinRows != 5_000_000 || cfg.FileOffload.StagingPath != "D:/offload" {
		t.Fatalf("file offload = %+v", cfg.FileOffload)
	}
}
