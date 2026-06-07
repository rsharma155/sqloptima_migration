// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"sort"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func lsn(last byte) cdc.LSN {
	return cdc.LSNFromBytes([10]byte{0, 0, 0, 0, 0, 0, 0, 0, 0, last})
}

func TestZeroIsSmallest(t *testing.T) {
	any := lsn(1)
	if !cdc.ZeroLSN.Less(any) {
		t.Error("ZeroLSN must be less than any non-zero LSN")
	}
	if !cdc.ZeroLSN.IsZero() {
		t.Error("ZeroLSN.IsZero() must be true")
	}
	if any.IsZero() {
		t.Error("non-zero LSN.IsZero() must be false")
	}
}

func TestByteOrderGivesChronologicalOrder(t *testing.T) {
	earlier := cdc.LSNFromBytes([10]byte{0, 0, 0, 0, 0, 0, 0, 0, 0, 5})
	later := cdc.LSNFromBytes([10]byte{0, 0, 0, 0, 0, 0, 0, 0, 1, 0})
	if !earlier.Less(later) {
		t.Error("earlier LSN must be less than later LSN")
	}
}

func TestHighByteDominatesOrdering(t *testing.T) {
	a := cdc.LSNFromBytes([10]byte{1, 0, 0, 0, 0, 0, 0, 0, 0, 0})
	b := cdc.LSNFromBytes([10]byte{0, 255, 255, 255, 255, 255, 255, 255, 255, 255})
	if !b.Less(a) {
		t.Error("leading byte 1 must dominate all lower bytes 255")
	}
}

func TestHexRoundtrip(t *testing.T) {
	raw := [10]byte{0x00, 0x00, 0x00, 0x2a, 0x00, 0x00, 0x01, 0x05, 0x00, 0x03}
	original := cdc.LSNFromBytes(raw)
	hex := original.ToHex()
	if len(hex) != 20 {
		t.Fatalf("hex length = %d, want 20", len(hex))
	}
	roundtripped, ok := cdc.LSNFromHex(hex)
	if !ok || roundtripped != original {
		t.Error("hex roundtrip failed")
	}
}

func TestFromHexAccepts0xPrefix(t *testing.T) {
	a, okA := cdc.LSNFromHex("0x0000000000000000000a")
	b, okB := cdc.LSNFromHex("0000000000000000000a")
	if !okA || !okB || a != b {
		t.Error("0x-prefixed and bare hex must produce the same LSN")
	}
}

func TestFromHexRejectsWrongLength(t *testing.T) {
	for _, bad := range []string{"00", "", "zz0000000000000000gg"} {
		if _, ok := cdc.LSNFromHex(bad); ok {
			t.Errorf("LSNFromHex(%q) must fail", bad)
		}
	}
}

func TestDisplayHas0xPrefix(t *testing.T) {
	l := lsn(10)
	if got := l.String(); got[:2] != "0x" {
		t.Errorf("String() = %q, must start with 0x", got)
	}
}

func TestSortingBatchOfLSNs(t *testing.T) {
	lsns := []cdc.LSN{lsn(3), lsn(1), lsn(2)}
	sort.Slice(lsns, func(i, j int) bool { return lsns[i].Less(lsns[j]) })
	if lsns[0] != lsn(1) || lsns[1] != lsn(2) || lsns[2] != lsn(3) {
		t.Error("sorting LSNs produced wrong order")
	}
}
