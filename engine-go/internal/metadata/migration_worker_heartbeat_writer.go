// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"
)

// UpsertWorkerHeartbeat records that the Go migration-engine worker is alive.
func (c *Client) UpsertWorkerHeartbeat(
	ctx context.Context, workerID, engineVersion, status string,
) error {
	_, err := c.pool.Exec(ctx, `
		INSERT INTO migration_worker_heartbeats (worker_id, last_seen_at, engine_version, status)
		VALUES ($1, NOW(), $2, $3)
		ON CONFLICT (worker_id) DO UPDATE SET
			last_seen_at = EXCLUDED.last_seen_at,
			engine_version = EXCLUDED.engine_version,
			status = EXCLUDED.status`, workerID, engineVersion, status)
	if err != nil {
		return fmt.Errorf("upsert worker heartbeat: %w", err)
	}
	return nil
}
