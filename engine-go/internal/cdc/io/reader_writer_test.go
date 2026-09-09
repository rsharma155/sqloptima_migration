// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/reader_writer_test.go
// Purpose: Unit tests for LSN/bind helpers (pure convert path)
// Domain: Replication / CDC
// Author: Ravi Sharma

package cdcio_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
	cdcio "github.com/ravisharma/sql-optima/engine-go/internal/cdc/io"
)

func TestBindArgsDeleteUsesPKColumns(t *testing.T) {
	ev := &cdc.CDCEvent{
		Operation: cdc.OpDelete,
		Columns:   map[string]interface{}{"id": 42, "name": "x"},
	}
	stmt := cdc.BuildApplyStatement("public", "users", cdc.OpDelete, []string{"id", "name"}, []string{"id"})
	args, err := cdcio.BindArgsForTest(ev, stmt, []string{"id", "name"}, []string{"id"})
	if err != nil {
		t.Fatal(err)
	}
	if len(args) != 1 || args[0] != 42 {
		t.Fatalf("expected [42], got %#v", args)
	}
}

func TestBindArgsUpsertUsesAllColumns(t *testing.T) {
	ev := &cdc.CDCEvent{
		Operation: cdc.OpInsert,
		Columns:   map[string]interface{}{"id": 1, "name": "a"},
	}
	stmt := cdc.BuildApplyStatement("public", "users", cdc.OpInsert, []string{"id", "name"}, []string{"id"})
	args, err := cdcio.BindArgsForTest(ev, stmt, []string{"id", "name"}, []string{"id"})
	if err != nil {
		t.Fatal(err)
	}
	if len(args) != 2 || args[0] != 1 || args[1] != "a" {
		t.Fatalf("unexpected args %#v", args)
	}
}

func TestBytesToLSNPadsShort(t *testing.T) {
	lsn, err := cdcio.BytesToLSNForTest([]byte{1, 2, 3})
	if err != nil {
		t.Fatal(err)
	}
	if lsn.IsZero() {
		t.Fatal("expected non-zero padded LSN")
	}
	if lsn[7] != 1 || lsn[8] != 2 || lsn[9] != 3 {
		t.Fatalf("unexpected padding: %v", lsn)
	}
}

func TestBindArgsDeleteMissingPKErrors(t *testing.T) {
	ev := &cdc.CDCEvent{
		Operation: cdc.OpDelete,
		Columns:   map[string]interface{}{"name": "x"},
	}
	stmt := cdc.BuildApplyStatement("public", "users", cdc.OpDelete, []string{"id"}, []string{"id"})
	_, err := cdcio.BindArgsForTest(ev, stmt, []string{"id"}, []string{"id"})
	if err == nil {
		t.Fatal("expected missing PK error")
	}
}
