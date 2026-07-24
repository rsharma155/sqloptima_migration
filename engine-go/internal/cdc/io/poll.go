// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/poll.go
// Purpose: CDC poll/apply loop driving the domain state machine via ports
// Domain: Replication / CDC (data plane application service)
// Author: Ravi Sharma

package cdcio

import (
	"context"
	"time"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

// PollLoopConfig configures a single-table CDC poll/apply loop.
type PollLoopConfig struct {
	Schema          string
	Table           string
	CaptureInstance string
	Columns         []string
	PKColumns       []string
	TargetSchema    string
	TargetTable     string
	PollInterval    time.Duration
	BatchSize       int
	OnCheckpoint    func(ctx context.Context, lsn cdc.LSN) error
	OnLag           func(ctx context.Context, lagHint int64)
}

// RunPollLoop drives the CDC state machine through snapshot → catch-up →
// streaming, reading via EventSource and applying via EventApplier until ctx
// is cancelled. Snapshot content itself is owned by the Python control plane;
// this loop only advances through the legal SNAPSHOTTING state.
func RunPollLoop(
	ctx context.Context,
	sm *cdc.CDCStateMachine,
	reader EventSource,
	writer EventApplier,
	cfg PollLoopConfig,
) error {
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = time.Second
	}
	if cfg.BatchSize <= 0 {
		cfg.BatchSize = 1000
	}
	targetSchema := cfg.TargetSchema
	if targetSchema == "" {
		targetSchema = "public"
	}
	targetTable := cfg.TargetTable
	if targetTable == "" {
		targetTable = cfg.Table
	}

	if err := sm.TransitionTo(cdc.StateStarting); err != nil {
		return err
	}
	if err := sm.TransitionTo(cdc.StateSnapshotting); err != nil {
		return err
	}
	if err := sm.TransitionTo(cdc.StateCDCCatchup); err != nil {
		return err
	}

	checkpoint := cdc.ZeroLSN
	ticker := time.NewTicker(cfg.PollInterval)
	defer ticker.Stop()

	first := true
	for {
		if first {
			first = false
		} else {
			select {
			case <-ctx.Done():
				_ = sm.TransitionTo(cdc.StateStopping)
				_ = sm.TransitionTo(cdc.StateCompleted)
				return ctx.Err()
			case <-ticker.C:
			}
		}

		events, err := reader.ReadAfter(
			ctx, cfg.Schema, cfg.Table, cfg.CaptureInstance,
			checkpoint, cfg.Columns, cfg.BatchSize,
		)
		if err != nil {
			_ = sm.TransitionTo(cdc.StateFailed)
			return err
		}

		applied := 0
		for _, ev := range events {
			if !ev.IsApplicable() {
				checkpoint = ev.CommitLSN
				continue
			}
			if err := writer.Apply(ctx, targetSchema, targetTable, ev, cfg.Columns, cfg.PKColumns); err != nil {
				_ = sm.TransitionTo(cdc.StateFailed)
				return err
			}
			checkpoint = ev.CommitLSN
			applied++
		}

		if cfg.OnCheckpoint != nil && !checkpoint.IsZero() {
			if err := cfg.OnCheckpoint(ctx, checkpoint); err != nil {
				_ = sm.TransitionTo(cdc.StateFailed)
				return err
			}
		}

		if sm.State() == cdc.StateCDCCatchup && applied < cfg.BatchSize {
			if err := sm.TransitionTo(cdc.StateCDCStreaming); err != nil {
				return err
			}
		}

		if cfg.OnLag != nil {
			maxLSN, err := reader.MaxLSN(ctx)
			if err == nil && !maxLSN.IsZero() && !checkpoint.IsZero() {
				cfg.OnLag(ctx, int64(maxLSN.Compare(checkpoint)))
			}
		}
	}
}
