// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
)

// TransferDispatchConfig is the Python control-plane JSON in transfer_jobs.config.
type TransferDispatchConfig struct {
	JobID          string                       `json:"job_id"`
	Kind           string                       `json:"kind"`
	Path           string                       `json:"path"`
	Source         TransferConnectionRef        `json:"source"`
	Target         TransferConnectionRef        `json:"target"`
	Tables         []TransferTablePayload       `json:"tables"`
	ConstraintPlan json.RawMessage              `json:"constraint_plan"`
	FileOffload    *TransferFileOffloadSettings `json:"file_offload"`
	SchemaClone    SchemaClonePlan              `json:"schema_clone"`
}

type TransferFileOffloadSettings struct {
	Enabled     bool    `json:"enabled"`
	MinRows     int64   `json:"min_rows"`
	MinMB       float64 `json:"min_mb"`
	StagingPath string  `json:"staging_path"`
}

const defaultFileOffloadMinRows int64 = 2_000_000
const defaultFileOffloadMinMB = 256.0

func DefaultFileOffloadSettings() TransferFileOffloadSettings {
	return TransferFileOffloadSettings{
		Enabled: true,
		MinRows: defaultFileOffloadMinRows,
		MinMB:   defaultFileOffloadMinMB,
	}
}

// ShouldFileOffload reports whether native file offload should run for one table.
// Same-server copies never use files; the app-level setting can disable offload entirely.
func ShouldFileOffload(sameServer bool, settings TransferFileOffloadSettings, rowEstimate int64, sizeMB float64) bool {
	if sameServer || !settings.Enabled {
		return false
	}
	if rowEstimate >= settings.MinRows {
		return true
	}
	return sizeMB > 0 && sizeMB >= settings.MinMB
}

type TransferConnectionRef struct {
	ConnectionID string `json:"connection_id"`
	Schema       string `json:"schema"`
	Engine       string `json:"engine"`
}

type TransferTablePayload struct {
	SourceSchema     string   `json:"source_schema"`
	SourceTable      string   `json:"source_table"`
	TargetSchema     string   `json:"target_schema"`
	TargetTable      string   `json:"target_table"`
	Columns          []string `json:"columns"`
	ChunkSize        int      `json:"chunk_size"`
	OrderColumn      string   `json:"order_column"`
	RowCountEstimate int64    `json:"row_count_estimate"`
}

// PathSupportsDataPlane reports whether this engine binary can move rows for path.
func PathSupportsDataPlane(path string) bool {
	switch path {
	case "pg_to_pg", "mssql_to_pg", "mssql_to_mssql":
		return true
	default:
		return false
	}
}

// ParseTransferDispatchConfig validates transfer_jobs.config JSON.
func ParseTransferDispatchConfig(raw json.RawMessage) (*TransferDispatchConfig, error) {
	if len(raw) == 0 {
		return nil, fmt.Errorf("empty transfer dispatch config")
	}
	var cfg TransferDispatchConfig
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return nil, fmt.Errorf("unmarshal transfer dispatch config: %w", err)
	}
	if cfg.Kind != "transfer" {
		return nil, fmt.Errorf("unsupported dispatch kind %q", cfg.Kind)
	}
	if len(cfg.Tables) == 0 {
		return nil, fmt.Errorf("transfer dispatch config has no tables")
	}
	for _, table := range cfg.Tables {
		if len(table.Columns) == 0 {
			return nil, fmt.Errorf("table %s has no columns", table.SourceTable)
		}
	}
	if _, err := uuid.Parse(cfg.JobID); err != nil {
		return nil, fmt.Errorf("invalid job_id: %w", err)
	}
	if cfg.FileOffload == nil {
		defaults := DefaultFileOffloadSettings()
		cfg.FileOffload = &defaults
	}
	return &cfg, nil
}
