// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

func TestConnectionStringContainsHost(t *testing.T) {
	cfg := extractor.SQLServerConfig{
		Host:     "db.example.com",
		Port:     1433,
		Database: "mydb",
		User:     "sa",
		Password: "secret",
	}
	cs := cfg.ConnectionString()
	if !strings.Contains(cs, "db.example.com") {
		t.Errorf("connection string must contain host, got: %s", cs)
	}
	if !strings.Contains(cs, "1433") {
		t.Errorf("connection string must contain port, got: %s", cs)
	}
	if !strings.Contains(cs, "mydb") {
		t.Errorf("connection string must contain database, got: %s", cs)
	}
}

func TestConnectionStringTrustCertFalseByDefault(t *testing.T) {
	cfg := extractor.SQLServerConfig{
		Host: "localhost", Port: 1433, Database: "db", User: "u", Password: "p",
	}
	cs := cfg.ConnectionString()
	if !strings.Contains(cs, "TrustServerCertificate=false") {
		t.Errorf("default connection string must set TrustServerCertificate=false, got: %s", cs)
	}
}

func TestConnectionStringTrustCertTrue(t *testing.T) {
	cfg := extractor.SQLServerConfig{
		Host: "localhost", Port: 1433, Database: "db", User: "u", Password: "p",
		TrustServerCertificate: true,
	}
	cs := cfg.ConnectionString()
	if !strings.Contains(cs, "TrustServerCertificate=true") {
		t.Errorf("connection string must set TrustServerCertificate=true, got: %s", cs)
	}
}

func TestConnectionStringUsesScheme(t *testing.T) {
	cfg := extractor.SQLServerConfig{
		Host: "localhost", Port: 1433, Database: "db", User: "u", Password: "p",
	}
	if cs := cfg.ConnectionString(); !strings.HasPrefix(cs, "sqlserver://") {
		t.Errorf("connection string must start with sqlserver://, got: %s", cs)
	}
}
