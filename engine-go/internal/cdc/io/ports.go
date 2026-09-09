// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/ports.go
// Purpose: Hexagonal ports for CDC capture (source) and apply (target)
// Domain: Replication / CDC (data plane)
// Author: Ravi Sharma

package cdcio

import (
	"context"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

// EventSource is the outbound port for reading CDC change rows from SQL Server.
// Implementations must never interpolate LSN values into SQL — use @P1 only.
type EventSource interface {
	ReadAfter(
		ctx context.Context,
		schema, table, captureInstance string,
		after cdc.LSN,
		columns []string,
		limit int,
	) ([]*cdc.CDCEvent, error)
	MaxLSN(ctx context.Context) (cdc.LSN, error)
}

// EventApplier is the outbound port for applying a single CDC event to PostgreSQL.
// Implementations must use parameterised DML from cdc.BuildApplyStatement.
type EventApplier interface {
	Apply(
		ctx context.Context,
		schema, table string,
		ev *cdc.CDCEvent,
		columns, pkColumns []string,
	) error
}

// Compile-time checks that concrete adapters satisfy the ports.
var (
	_ EventSource  = (*CaptureReader)(nil)
	_ EventApplier = (*ApplyWriter)(nil)
)
