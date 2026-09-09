// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

func TestEffectiveEnginePrefersEngineColumn(t *testing.T) {
	conn := &metadata.ProjectConnection{Engine: "postgres", DBType: "source"}
	if got := EffectiveEngine(conn); got != "postgres" {
		t.Fatalf("got %s", got)
	}
}

func TestEffectiveEngineFallsBackToRole(t *testing.T) {
	if got := EffectiveEngine(&metadata.ProjectConnection{DBType: "target"}); got != "postgres" {
		t.Fatalf("got %s", got)
	}
	if got := EffectiveEngine(&metadata.ProjectConnection{DBType: "source"}); got != "sqlserver" {
		t.Fatalf("got %s", got)
	}
}

func TestLiveTransferTableMoverRejectsUnsupportedEngines(t *testing.T) {
	mover := NewLiveTransferTableMover("")
	table := TransferTablePayload{
		SourceSchema: "public",
		SourceTable:  "orders",
		TargetSchema: "dbo",
		TargetTable:  "orders",
		Columns:      []string{"id"},
	}
	_, err := mover.Move(
		context.Background(),
		uuid.New(),
		&metadata.ProjectConnection{Engine: "postgres"},
		&metadata.ProjectConnection{Engine: "sqlserver"},
		table,
	)
	if err == nil || !strings.Contains(err.Error(), "does not support") {
		t.Fatalf("expected unsupported path error, got %v", err)
	}
}

func TestRewriteCopyAsText(t *testing.T) {
	in := `COPY "public"."orders" ("id") FROM STDIN WITH (FORMAT binary)`
	got := rewriteCopyAsText(in)
	want := `COPY "public"."orders" ("id") FROM STDIN`
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}
