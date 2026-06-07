// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

//go:build integration

package worker_test

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	_ "github.com/microsoft/go-mssqldb"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/integrationtest"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
	"github.com/ravisharma/sql-optima/engine-go/internal/worker"
)

func TestChunkPipeline_SQLServerToPostgres_integration(t *testing.T) {
	srcCfg := integrationtest.SQLServerConfigFromEnv(t)
	pgURL := integrationtest.PostgresURLFromEnv(t)

	table := fmt.Sprintf("GoInteg_%s", strings.ReplaceAll(uuid.NewString()[:8], "-", ""))
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	mssql, err := sql.Open("sqlserver", srcCfg.ConnectionString())
	if err != nil {
		t.Fatalf("open sqlserver: %v", err)
	}
	defer mssql.Close()

	_, err = mssql.ExecContext(ctx, fmt.Sprintf(`
		IF OBJECT_ID('dbo.%s', 'U') IS NOT NULL DROP TABLE dbo.%s;
		CREATE TABLE dbo.%s (
			id INT NOT NULL PRIMARY KEY,
			name NVARCHAR(100) NOT NULL,
			amount DECIMAL(18,2) NOT NULL
		);
		INSERT INTO dbo.%s (id, name, amount) VALUES
			(1, N'alpha', 10.50),
			(2, N'beta', 20.25),
			(3, N'gamma', 30.00);
	`, table, table, table, table))
	if err != nil {
		t.Fatalf("setup sqlserver table: %v", err)
	}
	defer func() { _, _ = mssql.ExecContext(context.Background(), fmt.Sprintf("DROP TABLE IF EXISTS dbo.%s", table)) }()

	pg, err := sql.Open("pgx", pgURL)
	if err != nil {
		t.Fatalf("open postgres: %v", err)
	}
	defer pg.Close()

	_, err = pg.ExecContext(ctx, fmt.Sprintf(`
		DROP TABLE IF EXISTS public."%s";
		CREATE TABLE public."%s" (
			id INTEGER PRIMARY KEY,
			name TEXT NOT NULL,
			amount NUMERIC(18,2) NOT NULL
		);
	`, table, table))
	if err != nil {
		t.Fatalf("setup postgres table: %v", err)
	}
	defer func() { _, _ = pg.ExecContext(context.Background(), fmt.Sprintf(`DROP TABLE IF EXISTS public."%s"`, table)) }()

	jobID := uuid.New()
	bounds := planner.PrimaryKeyBounds{Min: 1, Max: 3}
	chunks := planner.NewPrimaryKeyChunker(100).Plan(jobID, "dbo", table, "id", bounds)
	if len(chunks) == 0 {
		t.Fatal("expected at least one chunk")
	}

	schema := extractor.ExtractionSchema{Columns: []extractor.ExtractionColumn{
		{Name: "id", LogicalType: core.LogicalInt32},
		{Name: "name", LogicalType: core.LogicalUtf8},
		{Name: "amount", LogicalType: core.LogicalDecimal},
	}}

	pipeline := worker.NewMigrationChunkPipeline(srcCfg, pgURL)
	var total int64
	for _, chunk := range chunks {
		rows, err := pipeline.Run(
			ctx, chunk, "public", table, schema, false,
			[]string{"id"}, extractor.ExtractOptions{}, nil,
		)
		if err != nil {
			t.Fatalf("pipeline chunk %d: %v", chunk.ChunkIndex, err)
		}
		total += rows
	}
	if total != 3 {
		t.Fatalf("rows migrated = %d, want 3", total)
	}

	var pgCount int
	if err := pg.QueryRowContext(ctx, fmt.Sprintf(`SELECT COUNT(*) FROM public."%s"`, table)).Scan(&pgCount); err != nil {
		t.Fatalf("count postgres: %v", err)
	}
	if pgCount != 3 {
		t.Fatalf("postgres row count = %d, want 3", pgCount)
	}
}
