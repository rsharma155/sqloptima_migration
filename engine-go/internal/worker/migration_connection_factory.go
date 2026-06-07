// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"fmt"
	"net/url"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
	"github.com/ravisharma/sql-optima/engine-go/internal/secrets"
)

// MigrationConnectionFactory builds driver configs from metadata connection rows.
type MigrationConnectionFactory struct {
	MasterKey string
}

func (f MigrationConnectionFactory) SQLServerConfig(conn *metadata.ProjectConnection) (extractor.SQLServerConfig, error) {
	password, err := secrets.DecryptMigrationSecret(f.MasterKey, conn.EncryptedPassword)
	if err != nil {
		return extractor.SQLServerConfig{}, fmt.Errorf("decrypt source password: %w", err)
	}
	port := conn.Port
	if port == 0 {
		port = 1433
	}
	return extractor.SQLServerConfig{
		Host:                   conn.Host,
		Port:                   port,
		Database:               conn.Database,
		User:                   conn.Username,
		Password:               password,
		TrustServerCertificate: conn.TrustServerCertificate,
	}, nil
}

func (f MigrationConnectionFactory) PostgresURL(conn *metadata.ProjectConnection) (string, error) {
	password, err := secrets.DecryptMigrationSecret(f.MasterKey, conn.EncryptedPassword)
	if err != nil {
		return "", fmt.Errorf("decrypt target password: %w", err)
	}
	port := conn.Port
	if port == 0 {
		port = 5432
	}
	u := &url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(conn.Username, password),
		Host:   fmt.Sprintf("%s:%d", conn.Host, port),
		Path:   conn.Database,
	}
	return u.String(), nil
}
