// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/ports_test.go
// Purpose: TDD — CDC I/O ports and poll-loop behaviour without live databases
// Domain: Replication / CDC (data plane)
// Author: Ravi Sharma

package cdcio_test

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
	cdcio "github.com/ravisharma/sql-optima/engine-go/internal/cdc/io"
)

// fakeSource implements EventSource for deterministic unit tests.
type fakeSource struct {
	batches [][]*cdc.CDCEvent
	calls   int
	maxLSN  cdc.LSN
	err     error
}

func (f *fakeSource) ReadAfter(
	_ context.Context,
	_, _, _ string,
	_ cdc.LSN,
	_ []string,
	_ int,
) ([]*cdc.CDCEvent, error) {
	if f.err != nil {
		return nil, f.err
	}
	if f.calls >= len(f.batches) {
		return nil, nil
	}
	batch := f.batches[f.calls]
	f.calls++
	return batch, nil
}

func (f *fakeSource) MaxLSN(context.Context) (cdc.LSN, error) {
	return f.maxLSN, nil
}

type fakeApplier struct {
	applied int32
	failAt  int32
}

func (a *fakeApplier) Apply(
	_ context.Context,
	_, _ string,
	_ *cdc.CDCEvent,
	_, _ []string,
) error {
	n := atomic.AddInt32(&a.applied, 1)
	if a.failAt > 0 && n == a.failAt {
		return errors.New("apply failed")
	}
	return nil
}

func lsn(b byte) cdc.LSN {
	var out cdc.LSN
	out[9] = b
	return out
}

func TestRunPollLoop_AppliesInsertAndAdvancesCheckpoint(t *testing.T) {
	ev := &cdc.CDCEvent{
		StartLSN:  lsn(1),
		CommitLSN: lsn(1),
		SeqVal:    lsn(1),
		Operation: cdc.OpInsert,
		Schema:    "dbo",
		Table:     "orders",
		Columns:   map[string]interface{}{"id": 1},
	}
	src := &fakeSource{
		batches: [][]*cdc.CDCEvent{{ev}, nil},
		maxLSN:  lsn(9),
	}
	app := &fakeApplier{}
	sm := cdc.NewCDCStateMachine()

	ctx, cancel := context.WithCancel(context.Background())
	var gotCheckpoint cdc.LSN
	go func() {
		// Cancel after the loop has a chance to process the first batch.
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()

	err := cdcio.RunPollLoop(ctx, sm, src, app, cdcio.PollLoopConfig{
		Schema:          "dbo",
		Table:           "orders",
		CaptureInstance: "dbo_orders",
		Columns:         []string{"id"},
		PKColumns:       []string{"id"},
		PollInterval:    10 * time.Millisecond,
		BatchSize:       100,
		OnCheckpoint: func(_ context.Context, l cdc.LSN) error {
			gotCheckpoint = l
			return nil
		},
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
	if atomic.LoadInt32(&app.applied) < 1 {
		t.Fatalf("expected at least one apply, got %d", app.applied)
	}
	if gotCheckpoint != lsn(1) {
		t.Fatalf("checkpoint = %v, want %v", gotCheckpoint, lsn(1))
	}
	if sm.State() != cdc.StateCompleted && sm.State() != cdc.StateCDCStreaming {
		// After cancel we should be Completed; mid-stream cancel also OK if Completed.
		if sm.State() != cdc.StateCompleted {
			t.Fatalf("unexpected terminal state %s", sm.State())
		}
	}
}

func TestRunPollLoop_SkipsUpdateBefore(t *testing.T) {
	before := &cdc.CDCEvent{
		StartLSN: lsn(2), CommitLSN: lsn(2), SeqVal: lsn(1),
		Operation: cdc.OpUpdateBefore, Columns: map[string]interface{}{"id": 1},
	}
	after := &cdc.CDCEvent{
		StartLSN: lsn(2), CommitLSN: lsn(2), SeqVal: lsn(2),
		Operation: cdc.OpUpdateAfter, Columns: map[string]interface{}{"id": 1, "n": "x"},
	}
	src := &fakeSource{batches: [][]*cdc.CDCEvent{{before, after}}}
	app := &fakeApplier{}
	sm := cdc.NewCDCStateMachine()
	ctx, cancel := context.WithTimeout(context.Background(), 80*time.Millisecond)
	defer cancel()

	_ = cdcio.RunPollLoop(ctx, sm, src, app, cdcio.PollLoopConfig{
		Schema: "dbo", Table: "t", CaptureInstance: "dbo_t",
		Columns: []string{"id", "n"}, PKColumns: []string{"id"},
		PollInterval: 5 * time.Millisecond, BatchSize: 10,
	})
	if atomic.LoadInt32(&app.applied) != 1 {
		t.Fatalf("UPDATE-before must be skipped; applied=%d", app.applied)
	}
}

func TestRunPollLoop_ApplyErrorTransitionsToFailed(t *testing.T) {
	ev := &cdc.CDCEvent{
		StartLSN: lsn(3), CommitLSN: lsn(3), SeqVal: lsn(1),
		Operation: cdc.OpDelete, Columns: map[string]interface{}{"id": 9},
	}
	src := &fakeSource{batches: [][]*cdc.CDCEvent{{ev}}}
	app := &fakeApplier{failAt: 1}
	sm := cdc.NewCDCStateMachine()

	err := cdcio.RunPollLoop(context.Background(), sm, src, app, cdcio.PollLoopConfig{
		Schema: "dbo", Table: "t", CaptureInstance: "dbo_t",
		Columns: []string{"id"}, PKColumns: []string{"id"},
		PollInterval: time.Millisecond, BatchSize: 10,
	})
	if err == nil {
		t.Fatal("expected apply error")
	}
	if sm.State() != cdc.StateFailed {
		t.Fatalf("state=%s want FAILED", sm.State())
	}
}

func TestRowToEvent_MapsOperationAndColumns(t *testing.T) {
	start := []byte{0, 0, 0, 0, 0, 0, 0, 0, 0, 5}
	seq := []byte{0, 0, 0, 0, 0, 0, 0, 0, 0, 1}
	ev, err := cdcio.RowToEventForTest(
		"dbo", "orders",
		[]string{"__$start_lsn", "__$seqval", "__$operation", "__$update_mask", "id", "amount"},
		[]interface{}{start, seq, int64(2), []byte{0xff}, int64(42), "10.00"},
	)
	if err != nil {
		t.Fatal(err)
	}
	if ev.Operation != cdc.OpInsert {
		t.Fatalf("op=%v", ev.Operation)
	}
	if ev.Columns["id"] != int64(42) {
		t.Fatalf("id=%v", ev.Columns["id"])
	}
	if _, ok := ev.Columns["__$update_mask"]; ok {
		t.Fatal("meta columns must not appear in Columns")
	}
	if ev.CommitLSN[9] != 5 {
		t.Fatalf("commit LSN byte = %d", ev.CommitLSN[9])
	}
}

func TestLoadEnvWorkerConfig_DisabledByDefault(t *testing.T) {
	t.Setenv("MIGRATION_CDC_ENABLED", "")
	cfg := cdcio.LoadEnvWorkerConfig()
	if cfg.Enabled {
		t.Fatal("expected disabled when env unset")
	}
}

func TestLoadEnvWorkerConfig_ParsesColumns(t *testing.T) {
	t.Setenv("MIGRATION_CDC_ENABLED", "1")
	t.Setenv("MIGRATION_CDC_COLUMNS", "id, name , amount")
	t.Setenv("MIGRATION_CDC_PK_COLUMNS", "id")
	t.Setenv("MIGRATION_CDC_TABLE", "orders")
	t.Setenv("MIGRATION_CDC_SCHEMA", "dbo")
	t.Setenv("MIGRATION_CDC_CAPTURE_INSTANCE", "")
	cfg := cdcio.LoadEnvWorkerConfig()
	if !cfg.Enabled {
		t.Fatal("expected enabled")
	}
	if len(cfg.Columns) != 3 || cfg.Columns[1] != "name" {
		t.Fatalf("columns=%v", cfg.Columns)
	}
	if cfg.CaptureInstance != "dbo_orders" {
		t.Fatalf("expected default capture instance dbo_orders, got %q", cfg.CaptureInstance)
	}
}
