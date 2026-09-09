// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractport_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
)

func TestBuildPostgresExtractQueryIsParameterized(t *testing.T) {
	sql := extractport.BuildPostgresExtractQuery("public", "orders", "id", []string{"id", "amount"})
	want := `SELECT "id", "amount" FROM "public"."orders" WHERE "id" >= $1 AND "id" <= $2 ORDER BY "id"`
	if sql != want {
		t.Fatalf("got %s\nwant %s", sql, want)
	}
}

func TestBuildPostgresExtractQueryQuotesEmbeddedDoubleQuote(t *testing.T) {
	sql := extractport.BuildPostgresExtractQuery(`public`, `ord"ers`, "id", []string{"id"})
	if !strings.Contains(sql, `"ord""ers"`) {
		t.Fatalf("embedded quote must be doubled, got %s", sql)
	}
}

func TestBuildPostgresExtractQueryFullTableWhenNoOrderColumn(t *testing.T) {
	sql := extractport.BuildPostgresExtractQuery("public", "orders", "", []string{"id", "amount"})
	want := `SELECT "id", "amount" FROM "public"."orders"`
	if sql != want {
		t.Fatalf("got %s\nwant %s", sql, want)
	}
	if strings.Contains(sql, "$1") {
		t.Fatal("full-table extract must not use key parameters")
	}
}

func TestBuildPostgresBoundsQuery(t *testing.T) {
	sql := extractport.BuildPostgresBoundsQuery("public", "orders", "id")
	want := `SELECT MIN("id") AS lo, MAX("id") AS hi FROM "public"."orders"`
	if sql != want {
		t.Fatalf("got %s want %s", sql, want)
	}
}
