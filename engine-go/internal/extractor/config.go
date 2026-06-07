// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

import "fmt"

// SQLServerConfig holds connection parameters for a SQL Server data source.
type SQLServerConfig struct {
	Host     string
	Port     int
	Database string
	User     string
	Password string
	// TrustServerCertificate disables TLS certificate verification.
	// Set to true only in development / test environments.
	TrustServerCertificate bool
}

// ConnectionString returns an ADO-style connection string understood by
// the go-mssqldb driver.
func (c SQLServerConfig) ConnectionString() string {
	trust := "false"
	if c.TrustServerCertificate {
		trust = "true"
	}
	return fmt.Sprintf(
		"sqlserver://%s:%s@%s:%d?database=%s&TrustServerCertificate=%s",
		c.User, c.Password, c.Host, c.Port, c.Database, trust,
	)
}
