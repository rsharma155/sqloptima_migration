// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/viper"
)

// EngineConfig holds the full, validated engine configuration.
// Values come from config/default.toml with MIGRATION_* env-var overrides.
type EngineConfig struct {
	Database DatabaseConfig
	Queue    QueueConfig
	Workers  WorkerConfig
	Chunks   ChunkConfig
	Metrics  MetricsConfig
	Logging  LoggingConfig
}

// DatabaseConfig holds metadata-DB connection settings.
type DatabaseConfig struct {
	MetadataURL   string        `mapstructure:"metadata_url"`
	CommandPollMs time.Duration `mapstructure:"command_poll_ms"`
}

// QueueConfig holds bbolt queue settings.
type QueueConfig struct {
	Path string `mapstructure:"path"`
}

// WorkerConfig holds worker-pool sizes.
type WorkerConfig struct {
	ExtractorCount int `mapstructure:"extractor_count"`
	LoaderCount    int `mapstructure:"loader_count"`
}

// ChunkConfig holds adaptive-chunking parameters.
type ChunkConfig struct {
	InitialSize int64 `mapstructure:"initial_size"`
	TargetMs    int64 `mapstructure:"target_ms"`
	MinSize     int64 `mapstructure:"min_size"`
	MaxSize     int64 `mapstructure:"max_size"`
}

// MetricsConfig holds OpenTelemetry exporter settings.
type MetricsConfig struct {
	OTLPEndpoint        string        `mapstructure:"otlp_endpoint"`
	ExportIntervalSecs  time.Duration `mapstructure:"export_interval_secs"`
}

// LoggingConfig holds structured-logging settings.
type LoggingConfig struct {
	Level  string `mapstructure:"level"`
	Format string `mapstructure:"format"`
}

// Load reads config/default.toml (relative to the working directory) and
// applies MIGRATION_* environment variable overrides.
//
// Environment variable mapping: MIGRATION_<SECTION>_<KEY>
// Example: MIGRATION_DATABASE_METADATA_URL → database.metadata_url
func Load() (*EngineConfig, error) {
	v := viper.New()
	v.SetConfigName("default")
	v.SetConfigType("toml")
	v.AddConfigPath("config/")

	// Environment-variable overrides (MIGRATION_DATABASE_METADATA_URL etc.)
	v.SetEnvPrefix("MIGRATION")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()
	// Explicit binds so start.py overrides always win over default.toml (esp. on Windows).
	_ = v.BindEnv("database.metadata_url", "MIGRATION_DATABASE_METADATA_URL")
	_ = v.BindEnv("queue.path", "MIGRATION_QUEUE_PATH")
	_ = v.BindEnv("metrics.otlp_endpoint", "MIGRATION_METRICS_OTLP_ENDPOINT")

	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}

	cfg := &EngineConfig{}

	cfg.Database.MetadataURL = v.GetString("database.metadata_url")
	cfg.Database.CommandPollMs = time.Duration(v.GetInt64("database.command_poll_ms")) * time.Millisecond

	cfg.Queue.Path = v.GetString("queue.path")

	cfg.Workers.ExtractorCount = v.GetInt("workers.extractor_count")
	cfg.Workers.LoaderCount = v.GetInt("workers.loader_count")

	cfg.Chunks.InitialSize = v.GetInt64("chunks.initial_size")
	cfg.Chunks.TargetMs = v.GetInt64("chunks.target_ms")
	cfg.Chunks.MinSize = v.GetInt64("chunks.min_size")
	cfg.Chunks.MaxSize = v.GetInt64("chunks.max_size")

	cfg.Metrics.OTLPEndpoint = v.GetString("metrics.otlp_endpoint")
	cfg.Metrics.ExportIntervalSecs = time.Duration(v.GetInt64("metrics.export_interval_secs")) * time.Second

	cfg.Logging.Level = v.GetString("logging.level")
	cfg.Logging.Format = v.GetString("logging.format")

	if err := validate(cfg); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}
	return cfg, nil
}

func validate(cfg *EngineConfig) error {
	if cfg.Database.MetadataURL == "" {
		return fmt.Errorf("database.metadata_url is required")
	}
	if cfg.Queue.Path == "" {
		return fmt.Errorf("queue.path is required")
	}
	if cfg.Chunks.MinSize > cfg.Chunks.MaxSize {
		return fmt.Errorf("chunks.min_size (%d) must not exceed chunks.max_size (%d)",
			cfg.Chunks.MinSize, cfg.Chunks.MaxSize)
	}
	if cfg.Workers.ExtractorCount < 1 {
		return fmt.Errorf("workers.extractor_count must be >= 1")
	}
	if cfg.Workers.LoaderCount < 1 {
		return fmt.Errorf("workers.loader_count must be >= 1")
	}
	return nil
}
