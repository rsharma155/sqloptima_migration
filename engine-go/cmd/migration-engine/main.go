// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// migration-engine is the Go data-plane binary for the SQL Server → PostgreSQL
// migration platform. It replaces the Rust engine-rust/ workspace and
// eliminates the ~9 GB RocksDB + Arrow build artefact.
//
// Startup sequence (mirrors the Rust main.rs):
//  1. Load configuration  (config/default.toml + MIGRATION_* env-var overrides)
//  2. Initialise logging  (zap structured logger)
//  3. Initialise metrics  (OTEL + OTLP gRPC exporter)
//  4. Open the bbolt queue (replaces RocksDB)
//  5. Connect to the metadata PostgreSQL DB
//  6. Initialise the adaptive chunk sizer
//  7. Initialise the CDC state machine
//  8. Start command polling loop
//  9. Wait for SIGINT / SIGTERM → graceful shutdown
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.uber.org/zap"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
	"github.com/ravisharma/sql-optima/engine-go/internal/config"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
	"github.com/ravisharma/sql-optima/engine-go/internal/metrics"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
	"github.com/ravisharma/sql-optima/engine-go/internal/queue"
	"github.com/ravisharma/sql-optima/engine-go/internal/worker"
)

func main() {
	// -------------------------------------------------------------------------
	// 1. Configuration
	// -------------------------------------------------------------------------
	cfg, err := config.Load()
	if err != nil {
		// Logger not yet initialised; write to stderr and exit.
		os.Stderr.WriteString("FATAL config: " + err.Error() + "\n") //nolint:errcheck
		os.Exit(1)
	}

	// -------------------------------------------------------------------------
	// 2. Logging
	// -------------------------------------------------------------------------
	log := initLogger(cfg.Logging.Level, cfg.Logging.Format)
	defer log.Sync() //nolint:errcheck

	log.Info("migration engine starting",
		zap.String("version", "0.2.0"),
		zap.String("go_module", "github.com/ravisharma/sql-optima/engine-go"),
	)
	log.Info("configuration loaded",
		zap.String("metadata_url", cfg.Database.MetadataURL),
		zap.String("queue_path", cfg.Queue.Path),
		zap.Int("extractors", cfg.Workers.ExtractorCount),
		zap.Int("loaders", cfg.Workers.LoaderCount),
	)

	// -------------------------------------------------------------------------
	// 3. Metrics (OTEL)
	// -------------------------------------------------------------------------
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	shutdownMetrics, err := metrics.InitProvider(ctx,
		cfg.Metrics.OTLPEndpoint, cfg.Metrics.ExportIntervalSecs)
	if err != nil {
		log.Fatal("init metrics provider", zap.Error(err))
	}
	defer func() {
		shutCtx, shutCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutCancel()
		if err := shutdownMetrics(shutCtx); err != nil {
			log.Warn("metrics shutdown error", zap.Error(err))
		}
	}()

	engineMetrics, err := metrics.New()
	if err != nil {
		log.Fatal("create engine metrics", zap.Error(err))
	}
	_ = engineMetrics // handed to worker pools in Phase 10 full integration

	// -------------------------------------------------------------------------
	// 4. bbolt queue (replaces RocksDB)
	// -------------------------------------------------------------------------
	q, err := queue.Open(cfg.Queue.Path)
	if err != nil {
		log.Fatal("open bbolt queue", zap.Error(err))
	}
	defer q.Close()
	log.Info("bbolt queue opened", zap.String("path", cfg.Queue.Path))

	// -------------------------------------------------------------------------
	// 5. Metadata DB connection
	// -------------------------------------------------------------------------
	connectCtx, connectCancel := context.WithTimeout(ctx, 30*time.Second)
	meta, err := metadata.Connect(connectCtx, cfg.Database.MetadataURL)
	connectCancel()
	if err != nil {
		log.Fatal("connect metadata DB", zap.Error(err))
	}
	defer meta.Close()
	log.Info("metadata DB connected")

	poller := metadata.NewCommandPoller(meta)
	_ = poller // used per-chunk in worker loops

	// -------------------------------------------------------------------------
	// 6. Adaptive chunk sizer
	// -------------------------------------------------------------------------
	sizer := planner.NewAdaptiveChunkSizer(
		cfg.Chunks.InitialSize,
		cfg.Chunks.MinSize,
		cfg.Chunks.MaxSize,
		cfg.Chunks.TargetMs,
	)
	log.Info("adaptive chunk sizer initialised",
		zap.Int64("initial_chunk_size", sizer.CurrentSize()))

	// -------------------------------------------------------------------------
	// 7. CDC state machine
	// -------------------------------------------------------------------------
	cdcMachine := cdc.NewCDCStateMachine()
	log.Info("CDC state machine initialised",
		zap.String("cdc_state", cdcMachine.State().String()))

	// -------------------------------------------------------------------------
	// 8. Migration worker loop
	// -------------------------------------------------------------------------
	workerID := fmt.Sprintf("go-worker-%d", os.Getpid())
	masterKey := os.Getenv("MIGRATION_MASTER_KEY")
	if masterKey == "" {
		log.Warn("MIGRATION_MASTER_KEY not set — connection password decryption will fail")
	}
	metaAdapter := &worker.MetadataClientAdapter{Client: meta}
	engineRuntime := worker.MigrationEngineRuntime{
		Queue:    q,
		ChunkCfg: cfg.Chunks,
		WorkerID: workerID,
		Sizer:    sizer,
	}
	workerLoop := worker.NewMigrationEngineWorkerLoop(
		workerID, metaAdapter, masterKey, cfg.Database.MetadataURL, poller, engineRuntime,
	)

	go func() {
		if err := workerLoop.Run(ctx); err != nil && ctx.Err() == nil {
			log.Error("migration worker loop exited", zap.Error(err))
		}
	}()

	log.Info("migration worker loop started", zap.String("worker_id", workerID))

	// -------------------------------------------------------------------------
	// 9. Graceful shutdown on SIGINT / SIGTERM
	// -------------------------------------------------------------------------
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	received := <-sig
	log.Info("received shutdown signal", zap.String("signal", received.String()))
	cancel()

	log.Info("migration engine stopped")
}

// initLogger creates a zap structured logger.
// format="json" → production JSON logger; anything else → development text logger.
func initLogger(level, format string) *zap.Logger {
	var cfg zap.Config
	if format == "json" {
		cfg = zap.NewProductionConfig()
	} else {
		cfg = zap.NewDevelopmentConfig()
	}

	switch level {
	case "debug", "trace":
		cfg.Level = zap.NewAtomicLevelAt(zap.DebugLevel)
	case "warn":
		cfg.Level = zap.NewAtomicLevelAt(zap.WarnLevel)
	case "error":
		cfg.Level = zap.NewAtomicLevelAt(zap.ErrorLevel)
	default:
		cfg.Level = zap.NewAtomicLevelAt(zap.InfoLevel)
	}

	log, err := cfg.Build()
	if err != nil {
		panic("failed to build zap logger: " + err.Error())
	}
	return log
}
