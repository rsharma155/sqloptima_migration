// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/worker.go
// Purpose: Optional env-configured CDC live I/O worker launched from main
// Domain: Replication / CDC (application composition root helper)
// Author: Ravi Sharma

package cdcio

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.uber.org/zap"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/metrics"
)

// EnvWorkerConfig holds optional CDC live-I/O settings from the environment.
// When MIGRATION_CDC_ENABLED is not "1"/"true", StartEnvWorker is a no-op.
type EnvWorkerConfig struct {
	Enabled         bool
	SourceHost      string
	SourcePort      int
	SourceDatabase  string
	SourceUser      string
	SourcePassword  string
	TargetURL       string
	Schema          string
	Table           string
	CaptureInstance string
	Columns         []string
	PKColumns       []string
	TargetSchema    string
	TargetTable     string
	PollInterval    time.Duration
	BatchSize       int
}

// LoadEnvWorkerConfig parses CDC worker settings from environment variables.
func LoadEnvWorkerConfig() EnvWorkerConfig {
	enabled := os.Getenv("MIGRATION_CDC_ENABLED")
	cfg := EnvWorkerConfig{
		Enabled:         enabled == "1" || enabled == "true" || enabled == "TRUE",
		SourceHost:      envOr("MIGRATION_CDC_SOURCE_HOST", os.Getenv("MIGRATION_SOURCE_HOST")),
		SourceDatabase:  envOr("MIGRATION_CDC_SOURCE_DATABASE", os.Getenv("MIGRATION_SOURCE_DATABASE")),
		SourceUser:      envOr("MIGRATION_CDC_SOURCE_USER", os.Getenv("MIGRATION_SOURCE_USER")),
		SourcePassword:  envOr("MIGRATION_CDC_SOURCE_PASSWORD", os.Getenv("MIGRATION_SOURCE_PASSWORD")),
		TargetURL:       os.Getenv("MIGRATION_CDC_TARGET_URL"),
		Schema:          envOr("MIGRATION_CDC_SCHEMA", "dbo"),
		Table:           os.Getenv("MIGRATION_CDC_TABLE"),
		CaptureInstance: os.Getenv("MIGRATION_CDC_CAPTURE_INSTANCE"),
		TargetSchema:    envOr("MIGRATION_CDC_TARGET_SCHEMA", "public"),
		TargetTable:     os.Getenv("MIGRATION_CDC_TARGET_TABLE"),
		PollInterval:    time.Second,
		BatchSize:       1000,
		SourcePort:      1433,
	}
	if port := os.Getenv("MIGRATION_CDC_SOURCE_PORT"); port != "" {
		if p, err := strconv.Atoi(port); err == nil && p > 0 {
			cfg.SourcePort = p
		}
	}
	if cols := os.Getenv("MIGRATION_CDC_COLUMNS"); cols != "" {
		cfg.Columns = splitCSV(cols)
	}
	if pks := os.Getenv("MIGRATION_CDC_PK_COLUMNS"); pks != "" {
		cfg.PKColumns = splitCSV(pks)
	} else {
		cfg.PKColumns = []string{"id"}
	}
	if cfg.TargetTable == "" {
		cfg.TargetTable = cfg.Table
	}
	if cfg.CaptureInstance == "" && cfg.Schema != "" && cfg.Table != "" {
		cfg.CaptureInstance = cfg.Schema + "_" + cfg.Table
	}
	return cfg
}

// StartEnvWorker launches RunPollLoop in a goroutine when env config is complete.
// Returns a cancel function (nil if not started).
func StartEnvWorker(
	ctx context.Context,
	log *zap.Logger,
	em *metrics.EngineMetrics,
) (context.CancelFunc, error) {
	cfg := LoadEnvWorkerConfig()
	if !cfg.Enabled {
		log.Info("CDC live I/O worker disabled (set MIGRATION_CDC_ENABLED=1 to enable)")
		return nil, nil
	}
	if cfg.Table == "" || cfg.TargetURL == "" || cfg.SourceHost == "" {
		return nil, fmt.Errorf("CDC enabled but missing table/target URL/source host")
	}

	reader, err := NewCaptureReader(extractor.SQLServerConfig{
		Host:                   cfg.SourceHost,
		Port:                   cfg.SourcePort,
		Database:               cfg.SourceDatabase,
		User:                   cfg.SourceUser,
		Password:               cfg.SourcePassword,
		TrustServerCertificate: true,
	})
	if err != nil {
		return nil, err
	}

	pool, err := pgxpool.New(ctx, cfg.TargetURL)
	if err != nil {
		_ = reader.Close()
		return nil, fmt.Errorf("pgx pool: %w", err)
	}
	writer := NewApplyWriter(pool)

	workerCtx, cancel := context.WithCancel(ctx)
	sm := cdc.NewCDCStateMachine()
	jobID := uuid.Nil

	go func() {
		defer reader.Close()
		defer pool.Close()
		log.Info("CDC live I/O worker starting",
			zap.String("capture", cfg.CaptureInstance),
			zap.String("table", cfg.Schema+"."+cfg.Table),
		)
		err := RunPollLoop(workerCtx, sm, reader, writer, PollLoopConfig{
			Schema:          cfg.Schema,
			Table:           cfg.Table,
			CaptureInstance: cfg.CaptureInstance,
			Columns:         cfg.Columns,
			PKColumns:       cfg.PKColumns,
			TargetSchema:    cfg.TargetSchema,
			TargetTable:     cfg.TargetTable,
			PollInterval:    cfg.PollInterval,
			BatchSize:       cfg.BatchSize,
			OnLag: func(ctx context.Context, lagHint int64) {
				if em != nil {
					em.SetCDCLag(ctx, jobID, lagHint)
				}
			},
		})
		if err != nil && workerCtx.Err() == nil {
			log.Error("CDC live I/O worker failed", zap.Error(err))
		} else {
			log.Info("CDC live I/O worker stopped", zap.String("state", sm.State().String()))
		}
	}()

	return cancel, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func splitCSV(s string) []string {
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
