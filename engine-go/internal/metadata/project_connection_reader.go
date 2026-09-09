// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// ProjectConnection holds credentials loaded from project_connections.
type ProjectConnection struct {
	ConnectionID           uuid.UUID
	Name                   string
	DBType                 string
	Engine                 string
	Host                   string
	Port                   int
	Database               string
	Username               string
	EncryptedPassword      string
	TrustServerCertificate bool
}

// LoadProjectConnection reads a connection row by ID.
func (c *Client) LoadProjectConnection(ctx context.Context, connectionID uuid.UUID) (*ProjectConnection, error) {
	var row ProjectConnection
	var idStr string
	err := c.pool.QueryRow(ctx, `
		SELECT project_connection_id, name, db_type,
		       COALESCE(NULLIF(engine, ''), CASE WHEN db_type = 'target' THEN 'postgres' ELSE 'sqlserver' END),
		       host, port, database_name,
		       username, encrypted_password, ssl_enabled
		FROM project_connections
		WHERE project_connection_id = $1`, connectionID.String(),
	).Scan(
		&idStr, &row.Name, &row.DBType, &row.Engine, &row.Host, &row.Port, &row.Database,
		&row.Username, &row.EncryptedPassword, &row.TrustServerCertificate,
	)
	if err != nil {
		return nil, fmt.Errorf("load project connection: %w", err)
	}
	parsed, err := uuid.Parse(idStr)
	if err != nil {
		return nil, fmt.Errorf("parse connection id: %w", err)
	}
	row.ConnectionID = parsed
	return &row, nil
}

// UpdateMigrationJobTotals sets job-level row/table counters on completion.
func (c *Client) UpdateMigrationJobTotals(
	ctx context.Context, jobID uuid.UUID, rowsMigrated int64, tablesDone int,
) error {
	_, err := c.pool.Exec(ctx, `
		UPDATE migration_jobs
		SET rows_migrated = $1, tables_done = $2, updated_at = NOW()
		WHERE migration_job_id = $3`,
		rowsMigrated, tablesDone, jobID.String())
	if err != nil {
		return fmt.Errorf("update migration job totals: %w", err)
	}
	return nil
}
