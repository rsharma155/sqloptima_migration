// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func makeEvent(commit, seq byte, op cdc.CDCOperation) *cdc.CDCEvent {
	return &cdc.CDCEvent{
		StartLSN:  lsn(commit),
		CommitLSN: lsn(commit),
		SeqVal:    lsn(seq),
		Operation: op,
		Schema:    "dbo",
		Table:     "orders",
	}
}

func TestApplicableSkipsUpdateBefore(t *testing.T) {
	if makeEvent(1, 1, cdc.OpUpdateBefore).IsApplicable() {
		t.Error("UPDATE_BEFORE must not be applicable")
	}
	if !makeEvent(1, 1, cdc.OpInsert).IsApplicable() {
		t.Error("INSERT must be applicable")
	}
}

func TestQualifiedTableName(t *testing.T) {
	e := makeEvent(1, 1, cdc.OpInsert)
	if got := e.QualifiedTable(); got != "dbo.orders" {
		t.Errorf("QualifiedTable() = %q, want %q", got, "dbo.orders")
	}
}

func TestOrderForApplySortsByCommitThenSeq(t *testing.T) {
	events := []*cdc.CDCEvent{
		makeEvent(2, 1, cdc.OpInsert),
		makeEvent(1, 2, cdc.OpInsert),
		makeEvent(1, 1, cdc.OpInsert),
	}
	cdc.OrderForApply(events)

	// Expected order: commit=1,seq=1 → commit=1,seq=2 → commit=2,seq=1
	assertEvent(t, events[0], 1, 1)
	assertEvent(t, events[1], 1, 2)
	assertEvent(t, events[2], 2, 1)
}

func assertEvent(t *testing.T, e *cdc.CDCEvent, wantCommit, wantSeq byte) {
	t.Helper()
	if e.CommitLSN != lsn(wantCommit) || e.SeqVal != lsn(wantSeq) {
		t.Errorf("got event commit=%x seq=%x, want commit=%d seq=%d",
			e.CommitLSN[9], e.SeqVal[9], wantCommit, wantSeq)
	}
}

func TestOrderingIsStableForSingleEvent(t *testing.T) {
	events := []*cdc.CDCEvent{makeEvent(5, 5, cdc.OpDelete)}
	cdc.OrderForApply(events)
	if len(events) != 1 {
		t.Fatal("single event must remain after ordering")
	}
}
