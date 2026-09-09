// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/reader.go
// Purpose: SQL Server CDC CT-table reader (go-mssqldb EventSource adapter)
// Domain: Replication / CDC (infrastructure)
// Author: Ravi Sharma

package cdcio

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	_ "github.com/microsoft/go-mssqldb" // register sqlserver driver

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// CaptureReader polls SQL Server cdc.<capture>_CT tables via go-mssqldb.
type CaptureReader struct {
	cfg extractor.SQLServerConfig
	db  *sql.DB
}

// NewCaptureReader opens a SQL Server connection for CDC capture reads.
func NewCaptureReader(cfg extractor.SQLServerConfig) (*CaptureReader, error) {
	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return nil, fmt.Errorf("open SQL Server for CDC: %w", err)
	}
	db.SetConnMaxLifetime(5 * time.Minute)
	db.SetMaxOpenConns(2)
	return &CaptureReader{cfg: cfg, db: db}, nil
}

// Close closes the underlying SQL Server connection.
func (r *CaptureReader) Close() error {
	if r.db == nil {
		return nil
	}
	return r.db.Close()
}

// Ping verifies the SQL Server connection is usable.
func (r *CaptureReader) Ping(ctx context.Context) error {
	return r.db.PingContext(ctx)
}

// ReadAfter reads up to limit CDC events with __$start_lsn > after.
func (r *CaptureReader) ReadAfter(
	ctx context.Context,
	schema, table, captureInstance string,
	after cdc.LSN,
	columns []string,
	limit int,
) ([]*cdc.CDCEvent, error) {
	if limit <= 0 {
		limit = 1000
	}
	query := cdc.BuildCaptureReadQueryWithColumns(captureInstance, columns, limit)

	rows, err := r.db.QueryContext(ctx, query, sql.Named("P1", after[:]))
	if err != nil {
		return nil, fmt.Errorf("cdc capture read %s: %w", captureInstance, err)
	}
	defer rows.Close()

	colNames, err := rows.Columns()
	if err != nil {
		return nil, fmt.Errorf("cdc columns: %w", err)
	}

	var events []*cdc.CDCEvent
	for rows.Next() {
		dest := make([]interface{}, len(colNames))
		ptrs := make([]interface{}, len(colNames))
		for i := range dest {
			ptrs[i] = &dest[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, fmt.Errorf("cdc scan: %w", err)
		}

		ev, err := rowToEvent(schema, table, colNames, dest)
		if err != nil {
			return nil, err
		}
		events = append(events, ev)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	cdc.OrderForApply(events)
	return events, nil
}

// MaxLSN returns sys.fn_cdc_get_max_lsn() for lag measurement.
func (r *CaptureReader) MaxLSN(ctx context.Context) (cdc.LSN, error) {
	var raw []byte
	err := r.db.QueryRowContext(ctx, cdc.BuildMaxLSNQuery()).Scan(&raw)
	if err != nil {
		return cdc.ZeroLSN, fmt.Errorf("max LSN: %w", err)
	}
	return bytesToLSN(raw)
}
