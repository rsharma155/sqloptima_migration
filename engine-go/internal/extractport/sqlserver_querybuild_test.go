// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractport_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
)

func TestBuildSQLServerFullTableQueryQuotesIdentifiers(t *testing.T) {
	sql := extractport.BuildSQLServerFullTableQuery("dbo", "orders", []string{"id", "amount"})
	want := "SELECT [id], [amount] FROM [dbo].[orders]"
	if sql != want {
		t.Fatalf("got %s\nwant %s", sql, want)
	}
	if strings.Contains(sql, "@P1") || strings.Contains(sql, "'") {
		t.Fatal("full-table extract must not interpolate values")
	}
}

func TestBuildSQLServerFullTableQueryEscapesClosingBracket(t *testing.T) {
	sql := extractport.BuildSQLServerFullTableQuery("dbo", "ord]ers", []string{"id"})
	if !strings.Contains(sql, "[ord]]ers]") {
		t.Fatalf("embedded bracket must be doubled, got %s", sql)
	}
}

func TestBuildSQLServerPartitionRowEstimateQueryIsParameterized(t *testing.T) {
	sql := extractport.BuildSQLServerPartitionRowEstimateQuery()
	if !strings.Contains(sql, "sys.dm_db_partition_stats") {
		t.Fatalf("expected dm_db_partition_stats, got %s", sql)
	}
	if !strings.Contains(sql, "s.name = @P1") || !strings.Contains(sql, "o.name = @P2") {
		t.Fatalf("schema/table must be parameters, got %s", sql)
	}
	if strings.Contains(sql, "sp_spaceused") {
		t.Fatal("must not call sp_spaceused")
	}
}

func TestBuildSQLServerIntegerRangeSelectIsParameterized(t *testing.T) {
	sql := extractport.BuildSQLServerIntegerRangeSelect("dbo", "orders", "id", []string{"id", "amount"})
	want := "SELECT [id], [amount] FROM [dbo].[orders] WHERE [id] >= @P1 AND [id] <= @P2 ORDER BY [id]"
	if sql != want {
		t.Fatalf("got %s\nwant %s", sql, want)
	}
	if strings.Contains(sql, "NOLOCK") {
		t.Fatal("must not default NOLOCK")
	}
}

func TestBuildSQLServerIntegerRangeInsertSelectUsesFourPartNames(t *testing.T) {
	sql := extractport.BuildSQLServerIntegerRangeInsertSelect(
		"SrcDB", "dbo", "orders",
		"TgtDB", "dbo", "orders",
		"id", []string{"id", "amount"},
	)
	want := "INSERT INTO [TgtDB].[dbo].[orders] ([id], [amount]) SELECT [id], [amount] FROM [SrcDB].[dbo].[orders] WHERE [id] >= @P1 AND [id] <= @P2"
	if sql != want {
		t.Fatalf("got %s\nwant %s", sql, want)
	}
}

func TestBuildSQLServerKeysetSelectFirstAndNext(t *testing.T) {
	first := extractport.BuildSQLServerKeysetSelect("dbo", "orders", "id", []string{"id", "amount"}, false)
	if first != "SELECT TOP (@P1) [id], [amount] FROM [dbo].[orders] ORDER BY [id]" {
		t.Fatalf("first batch: %s", first)
	}
	next := extractport.BuildSQLServerKeysetSelect("dbo", "orders", "id", []string{"id", "amount"}, true)
	if next != "SELECT TOP (@P2) [id], [amount] FROM [dbo].[orders] WHERE [id] > @P1 ORDER BY [id]" {
		t.Fatalf("next batch: %s", next)
	}
}

func TestBuildSQLServerDeltaSelect(t *testing.T) {
	sql := extractport.BuildSQLServerDeltaSelect("dbo", "orders", "id", []string{"id", "amount"})
	want := "SELECT [id], [amount] FROM [dbo].[orders] WHERE [id] > @P1 ORDER BY [id]"
	if sql != want {
		t.Fatalf("got %s", sql)
	}
}

func TestBuildSQLServerIdentityInsert(t *testing.T) {
	on := extractport.BuildSQLServerIdentityInsert("dbo", "orders", true)
	off := extractport.BuildSQLServerIdentityInsert("dbo", "orders", false)
	if on != "SET IDENTITY_INSERT [dbo].[orders] ON" {
		t.Fatalf("on: %s", on)
	}
	if off != "SET IDENTITY_INSERT [dbo].[orders] OFF" {
		t.Fatalf("off: %s", off)
	}
}

func TestBuildSQLServerIntegerRangeSelectLiteralUsesDecimalKeys(t *testing.T) {
	sql := extractport.BuildSQLServerIntegerRangeSelectLiteral(
		"Sales", "dbo", "orders", "id", []string{"id"}, 10, 20,
	)
	want := "SELECT [id] FROM [Sales].[dbo].[orders] WHERE [id] >= 10 AND [id] <= 20 ORDER BY [id]"
	if sql != want {
		t.Fatalf("got %s", sql)
	}
	if strings.Contains(sql, "'") || strings.Contains(sql, "@") {
		t.Fatal("literal integer range must not quote numbers or use parameters")
	}
}

func TestBuildSQLServerDiscoverPrimaryKeyQuery(t *testing.T) {
	sql := extractport.BuildSQLServerDiscoverPrimaryKeyQuery()
	if !strings.Contains(sql, "i.is_primary_key = 1") {
		t.Fatalf("expected PK catalog query, got %s", sql)
	}
	if !strings.Contains(sql, "@P1") || !strings.Contains(sql, "@P2") {
		t.Fatal("schema/table must be parameters")
	}
}
