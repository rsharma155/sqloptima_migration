// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metrics_test

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/metrics"
)

func TestMetricsInstantiateWithoutPanic(t *testing.T) {
	// The global OTel provider is the no-op provider at this point (no InitProvider
	// call). Verify that New() succeeds and all metric instruments are created.
	m, err := metrics.New()
	if err != nil {
		t.Fatalf("metrics.New() unexpected error: %v", err)
	}
	if m == nil {
		t.Fatal("metrics.New() returned nil")
	}
}

func TestMetricsRecordingDoesNotPanic(t *testing.T) {
	m, err := metrics.New()
	if err != nil {
		t.Fatalf("metrics.New(): %v", err)
	}
	ctx := context.Background()
	jobID := uuid.New()

	// All recording helpers must be callable against the no-op provider without
	// panicking. This validates method signatures and attribute construction.
	m.RecordRowsExtracted(ctx, jobID, "dbo.orders", 1000)
	m.RecordRowsLoaded(ctx, jobID, "dbo.orders", 1000)
	m.RecordChunkDuration(ctx, jobID, "extract", 1.5)
	m.SetActiveWorkers(ctx, jobID, "extractor", 4)
	m.SetQueueDepth(ctx, jobID, "PENDING", 12)
	m.SetCDCLag(ctx, jobID, 250)
}
