// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/writer.go
// Purpose: PostgreSQL CDC apply adapter (pgx/v5 EventApplier)
// Domain: Replication / CDC (infrastructure)
// Author: Ravi Sharma

package cdcio

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

// ApplyWriter applies CDC events to PostgreSQL via pgx/v5.
type ApplyWriter struct {
	pool *pgxpool.Pool
}

// NewApplyWriter wraps an existing pgx pool.
func NewApplyWriter(pool *pgxpool.Pool) *ApplyWriter {
	return &ApplyWriter{pool: pool}
}

// Apply executes the parameterised DML for one CDC event.
func (w *ApplyWriter) Apply(
	ctx context.Context,
	schema, table string,
	ev *cdc.CDCEvent,
	columns, pkColumns []string,
) error {
	stmt := cdc.BuildApplyStatement(schema, table, ev.Operation, columns, pkColumns)
	if !stmt.Applicable {
		return nil
	}

	args, err := bindArgs(ev, stmt, columns, pkColumns)
	if err != nil {
		return err
	}
	_, err = w.pool.Exec(ctx, stmt.SQL, args...)
	if err != nil {
		return fmt.Errorf("cdc apply %s.%s %s: %w", schema, table, ev.Operation, err)
	}
	return nil
}
