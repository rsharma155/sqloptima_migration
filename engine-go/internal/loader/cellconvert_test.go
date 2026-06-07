// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
)

// pgEpochDays is the offset the loader applies when converting CellDate to CopyDate.
// Unix epoch: 1970-01-01; PostgreSQL epoch: 2000-01-01; offset = 10957 days.
const pgEpochDays int32 = 10957

// pgEpochMicros is pgEpochDays expressed in microseconds.
const pgEpochMicros int64 = int64(pgEpochDays) * 24 * 3600 * 1_000_000

func TestNullConverts(t *testing.T) {
	v := loader.ToCopyValue(core.CellNull{})
	if _, ok := v.(loader.CopyNull); !ok {
		t.Errorf("CellNull must convert to CopyNull, got %T", v)
	}
}

func TestBoolConverts(t *testing.T) {
	if _, ok := loader.ToCopyValue(core.CellBool{V: true}).(loader.CopyBool); !ok {
		t.Error("CellBool must convert to CopyBool")
	}
}

func TestIntConverts(t *testing.T) {
	if _, ok := loader.ToCopyValue(core.CellI16{V: 42}).(loader.CopyInt16); !ok {
		t.Error("CellI16 must convert to CopyInt16")
	}
	if _, ok := loader.ToCopyValue(core.CellI32{V: 1}).(loader.CopyInt32); !ok {
		t.Error("CellI32 must convert to CopyInt32")
	}
	if _, ok := loader.ToCopyValue(core.CellI64{V: 1}).(loader.CopyInt64); !ok {
		t.Error("CellI64 must convert to CopyInt64")
	}
}

func TestFloatConverts(t *testing.T) {
	if _, ok := loader.ToCopyValue(core.CellF32{V: 1.5}).(loader.CopyFloat32); !ok {
		t.Error("CellF32 must convert to CopyFloat32")
	}
	if _, ok := loader.ToCopyValue(core.CellF64{V: 2.5}).(loader.CopyFloat64); !ok {
		t.Error("CellF64 must convert to CopyFloat64")
	}
}

func TestStrConverts(t *testing.T) {
	v := loader.ToCopyValue(core.CellStr{V: "hello"})
	cv, ok := v.(loader.CopyText)
	if !ok {
		t.Fatalf("CellStr must convert to CopyText, got %T", v)
	}
	if cv.V != "hello" {
		t.Errorf("CopyText.V = %q, want %q", cv.V, "hello")
	}
}

func TestBinConverts(t *testing.T) {
	if _, ok := loader.ToCopyValue(core.CellBin{V: []byte{1, 2}}).(loader.CopyBytes); !ok {
		t.Error("CellBin must convert to CopyBytes")
	}
}

// TestDateEpochShift is the critical correctness test for the Unix→PostgreSQL epoch
// conversion. The extractor stores days since 1970-01-01; the loader must shift
// by -10957 to produce days since 2000-01-01 for PostgreSQL.
func TestDateEpochShift(t *testing.T) {
	// Unix day 10957 = 2000-01-01 in Unix epoch → must become day 0 in PG epoch.
	unixDay2000 := int32(10957)
	v := loader.ToCopyValue(core.CellDate{V: unixDay2000})
	cd, ok := v.(loader.CopyDate)
	if !ok {
		t.Fatalf("CellDate must convert to CopyDate, got %T", v)
	}
	if cd.V != 0 {
		t.Errorf("2000-01-01 (Unix day 10957) must map to PG day 0, got %d", cd.V)
	}
}

func TestDateEpochShiftNegative(t *testing.T) {
	// Unix day 0 = 1970-01-01 → must become -10957 in PG epoch.
	v := loader.ToCopyValue(core.CellDate{V: 0})
	cd, ok := v.(loader.CopyDate)
	if !ok {
		t.Fatalf("CellDate must convert to CopyDate, got %T", v)
	}
	if cd.V != -pgEpochDays {
		t.Errorf("1970-01-01 (Unix day 0) must map to PG day -%d, got %d", pgEpochDays, cd.V)
	}
}

// TestTimestampEpochShift verifies the microsecond-precision epoch shift.
func TestTimestampEpochShift(t *testing.T) {
	// Unix microseconds for 2000-01-01 00:00:00 UTC = pgEpochMicros
	// That must map to PG epoch microsecond 0.
	v := loader.ToCopyValue(core.CellTimestampMicros{V: pgEpochMicros})
	ct, ok := v.(loader.CopyTimestampMicros)
	if !ok {
		t.Fatalf("CellTimestampMicros must convert to CopyTimestampMicros, got %T", v)
	}
	if ct.V != 0 {
		t.Errorf("2000-01-01 00:00:00 must map to PG epoch microsecond 0, got %d", ct.V)
	}
}

func TestTimestampUnixEpochMapsToNegative(t *testing.T) {
	// Unix microseconds 0 = 1970-01-01 00:00:00 UTC → must be negative in PG epoch.
	v := loader.ToCopyValue(core.CellTimestampMicros{V: 0})
	ct, ok := v.(loader.CopyTimestampMicros)
	if !ok {
		t.Fatalf("CellTimestampMicros must convert to CopyTimestampMicros, got %T", v)
	}
	if ct.V != -pgEpochMicros {
		t.Errorf("1970-01-01 00:00:00 must map to -%d µs, got %d", pgEpochMicros, ct.V)
	}
}

func TestTimeMicrosConverts(t *testing.T) {
	micros := int64(3_600_000_000) // 01:00:00
	v := loader.ToCopyValue(core.CellTimeMicros{V: micros})
	ct, ok := v.(loader.CopyTimeMicros)
	if !ok {
		t.Fatalf("CellTimeMicros must convert to CopyTimeMicros, got %T", v)
	}
	if ct.V != micros {
		t.Errorf("time micros = %d, want %d", ct.V, micros)
	}
}

func TestUUIDConverts(t *testing.T) {
	var arr [16]byte
	for i := range arr {
		arr[i] = byte(i)
	}
	v := loader.ToCopyValue(core.CellUUID{V: arr})
	cu, ok := v.(loader.CopyUUID)
	if !ok {
		t.Fatalf("CellUUID must convert to CopyUUID, got %T", v)
	}
	if cu.V != arr {
		t.Error("UUID bytes must be preserved exactly")
	}
}
