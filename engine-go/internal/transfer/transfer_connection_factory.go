// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"fmt"
	"net/url"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
	"github.com/ravisharma/sql-optima/engine-go/internal/secrets"
)

// TransferConnectionFactory builds driver configs from metadata connection rows
// using the connection engine field (not db_type role).
type TransferConnectionFactory struct {
	MasterKey string
}

func EffectiveEngine(conn *metadata.ProjectConnection) string {
	if conn == nil {
		return ""
	}
	if conn.Engine != "" {
		return conn.Engine
	}
	if conn.DBType == "target" {
		return "postgres"
	}
	return "sqlserver"
}

func (f TransferConnectionFactory) SQLServerConfig(conn *metadata.ProjectConnection) (extractor.SQLServerConfig, error) {
	password, err := secrets.DecryptMigrationSecret(f.MasterKey, conn.EncryptedPassword)
	if err != nil {
		return extractor.SQLServerConfig{}, fmt.Errorf("decrypt transfer source password: %w", err)
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

func (f TransferConnectionFactory) PostgresURL(conn *metadata.ProjectConnection) (string, error) {
	password, err := secrets.DecryptMigrationSecret(f.MasterKey, conn.EncryptedPassword)
	if err != nil {
		return "", fmt.Errorf("decrypt transfer password: %w", err)
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
