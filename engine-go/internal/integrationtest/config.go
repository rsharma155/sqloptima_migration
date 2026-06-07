// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

//go:build integration

package integrationtest

import (
	"fmt"
	"os"
	"strconv"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// SQLServerConfigFromEnv loads source connection settings from MIGRATION_SOURCE_* env vars.
// Skips the test when MIGRATION_SOURCE_HOST is unset.
func SQLServerConfigFromEnv(t *testing.T) extractor.SQLServerConfig {
	t.Helper()
	host := os.Getenv("MIGRATION_SOURCE_HOST")
	if host == "" {
		t.Skip("MIGRATION_SOURCE_HOST not set — skipping live SQL Server integration test")
	}
	port := envInt("MIGRATION_SOURCE_PORT", 1433)
	return extractor.SQLServerConfig{
		Host:                   host,
		Port:                   port,
		Database:               envStr("MIGRATION_SOURCE_DATABASE", "master"),
		User:                   envStr("MIGRATION_SOURCE_USER", "sa"),
		Password:               os.Getenv("MIGRATION_SOURCE_PASSWORD"),
		TrustServerCertificate: true,
	}
}

// PostgresURLFromEnv returns a PostgreSQL connection URL from MIGRATION_TARGET_* or
// MIGRATION_TARGET_PG_URL. Skips when neither host nor URL is configured.
func PostgresURLFromEnv(t *testing.T) string {
	t.Helper()
	if u := os.Getenv("MIGRATION_TARGET_PG_URL"); u != "" {
		return u
	}
	host := os.Getenv("MIGRATION_TARGET_HOST")
	if host == "" {
		t.Skip("MIGRATION_TARGET_HOST or MIGRATION_TARGET_PG_URL not set — skipping live PG integration test")
	}
	port := envInt("MIGRATION_TARGET_PORT", 5432)
	user := envStr("MIGRATION_TARGET_USER", "postgres")
	pass := os.Getenv("MIGRATION_TARGET_PASSWORD")
	db := envStr("MIGRATION_TARGET_DATABASE", "postgres")
	return fmt.Sprintf("postgresql://%s:%s@%s:%d/%s", user, pass, host, port, db)
}

func envStr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return n
}
