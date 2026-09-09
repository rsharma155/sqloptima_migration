// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/jackc/pgx/v5"
	_ "github.com/microsoft/go-mssqldb"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
)

type sqlRowsCopySource struct {
	rows *sql.Rows
	vals []any
	err  error
}

func (s *sqlRowsCopySource) Next() bool {
	if !s.rows.Next() {
		s.err = s.rows.Err()
		return false
	}
	cols, err := s.rows.Columns()
	if err != nil {
		s.err = err
		return false
	}
	raw := make([]any, len(cols))
	ptrs := make([]any, len(cols))
	for i := range raw {
		ptrs[i] = &raw[i]
	}
	if err := s.rows.Scan(ptrs...); err != nil {
		s.err = err
		return false
	}
	s.vals = make([]any, len(raw))
	for i, v := range raw {
		s.vals[i] = normalizeDriverValue(v)
	}
	return true
}

func (s *sqlRowsCopySource) Values() ([]any, error) {
	return s.vals, s.err
}

func (s *sqlRowsCopySource) Err() error {
	return s.err
}

func normalizeDriverValue(v any) any {
	if v == nil {
		return nil
	}
	if b, ok := v.([]byte); ok {
		return string(b)
	}
	return v
}

func CopySQLServerToPostgres(
	ctx context.Context,
	mssqlConnStr, pgURL string,
	srcSchema, srcTable, tgtSchema, tgtTable string,
	columns []string,
) (int64, error) {
	query := extractport.BuildSQLServerFullTableQuery(srcSchema, srcTable, columns)
	db, err := sql.Open("sqlserver", mssqlConnStr)
	if err != nil {
		return 0, fmt.Errorf("open transfer SQL Server: %w", err)
	}
	defer db.Close()

	rows, err := db.QueryContext(ctx, query)
	if err != nil {
		return 0, fmt.Errorf("extract transfer SQL Server: %w", err)
	}
	defer rows.Close()

	conn, err := pgx.Connect(ctx, pgURL)
	if err != nil {
		return 0, fmt.Errorf("connect transfer target postgres: %w", err)
	}
	defer conn.Close(ctx)

	copied, err := conn.CopyFrom(
		ctx,
		pgx.Identifier{tgtSchema, tgtTable},
		columns,
		&sqlRowsCopySource{rows: rows},
	)
	if err != nil {
		return copied, fmt.Errorf("COPY FROM transfer target: %w", err)
	}
	return copied, nil
}
