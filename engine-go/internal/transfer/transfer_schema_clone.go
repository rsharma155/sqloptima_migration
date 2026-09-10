// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"database/sql"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	_ "github.com/microsoft/go-mssqldb"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

type SchemaCloneStatement struct {
	Phase        string `json:"phase"`
	Kind         string `json:"kind"`
	SQL          string `json:"sql"`
	Schema       string `json:"schema"`
	Name         string `json:"name"`
	SkipIfExists bool   `json:"skip_if_exists"`
}

type SchemaClonePlan struct {
	CreateIfMissing bool                   `json:"create_if_missing"`
	CloneObjects    bool                   `json:"clone_objects"`
	Statements      []SchemaCloneStatement `json:"statements"`
	Notes           []string               `json:"notes"`
}

func (p SchemaClonePlan) Phase(phase string) []SchemaCloneStatement {
	out := make([]SchemaCloneStatement, 0)
	for _, s := range p.Statements {
		if s.Phase == phase {
			out = append(out, s)
		}
	}
	return out
}

type TransferSchemaCloneApplier interface {
	Apply(ctx context.Context, target *metadata.ProjectConnection, statements []SchemaCloneStatement) error
}

type LiveTransferSchemaCloneApplier struct {
	factory TransferConnectionFactory
}

func NewLiveTransferSchemaCloneApplier(masterKey string) *LiveTransferSchemaCloneApplier {
	return &LiveTransferSchemaCloneApplier{factory: TransferConnectionFactory{MasterKey: masterKey}}
}

var _ TransferSchemaCloneApplier = (*LiveTransferSchemaCloneApplier)(nil)

func (a *LiveTransferSchemaCloneApplier) Apply(
	ctx context.Context,
	target *metadata.ProjectConnection,
	statements []SchemaCloneStatement,
) error {
	if len(statements) == 0 {
		return nil
	}
	engine := EffectiveEngine(target)
	for _, stmt := range statements {
		sqlText := strings.TrimSpace(stmt.SQL)
		if sqlText == "" {
			return fmt.Errorf("empty %s clone statement for %s.%s", stmt.Kind, stmt.Schema, stmt.Name)
		}
		if stmt.SkipIfExists {
			exists, err := a.objectExists(ctx, target, engine, stmt)
			if err != nil {
				return err
			}
			if exists {
				continue
			}
		}
		if err := a.execSQL(ctx, target, engine, sqlText); err != nil {
			return fmt.Errorf("%s %s.%s: %w", stmt.Kind, stmt.Schema, stmt.Name, err)
		}
	}
	return nil
}

func (a *LiveTransferSchemaCloneApplier) execSQL(
	ctx context.Context,
	target *metadata.ProjectConnection,
	engine, query string,
) error {
	if engine == "postgres" {
		url, err := a.factory.PostgresURL(target)
		if err != nil {
			return err
		}
		conn, err := pgx.Connect(ctx, url)
		if err != nil {
			return fmt.Errorf("connect target postgres for schema clone: %w", err)
		}
		defer conn.Close(ctx)
		_, err = conn.Exec(ctx, query)
		return err
	}
	cfg, err := a.factory.SQLServerConfig(target)
	if err != nil {
		return err
	}
	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.ExecContext(ctx, query)
	return err
}

func (a *LiveTransferSchemaCloneApplier) objectExists(
	ctx context.Context,
	target *metadata.ProjectConnection,
	engine string,
	stmt SchemaCloneStatement,
) (bool, error) {
	kind := strings.ToLower(stmt.Kind)
	if engine == "postgres" {
		return a.pgExists(ctx, target, kind, stmt.Schema, stmt.Name)
	}
	return a.mssqlExists(ctx, target, kind, stmt.Schema, stmt.Name)
}

func (a *LiveTransferSchemaCloneApplier) mssqlExists(
	ctx context.Context,
	target *metadata.ProjectConnection,
	kind, schema, name string,
) (bool, error) {
	cfg, err := a.factory.SQLServerConfig(target)
	if err != nil {
		return false, err
	}
	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return false, err
	}
	defer db.Close()
	var query string
	switch kind {
	case "schema":
		query = "SELECT CASE WHEN EXISTS (SELECT 1 FROM sys.schemas WHERE name = @p1) THEN 1 ELSE 0 END"
		return scanExists(ctx, db, query, schema)
	case "table":
		query = "SELECT CASE WHEN OBJECT_ID(@p1, 'U') IS NULL THEN 0 ELSE 1 END"
		return scanExists(ctx, db, query, schema+"."+name)
	case "view":
		query = "SELECT CASE WHEN OBJECT_ID(@p1, 'V') IS NULL THEN 0 ELSE 1 END"
		return scanExists(ctx, db, query, schema+"."+name)
	case "procedure":
		query = "SELECT CASE WHEN OBJECT_ID(@p1, 'P') IS NULL THEN 0 ELSE 1 END"
		return scanExists(ctx, db, query, schema+"."+name)
	case "function":
		query = "SELECT CASE WHEN OBJECT_ID(@p1) IS NULL THEN 0 ELSE 1 END"
		return scanExists(ctx, db, query, schema+"."+name)
	case "trigger":
		query = "SELECT CASE WHEN OBJECT_ID(@p1, 'TR') IS NULL THEN 0 ELSE 1 END"
		return scanExists(ctx, db, query, schema+"."+name)
	case "index":
		query = `SELECT CASE WHEN EXISTS (
			SELECT 1 FROM sys.indexes i
			INNER JOIN sys.tables t ON i.object_id = t.object_id
			INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
			WHERE s.name = @p1 AND i.name = @p2
		) THEN 1 ELSE 0 END`
		return scanExists(ctx, db, query, schema, name)
	case "foreign_key", "check":
		query = "SELECT CASE WHEN OBJECT_ID(@p1) IS NULL THEN 0 ELSE 1 END"
		return scanExists(ctx, db, query, schema+"."+name)
	default:
		return false, nil
	}
}

func (a *LiveTransferSchemaCloneApplier) pgExists(
	ctx context.Context,
	target *metadata.ProjectConnection,
	kind, schema, name string,
) (bool, error) {
	url, err := a.factory.PostgresURL(target)
	if err != nil {
		return false, err
	}
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		return false, err
	}
	defer conn.Close(ctx)
	var exists int
	switch kind {
	case "schema":
		err = conn.QueryRow(ctx,
			`SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = $1) THEN 1 ELSE 0 END`,
			schema,
		).Scan(&exists)
	case "table":
		err = conn.QueryRow(ctx,
			`SELECT CASE WHEN to_regclass($1) IS NULL THEN 0 ELSE 1 END`,
			schema+"."+name,
		).Scan(&exists)
	default:
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return exists == 1, nil
}

func scanExists(ctx context.Context, db *sql.DB, query string, args ...any) (bool, error) {
	var exists int
	if err := db.QueryRowContext(ctx, query, args...).Scan(&exists); err != nil {
		return false, err
	}
	return exists == 1, nil
}
