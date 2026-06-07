// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"encoding/json"
	"testing"
)

func TestParseGoJobDispatchConfig_valid(t *testing.T) {
	raw := json.RawMessage(`{
		"job_id": "550e8400-e29b-41d4-a716-446655440000",
		"executor": "go",
		"source": {"connection_id": "a", "schema": "dbo"},
		"target": {"connection_id": "b", "schema": "public"},
		"tables": [{
			"table_name": "Customers",
			"source_schema": "dbo",
			"target_schema": "public",
			"columns": ["Id", "Name"],
			"chunk_size": 10000,
			"parallel_workers": 4,
			"strategy": "chunked"
		}]
	}`)
	cfg, err := ParseGoJobDispatchConfig(raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Tables) != 1 || cfg.Tables[0].TableName != "Customers" {
		t.Fatalf("unexpected tables: %+v", cfg.Tables)
	}
}

func TestParseGoJobDispatchConfig_rejects_empty_tables(t *testing.T) {
	raw := json.RawMessage(`{"job_id":"550e8400-e29b-41d4-a716-446655440000","executor":"go","source":{"connection_id":"a","schema":"dbo"},"target":{"connection_id":"b","schema":"public"},"tables":[]}`)
	_, err := ParseGoJobDispatchConfig(raw)
	if err == nil {
		t.Fatal("expected error for empty tables")
	}
}
