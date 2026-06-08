// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
)

// GoJobDispatchConfig mirrors the Python control-plane JSON contract.
type GoJobDispatchConfig struct {
	JobID            string                    `json:"job_id"`
	Executor         string                    `json:"executor"`
	Source           GoConnectionDispatchRef   `json:"source"`
	Target           GoConnectionDispatchRef   `json:"target"`
	Tables           []GoTableDispatchPayload  `json:"tables"`
	SnapshotRef      *string                   `json:"snapshot_ref"`
	Idempotent       bool                      `json:"idempotent"`
	ConflictColumns  []string                  `json:"conflict_columns"`
	UseNoLock        bool                      `json:"use_nolock"`
	SourceThrottle   SourceThrottleConfig      `json:"source_throttle"`
}

type GoConnectionDispatchRef struct {
	ConnectionID string `json:"connection_id"`
	Schema       string `json:"schema"`
}

type GoTableDispatchPayload struct {
	TableName         string            `json:"table_name"`
	SourceSchema      string            `json:"source_schema"`
	TargetSchema      string            `json:"target_schema"`
	Columns           []string          `json:"columns"`
	ChunkSize         int               `json:"chunk_size"`
	ParallelWorkers   int               `json:"parallel_workers"`
	Strategy          string            `json:"strategy"`
	ColumnTransforms  map[string]string `json:"column_transforms"`
	ColumnSensitivity map[string]string `json:"column_sensitivity"`
	ColumnTypes        map[string]string `json:"column_types"`
	ColumnExtractCasts map[string]string `json:"column_extract_casts"`
	OrderColumn        string            `json:"order_column"`
	WhereClause       string            `json:"where_clause"`
	SourceMaxDOP      int               `json:"source_maxdop"`
	SkipDataLoad      bool              `json:"skip_data_load"`
	RowCountEstimate  int64             `json:"row_count_estimate"`
	TableSizeMB       float64           `json:"table_size_mb"`
	ChunkDelaySec     float64           `json:"chunk_delay_sec"`
}

// ParseGoJobDispatchConfig validates and parses raw JSON from migration_jobs.config.
func ParseGoJobDispatchConfig(raw json.RawMessage) (*GoJobDispatchConfig, error) {
	if len(raw) == 0 {
		return nil, fmt.Errorf("empty dispatch config")
	}
	var cfg GoJobDispatchConfig
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return nil, fmt.Errorf("unmarshal dispatch config: %w", err)
	}
	if cfg.Executor != "go" {
		return nil, fmt.Errorf("unsupported executor %q", cfg.Executor)
	}
	if len(cfg.Tables) == 0 {
		return nil, fmt.Errorf("dispatch config has no tables")
	}
	for _, t := range cfg.Tables {
		if len(t.Columns) == 0 {
			return nil, fmt.Errorf("table %s has no columns", t.TableName)
		}
	}
	if _, err := uuid.Parse(cfg.JobID); err != nil {
		return nil, fmt.Errorf("invalid job_id: %w", err)
	}
	return &cfg, nil
}
