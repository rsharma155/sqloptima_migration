// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// DeleteChunkRange removes rows in [startKey, endKey] for idempotent re-runs.
func (l *Loader) DeleteChunkRange(
	ctx context.Context,
	targetSchema, targetTable, pkColumn string,
	startKey, endKey any,
) error {
	conn, err := pgx.Connect(ctx, l.pgURL)
	if err != nil {
		return fmt.Errorf("pgx connect: %w", err)
	}
	defer conn.Close(ctx)

	sql := fmt.Sprintf(
		`DELETE FROM %s.%s WHERE %s >= $1 AND %s <= $2`,
		quoteIdentPG(targetSchema),
		quoteIdentPG(targetTable),
		quoteIdentPG(pkColumn),
		quoteIdentPG(pkColumn),
	)
	_, err = conn.Exec(ctx, sql, startKey, endKey)
	if err != nil {
		return fmt.Errorf("delete chunk range: %w", err)
	}
	return nil
}
