// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// InsertMigrationQuarantine records a failed chunk row in migration_quarantine.
func (c *Client) InsertMigrationQuarantine(
	ctx context.Context,
	jobID uuid.UUID,
	tableSchema, tableName string,
	chunkIndex uint32,
	pkColumn string,
	startKey, endKey *string,
	errMsg string,
) error {
	pkValue := fmt.Sprintf("%s:[%s,%s]", pkColumn, derefKey(startKey), derefKey(endKey))
	_, err := c.pool.Exec(ctx,
		`INSERT INTO migration_quarantine (
			migration_quarantine_id, migration_job_id,
			table_schema, table_name, row_pk_value,
			error_type, error_message, created_at
		) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())`,
		uuid.New().String(),
		jobID.String(),
		tableSchema,
		tableName,
		pkValue,
		"chunk_failure",
		fmt.Sprintf("chunk %d: %s", chunkIndex, errMsg),
	)
	return err
}

func derefKey(k *string) string {
	if k == nil {
		return ""
	}
	return *k
}
