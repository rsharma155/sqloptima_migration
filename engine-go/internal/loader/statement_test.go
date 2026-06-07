// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
)

func TestBuildsStatementWithColumns(t *testing.T) {
	sql := loader.BuildCopyStatement("public", "orders", []string{"id", "total"})
	want := `COPY "public"."orders" ("id", "total") FROM STDIN WITH (FORMAT binary)`
	if sql != want {
		t.Errorf("got:  %s\nwant: %s", sql, want)
	}
}

func TestBuildsStatementWithoutColumns(t *testing.T) {
	sql := loader.BuildCopyStatement("public", "orders", nil)
	want := `COPY "public"."orders" FROM STDIN WITH (FORMAT binary)`
	if sql != want {
		t.Errorf("got:  %s\nwant: %s", sql, want)
	}
}

func TestQuotesIdentifiers(t *testing.T) {
	sql := loader.BuildCopyStatement("my schema", "order items", []string{"unit price"})
	if !strings.Contains(sql, `"my schema"."order items"`) {
		t.Errorf("spaces in identifiers must be quoted, got: %s", sql)
	}
}

func TestInjectionViaQuoteNeutralised(t *testing.T) {
	sql := loader.BuildCopyStatement("public", `x"; DROP TABLE users; --`, []string{"id"})
	if !strings.Contains(sql, `"x""; DROP TABLE users; --"`) {
		t.Errorf("embedded quote must be doubled, got: %s", sql)
	}
}

func TestAlwaysBinaryFormat(t *testing.T) {
	sql := loader.BuildCopyStatement("public", "t", []string{"id"})
	if !strings.HasSuffix(sql, "FROM STDIN WITH (FORMAT binary)") {
		t.Errorf("must end with binary format clause, got: %s", sql)
	}
}
