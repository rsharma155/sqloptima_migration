// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

func TestExtractQueryListsColumnsAndOrdersByPK(t *testing.T) {
	sql := extractor.BuildExtractQuery("dbo", "orders", "id", []string{"id", "total"})
	want := "SELECT [id], [total] FROM [dbo].[orders] WHERE [id] >= @P1 AND [id] <= @P2 ORDER BY [id]"
	if sql != want {
		t.Errorf("got:  %s\nwant: %s", sql, want)
	}
}

func TestExtractQueryUsesStarWhenNoColumns(t *testing.T) {
	sql := extractor.BuildExtractQuery("dbo", "orders", "id", nil)
	if !strings.HasPrefix(sql, "SELECT * FROM [dbo].[orders]") {
		t.Errorf("no-column query must use *, got: %s", sql)
	}
}

func TestExtractQueryIsParameterised(t *testing.T) {
	sql := extractor.BuildExtractQuery("dbo", "t", "id", []string{"id"})
	if !strings.Contains(sql, "@P1") || !strings.Contains(sql, "@P2") {
		t.Errorf("query must contain @P1 and @P2, got: %s", sql)
	}
}

func TestIdentifiersAreBracketQuoted(t *testing.T) {
	sql := extractor.BuildExtractQuery("sales", "Order Items", "Order Id", []string{"Qty"})
	if !strings.Contains(sql, "[sales].[Order Items]") {
		t.Errorf("table must be bracket-quoted, got: %s", sql)
	}
	if !strings.Contains(sql, "[Order Id]") || !strings.Contains(sql, "[Qty]") {
		t.Errorf("columns must be bracket-quoted, got: %s", sql)
	}
}

func TestInjectionViaClosingBracketNeutralised(t *testing.T) {
	sql := extractor.BuildExtractQuery("dbo", "x]; DROP TABLE users; --", "id", []string{"id"})
	if !strings.Contains(sql, "[x]]; DROP TABLE users; --]") {
		t.Errorf("closing bracket must be doubled, got: %s", sql)
	}
	if strings.Contains(sql, "[x];") {
		t.Errorf("injection must not break bracket context, got: %s", sql)
	}
}

func TestCountQueryUsesCountBig(t *testing.T) {
	sql := extractor.BuildCountQuery("dbo", "orders")
	if sql != "SELECT COUNT_BIG(*) FROM [dbo].[orders]" {
		t.Errorf("count query = %q", sql)
	}
}

func TestBoundsQuerySelectsMinMax(t *testing.T) {
	sql := extractor.BuildBoundsQuery("dbo", "orders", "id")
	if sql != "SELECT MIN([id]) AS lo, MAX([id]) AS hi FROM [dbo].[orders]" {
		t.Errorf("bounds query = %q", sql)
	}
}

func TestExtractQueryWithOptionsNOLOCKAndMAXDOP(t *testing.T) {
	opts := extractor.ExtractOptions{
		WhereClause:  "active = 1",
		OrderColumn:  "created_at",
		MaxDOP:       4,
		NoLock:       true,
		UUIDKeyRange: true,
	}
	sql := extractor.BuildExtractQueryWithOptions("dbo", "orders", "id", []string{"id"}, opts)
	if !strings.Contains(sql, "WITH (NOLOCK)") {
		t.Errorf("expected NOLOCK hint, got: %s", sql)
	}
	if !strings.Contains(sql, "OPTION (MAXDOP 4)") {
		t.Errorf("expected MAXDOP, got: %s", sql)
	}
	if !strings.Contains(sql, "CAST([id] AS CHAR(36))") {
		t.Errorf("expected UUID cast, got: %s", sql)
	}
	if !strings.Contains(sql, "AND (active = 1)") {
		t.Errorf("expected where clause, got: %s", sql)
	}
	if !strings.Contains(sql, "ORDER BY [created_at]") {
		t.Errorf("expected order column override, got: %s", sql)
	}
}
