// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestIntegerFamilyMapsCorrectly(t *testing.T) {
	cases := []struct {
		typeName string
		maxLen   int32
		want     core.LogicalType
	}{
		{"bit", 1, core.LogicalBool},
		{"tinyint", 1, core.LogicalInt16},
		{"smallint", 2, core.LogicalInt16},
		{"int", 4, core.LogicalInt32},
		{"bigint", 8, core.LogicalInt64},
	}
	for _, tc := range cases {
		got := core.MapSQLServerType(tc.typeName, tc.maxLen)
		if got != tc.want {
			t.Errorf("MapSQLServerType(%q,%d) = %v, want %v", tc.typeName, tc.maxLen, got, tc.want)
		}
	}
}

func TestCaseInsensitiveAndSuffixTolerant(t *testing.T) {
	if core.MapSQLServerType("INT", 4) != core.LogicalInt32 {
		t.Error("uppercase INT must map to Int32")
	}
	if core.MapSQLServerType("Decimal(18,2)", 9) != core.LogicalDecimal {
		t.Error("Decimal(18,2) with suffix must map to Decimal")
	}
	if core.MapSQLServerType("  varchar(50) ", 50) != core.LogicalUtf8 {
		t.Error("padded varchar(50) must map to Utf8")
	}
}

func TestVarcharMaxIsLargeUtf8(t *testing.T) {
	if core.MapSQLServerType("varchar", -1) != core.LogicalLargeUtf8 {
		t.Error("varchar(max) must be LargeUtf8")
	}
	if core.MapSQLServerType("nvarchar", -1) != core.LogicalLargeUtf8 {
		t.Error("nvarchar(max) must be LargeUtf8")
	}
	if core.MapSQLServerType("varchar", 255) != core.LogicalUtf8 {
		t.Error("varchar(255) must be Utf8")
	}
}

func TestVarbinaryMaxIsLargeBinary(t *testing.T) {
	if core.MapSQLServerType("varbinary", -1) != core.LogicalLargeBinary {
		t.Error("varbinary(max) must be LargeBinary")
	}
	if core.MapSQLServerType("varbinary", 16) != core.LogicalBinary {
		t.Error("varbinary(16) must be Binary")
	}
	if core.MapSQLServerType("image", 16) != core.LogicalLargeBinary {
		t.Error("image must be LargeBinary")
	}
}

func TestTemporalTypes(t *testing.T) {
	cases := []struct {
		name string
		want core.LogicalType
	}{
		{"date", core.LogicalDate},
		{"time", core.LogicalTime},
		{"datetime", core.LogicalTimestamp},
		{"datetime2", core.LogicalTimestamp},
		{"smalldatetime", core.LogicalTimestamp},
		{"datetimeoffset", core.LogicalTimestampTz},
	}
	for _, tc := range cases {
		if got := core.MapSQLServerType(tc.name, 8); got != tc.want {
			t.Errorf("MapSQLServerType(%q) = %v, want %v", tc.name, got, tc.want)
		}
	}
}

func TestUUIDAndMoney(t *testing.T) {
	if core.MapSQLServerType("uniqueidentifier", 16) != core.LogicalUUID {
		t.Error("uniqueidentifier must map to UUID")
	}
	if core.MapSQLServerType("money", 8) != core.LogicalDecimal {
		t.Error("money must map to Decimal")
	}
	if core.MapSQLServerType("smallmoney", 4) != core.LogicalDecimal {
		t.Error("smallmoney must map to Decimal")
	}
}

func TestUnsupportedTypesFlagged(t *testing.T) {
	for _, name := range []string{"hierarchyid", "geography", "geometry", "sql_variant"} {
		if got := core.MapSQLServerType(name, -1); got != core.LogicalUnsupported {
			t.Errorf("MapSQLServerType(%q) = %v, want Unsupported", name, got)
		}
		if !core.MapSQLServerType(name, -1).NeedsManualReview() {
			t.Errorf("%q must need manual review", name)
		}
	}
}

func TestPostgresTypeNames(t *testing.T) {
	cases := []struct {
		lt   core.LogicalType
		want string
	}{
		{core.LogicalInt32, "integer"},
		{core.LogicalBool, "boolean"},
		{core.LogicalTimestampTz, "timestamptz"},
		{core.LogicalUUID, "uuid"},
		{core.LogicalLargeUtf8, "text"},
		{core.LogicalLargeBinary, "bytea"},
	}
	for _, tc := range cases {
		if got := tc.lt.PostgresType(); got != tc.want {
			t.Errorf("%v.PostgresType() = %q, want %q", tc.lt, got, tc.want)
		}
	}
}

func TestLOBDetection(t *testing.T) {
	if !core.LogicalLargeUtf8.IsLOB() {
		t.Error("LargeUtf8 must be LOB")
	}
	if !core.LogicalLargeBinary.IsLOB() {
		t.Error("LargeBinary must be LOB")
	}
	if core.LogicalUtf8.IsLOB() {
		t.Error("Utf8 must not be LOB")
	}
	if core.LogicalInt32.IsLOB() {
		t.Error("Int32 must not be LOB")
	}
}
