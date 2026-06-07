// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package config_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/config"
)

// createTempConfig writes a minimal TOML config to a temp dir and changes the
// working directory to that dir so Load() finds it.
func setupConfig(t *testing.T, content string) {
	t.Helper()
	dir := t.TempDir()
	cfgDir := filepath.Join(dir, "config")
	if err := os.MkdirAll(cfgDir, 0755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if err := os.WriteFile(filepath.Join(cfgDir, "default.toml"), []byte(content), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	orig, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatalf("Chdir: %v", err)
	}
	t.Cleanup(func() { os.Chdir(orig) }) //nolint:errcheck
}

const minimalConfig = `
[database]
metadata_url    = "postgresql://localhost/test"
command_poll_ms = 500

[queue]
path = "/tmp/test.bbolt"

[workers]
extractor_count = 2
loader_count    = 2

[chunks]
initial_size = 5000
target_ms    = 1000
min_size     = 100
max_size     = 50000

[metrics]
otlp_endpoint        = ""
export_interval_secs = 10

[logging]
level  = "info"
format = "json"
`

func TestLoadMinimalConfig(t *testing.T) {
	setupConfig(t, minimalConfig)
	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}
	if cfg.Database.MetadataURL != "postgresql://localhost/test" {
		t.Errorf("metadata_url = %q", cfg.Database.MetadataURL)
	}
	if cfg.Workers.ExtractorCount != 2 {
		t.Errorf("extractor_count = %d, want 2", cfg.Workers.ExtractorCount)
	}
	if cfg.Chunks.MinSize >= cfg.Chunks.MaxSize {
		t.Error("min_size must be < max_size")
	}
}

func TestValidationRejectsInvertedChunkBounds(t *testing.T) {
	setupConfig(t, `
[database]
metadata_url = "postgresql://localhost/test"
command_poll_ms = 500

[queue]
path = "/tmp/test.bbolt"

[workers]
extractor_count = 1
loader_count = 1

[chunks]
initial_size = 1000
target_ms = 2000
min_size = 50000
max_size = 1000

[metrics]
otlp_endpoint = ""
export_interval_secs = 10

[logging]
level = "info"
format = "json"
`)
	if _, err := config.Load(); err == nil {
		t.Error("inverted min/max chunk bounds must produce an error")
	}
}
