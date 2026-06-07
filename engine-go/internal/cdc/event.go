// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc

import (
	"fmt"
	"sort"
)

// CDCEvent is a single change captured from a cdc.<capture>_CT table.
//
// CommitLSN drives the checkpoint watermark; SeqVal orders changes that share
// a commit LSN within the same transaction. Together they provide a total order
// that is stable across process restarts.
type CDCEvent struct {
	StartLSN  LSN
	CommitLSN LSN
	SeqVal    LSN // __$seqval — intra-transaction sequence
	Operation CDCOperation
	Schema    string
	Table     string
	// Columns holds the change values keyed by column name. Populated by the
	// I/O layer after reading the capture-table row; may be nil for events used
	// in pure planning/ordering tests.
	Columns map[string]interface{}
}

// IsApplicable reports whether this event should be applied to the target.
func (e *CDCEvent) IsApplicable() bool { return e.Operation.IsApplicable() }

// QualifiedTable returns "schema.table".
func (e *CDCEvent) QualifiedTable() string { return fmt.Sprintf("%s.%s", e.Schema, e.Table) }

// OrderForApply sorts events into the order they must be applied: by commit
// LSN, then by intra-transaction sequence value. This guarantees deterministic,
// correct replay even when a batch spans multiple transactions.
func OrderForApply(events []*CDCEvent) {
	sort.SliceStable(events, func(i, j int) bool {
		cmp := events[i].CommitLSN.Compare(events[j].CommitLSN)
		if cmp != 0 {
			return cmp < 0
		}
		return events[i].SeqVal.Less(events[j].SeqVal)
	})
}
