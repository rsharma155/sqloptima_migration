// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import "testing"

func TestSameSQLServerInstance(t *testing.T) {
	a := &sqlServerEndpoint{Host: "db01", Port: 1433, Database: "src"}
	b := &sqlServerEndpoint{Host: "DB01", Port: 1433, Database: "tgt"}
	if !SameSQLServerInstance(a, b) {
		t.Fatal("same host:port must be treated as one instance")
	}
	c := &sqlServerEndpoint{Host: "db01", Port: 1434, Database: "tgt"}
	if SameSQLServerInstance(a, c) {
		t.Fatal("different port is a different instance")
	}
}

func TestSelectMSSQLCopyMode(t *testing.T) {
	offload := DefaultFileOffloadSettings()
	if got := SelectMSSQLCopyMode(true, offload, 10_000_000, 4000); got != MSSQLCopyInsertSelect {
		t.Fatalf("same server must INSERT…SELECT, got %s", got)
	}
	if got := SelectMSSQLCopyMode(false, offload, 2_000_000, 10); got != MSSQLCopyBCPNative {
		t.Fatalf("large cross-server must BCP, got %s", got)
	}
	if got := SelectMSSQLCopyMode(false, offload, 500, 1); got != MSSQLCopyStreamBulk {
		t.Fatalf("small cross-server must stream, got %s", got)
	}
	disabled := offload
	disabled.Enabled = false
	if got := SelectMSSQLCopyMode(false, disabled, 10_000_000, 4000); got != MSSQLCopyStreamBulk {
		t.Fatalf("disabled offload must stream, got %s", got)
	}
}

func TestNextIntegerRangeAdvancesAndStops(t *testing.T) {
	lo, hi, done := NextIntegerRange(1, 25, 10)
	if done || lo != 1 || hi != 10 {
		t.Fatalf("first range = %d-%d done=%v", lo, hi, done)
	}
	current := hi + 1
	lo, hi, done = NextIntegerRange(current, 25, 10)
	if done || lo != 11 || hi != 20 {
		t.Fatalf("second range = %d-%d done=%v", lo, hi, done)
	}
	current = hi + 1
	lo, hi, done = NextIntegerRange(current, 25, 10)
	if done || lo != 21 || hi != 25 {
		t.Fatalf("last range = %d-%d done=%v", lo, hi, done)
	}
	current = hi + 1
	_, _, done = NextIntegerRange(current, 25, 10)
	if !done {
		t.Fatal("must stop after max")
	}
}

func TestNextIntegerRangeRejectsInvertedBounds(t *testing.T) {
	_, _, done := NextIntegerRange(20, 10, 10)
	if !done {
		t.Fatal("rangeEnd < current must stop")
	}
}

func TestHeapCopyPolicy(t *testing.T) {
	if err := HeapCopyPolicy("", 50, 100); err != nil {
		t.Fatalf("small heap one-shot should be allowed: %v", err)
	}
	if err := HeapCopyPolicy("", 5_000, 100); err == nil {
		t.Fatal("large heap without order column must fail")
	}
	if err := HeapCopyPolicy("id", 5_000, 100); err != nil {
		t.Fatalf("ordered table must be allowed: %v", err)
	}
}

func TestMaxCopyItersIsFinite(t *testing.T) {
	n := MaxCopyIters(10_000_000, 10_000)
	if n < 1000 || n > 1_000_000 {
		t.Fatalf("unexpected cap %d", n)
	}
	if MaxCopyIters(10, 10_000) < 8 {
		t.Fatal("small tables still need a few iterations")
	}
}

func TestBCPServerAddrAndDest(t *testing.T) {
	if got := bcpServerAddr("db01", 1433); got != "db01,1433" {
		t.Fatalf("got %s", got)
	}
	if got := bcpDestName("Sales", "dbo", "orders"); got != "Sales.dbo.orders" {
		t.Fatalf("got %s", got)
	}
}

func TestShouldSkipInsertOnlyDelta(t *testing.T) {
	if !ShouldSkipInsertOnlyDelta(true, true, 0) {
		t.Fatal("target max >= source max should skip")
	}
	if ShouldSkipInsertOnlyDelta(true, false, -1) {
		t.Fatal("target behind source must copy")
	}
	if ShouldSkipInsertOnlyDelta(false, false, 0) {
		t.Fatal("empty target must copy")
	}
}
