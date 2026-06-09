package config_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/config"
)

func TestEnvOverridesConfigFile(t *testing.T) {
	setupConfig(t, minimalConfig)
	t.Setenv("MIGRATION_DATABASE_METADATA_URL", "postgresql://env-override/test")
	t.Setenv("MIGRATION_QUEUE_PATH", "data/env_queue.bbolt")

	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}
	if cfg.Database.MetadataURL != "postgresql://env-override/test" {
		t.Errorf("metadata_url = %q, want env override", cfg.Database.MetadataURL)
	}
	if cfg.Queue.Path != "data/env_queue.bbolt" {
		t.Errorf("queue.path = %q, want env override", cfg.Queue.Path)
	}
}
