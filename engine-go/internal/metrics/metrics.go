// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metrics

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
)

// EngineMetrics is the central registry for all migration-engine OTEL metrics.
// Create once at startup and share via pointer.
//
// All metrics use the "migration.*" namespace for easy filtering in
// Prometheus / Grafana dashboards.
type EngineMetrics struct {
	rowsExtracted metric.Int64Counter
	rowsLoaded    metric.Int64Counter
	chunkDuration metric.Float64Histogram
	activeWorkers metric.Int64Gauge
	queueDepth    metric.Int64Gauge
	cdcLagMs      metric.Int64Gauge
}

// New creates and registers all engine metrics against the global MeterProvider.
func New() (*EngineMetrics, error) {
	m := otel.Meter("migration-engine")
	em := &EngineMetrics{}
	var err error

	if em.rowsExtracted, err = m.Int64Counter(
		"migration.rows_extracted_total",
		metric.WithDescription("Total rows extracted from the SQL Server source"),
	); err != nil {
		return nil, fmt.Errorf("create rows_extracted counter: %w", err)
	}

	if em.rowsLoaded, err = m.Int64Counter(
		"migration.rows_loaded_total",
		metric.WithDescription("Total rows loaded into the PostgreSQL target"),
	); err != nil {
		return nil, fmt.Errorf("create rows_loaded counter: %w", err)
	}

	if em.chunkDuration, err = m.Float64Histogram(
		"migration.chunk_duration_seconds",
		metric.WithDescription("Extraction + loading duration per chunk"),
	); err != nil {
		return nil, fmt.Errorf("create chunk_duration histogram: %w", err)
	}

	if em.activeWorkers, err = m.Int64Gauge(
		"migration.active_workers",
		metric.WithDescription("Number of active extractor or loader goroutines"),
	); err != nil {
		return nil, fmt.Errorf("create active_workers gauge: %w", err)
	}

	if em.queueDepth, err = m.Int64Gauge(
		"migration.queue_depth",
		metric.WithDescription("Number of chunks in PENDING or EXTRACTED state"),
	); err != nil {
		return nil, fmt.Errorf("create queue_depth gauge: %w", err)
	}

	if em.cdcLagMs, err = m.Int64Gauge(
		"migration.cdc_lag_milliseconds",
		metric.WithDescription("CDC lag between the source LSN and the applied LSN"),
	); err != nil {
		return nil, fmt.Errorf("create cdc_lag gauge: %w", err)
	}

	return em, nil
}

// ---------------------------------------------------------------------------
// Attribute helpers
// ---------------------------------------------------------------------------

func jobAttr(id uuid.UUID) attribute.KeyValue   { return attribute.String("job_id", id.String()) }
func tableAttr(t string) attribute.KeyValue     { return attribute.String("table", t) }
func phaseAttr(p string) attribute.KeyValue     { return attribute.String("phase", p) }
func workerTypeAttr(k string) attribute.KeyValue { return attribute.String("type", k) }
func statusAttr(s string) attribute.KeyValue    { return attribute.String("status", s) }

// ---------------------------------------------------------------------------
// Recording helpers
// ---------------------------------------------------------------------------

// RecordRowsExtracted increments the rows_extracted counter.
func (e *EngineMetrics) RecordRowsExtracted(ctx context.Context, jobID uuid.UUID, table string, n int64) {
	e.rowsExtracted.Add(ctx, n, metric.WithAttributes(jobAttr(jobID), tableAttr(table)))
}

// RecordRowsLoaded increments the rows_loaded counter.
func (e *EngineMetrics) RecordRowsLoaded(ctx context.Context, jobID uuid.UUID, table string, n int64) {
	e.rowsLoaded.Add(ctx, n, metric.WithAttributes(jobAttr(jobID), tableAttr(table)))
}

// RecordChunkDuration records a chunk extraction+load duration in seconds.
func (e *EngineMetrics) RecordChunkDuration(ctx context.Context, jobID uuid.UUID, phase string, secs float64) {
	e.chunkDuration.Record(ctx, secs, metric.WithAttributes(jobAttr(jobID), phaseAttr(phase)))
}

// SetActiveWorkers sets the active-worker gauge for a worker type.
func (e *EngineMetrics) SetActiveWorkers(ctx context.Context, jobID uuid.UUID, kind string, count int64) {
	e.activeWorkers.Record(ctx, count, metric.WithAttributes(jobAttr(jobID), workerTypeAttr(kind)))
}

// SetQueueDepth sets the queue-depth gauge for a chunk status.
func (e *EngineMetrics) SetQueueDepth(ctx context.Context, jobID uuid.UUID, status string, depth int64) {
	e.queueDepth.Record(ctx, depth, metric.WithAttributes(jobAttr(jobID), statusAttr(status)))
}

// SetCDCLag sets the CDC lag gauge.
func (e *EngineMetrics) SetCDCLag(ctx context.Context, jobID uuid.UUID, lagMs int64) {
	e.cdcLagMs.Record(ctx, lagMs, metric.WithAttributes(jobAttr(jobID)))
}
