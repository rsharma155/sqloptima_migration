// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	_ "github.com/microsoft/go-mssqldb"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
	"github.com/ravisharma/sql-optima/engine-go/internal/planner"
)

// ChunkKeyKind identifies how a table should be chunked.
type ChunkKeyKind int

const (
	ChunkKeyInteger ChunkKeyKind = iota
	ChunkKeyDateTime
	ChunkKeyUUID
)

// ChunkKeyInfo describes the column used for range chunking.
type ChunkKeyInfo struct {
	Column    string
	Kind      ChunkKeyKind
	Composite []string
}

// SQLServerChunkKeyDiscoverer discovers the chunking column and its kind.
type SQLServerChunkKeyDiscoverer struct{}

// SQLServerPrimaryKeyDiscoverer is kept for compatibility with older call sites.
type SQLServerPrimaryKeyDiscoverer = SQLServerChunkKeyDiscoverer

func (SQLServerChunkKeyDiscoverer) Discover(
	ctx context.Context,
	cfg extractor.SQLServerConfig,
	schema, table string,
) (string, error) {
	info, err := SQLServerChunkKeyDiscoverer{}.DiscoverKey(ctx, cfg, schema, table, "", nil)
	if err != nil {
		return "", err
	}
	return info.Column, nil
}

func (d SQLServerChunkKeyDiscoverer) DiscoverKey(
	ctx context.Context,
	cfg extractor.SQLServerConfig,
	schema, table, orderColumn string,
	columnTypes map[string]string,
) (ChunkKeyInfo, error) {
	if orderColumn != "" {
		kind := classifySQLType(columnTypes[orderColumn])
		return ChunkKeyInfo{Column: orderColumn, Kind: kind}, nil
	}

	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return ChunkKeyInfo{}, fmt.Errorf("open sqlserver: %w", err)
	}
	defer db.Close()

	query := `
		SELECT c.name, ty.name
		FROM sys.indexes i
		INNER JOIN sys.index_columns ic
			ON i.object_id = ic.object_id AND i.index_id = ic.index_id
		INNER JOIN sys.columns c
			ON ic.object_id = c.object_id AND ic.column_id = c.column_id
		INNER JOIN sys.types ty ON c.user_type_id = ty.user_type_id
		INNER JOIN sys.tables t ON i.object_id = t.object_id
		INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
		WHERE i.is_primary_key = 1
		  AND s.name = @P1
		  AND t.name = @P2
		ORDER BY ic.key_ordinal`

	rows, err := db.QueryContext(ctx, query, sql.Named("P1", schema), sql.Named("P2", table))
	if err != nil {
		return ChunkKeyInfo{}, fmt.Errorf("query primary key for %s.%s: %w", schema, table, err)
	}
	defer rows.Close()

	var pkCols []string
	var pkTypes []string
	for rows.Next() {
		var name, typeName sql.NullString
		if err := rows.Scan(&name, &typeName); err != nil {
			return ChunkKeyInfo{}, err
		}
		if name.Valid && name.String != "" {
			pkCols = append(pkCols, name.String)
			pkTypes = append(pkTypes, typeName.String)
		}
	}
	if err := rows.Err(); err != nil {
		return ChunkKeyInfo{}, err
	}
	if len(pkCols) == 0 {
		return ChunkKeyInfo{}, fmt.Errorf("no primary key found for %s.%s", schema, table)
	}

	info := ChunkKeyInfo{
		Column: pkCols[0],
		Kind:   classifySQLType(pkTypes[0]),
	}
	if len(pkCols) > 1 {
		info.Composite = append([]string(nil), pkCols...)
	}
	return info, nil
}

func classifySQLType(typeName string) ChunkKeyKind {
	base := strings.ToLower(strings.TrimSpace(typeName))
	if i := strings.IndexByte(base, '('); i >= 0 {
		base = strings.TrimSpace(base[:i])
	}
	switch base {
	case "uniqueidentifier":
		return ChunkKeyUUID
	case "datetime", "datetime2", "smalldatetime", "date":
		return ChunkKeyDateTime
	default:
		return ChunkKeyInteger
	}
}

// SQLServerChunkBoundsReader reads MIN/MAX bounds for chunk keys.
type SQLServerChunkBoundsReader struct{}

// SQLServerPKBoundsReader alias for legacy callers.
type SQLServerPKBoundsReader = SQLServerChunkBoundsReader

func (SQLServerChunkBoundsReader) Read(
	ctx context.Context, cfg extractor.SQLServerConfig, schema, table, pkCol string,
) (planner.PrimaryKeyBounds, error) {
	return SQLServerChunkBoundsReader{}.ReadInteger(ctx, cfg, schema, table, pkCol)
}

func (SQLServerChunkBoundsReader) ReadInteger(
	ctx context.Context, cfg extractor.SQLServerConfig, schema, table, col string,
) (planner.PrimaryKeyBounds, error) {
	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return planner.PrimaryKeyBounds{}, err
	}
	defer db.Close()
	var lo, hi sql.NullInt64
	if err := db.QueryRowContext(ctx, extractor.BuildBoundsQuery(schema, table, col)).Scan(&lo, &hi); err != nil {
		return planner.PrimaryKeyBounds{}, err
	}
	if !lo.Valid || !hi.Valid {
		return planner.PrimaryKeyBounds{Min: 1, Max: 0}, nil
	}
	return planner.PrimaryKeyBounds{Min: lo.Int64, Max: hi.Int64}, nil
}

func (SQLServerChunkBoundsReader) ReadDateTime(
	ctx context.Context, cfg extractor.SQLServerConfig, schema, table, col string,
) (planner.DateBounds, error) {
	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return planner.DateBounds{}, err
	}
	defer db.Close()
	var lo, hi sql.NullTime
	if err := db.QueryRowContext(ctx, extractor.BuildDateBoundsQuery(schema, table, col)).Scan(&lo, &hi); err != nil {
		return planner.DateBounds{}, err
	}
	if !lo.Valid || !hi.Valid {
		return planner.DateBounds{Min: time.Now(), Max: time.Now().AddDate(0, 0, -1)}, nil
	}
	return planner.DateBounds{Min: lo.Time, Max: hi.Time}, nil
}

func (SQLServerChunkBoundsReader) ReadUUID(
	ctx context.Context, cfg extractor.SQLServerConfig, schema, table, col string,
) (planner.UUIDBounds, error) {
	db, err := sql.Open("sqlserver", cfg.ConnectionString())
	if err != nil {
		return planner.UUIDBounds{}, err
	}
	defer db.Close()
	var lo, hi sql.NullString
	if err := db.QueryRowContext(ctx, extractor.BuildUUIDBoundsQuery(schema, table, col)).Scan(&lo, &hi); err != nil {
		return planner.UUIDBounds{}, err
	}
	if !lo.Valid || !hi.Valid {
		return planner.UUIDBounds{}, nil
	}
	return planner.UUIDBounds{Min: strings.ToLower(lo.String), Max: strings.ToLower(hi.String)}, nil
}

// ResolveTableChunks discovers the chunk key, reads bounds, and plans chunks.
func ResolveTableChunks(
	ctx context.Context,
	jobID uuid.UUID,
	src extractor.SQLServerConfig,
	table GoTableDispatchPayload,
	defaultChunkSize int64,
) ([]core.ChunkPlan, ChunkKeyInfo, error) {
	discoverer := SQLServerChunkKeyDiscoverer{}
	boundsReader := SQLServerChunkBoundsReader{}

	key, err := discoverer.DiscoverKey(
		ctx, src, table.SourceSchema, table.TableName,
		table.OrderColumn, table.ColumnTypes,
	)
	if err != nil {
		return nil, key, err
	}

	chunkSize := int64(table.ChunkSize)
	if chunkSize < 1 {
		chunkSize = defaultChunkSize
	}

	switch key.Kind {
	case ChunkKeyDateTime:
		bounds, err := boundsReader.ReadDateTime(ctx, src, table.SourceSchema, table.TableName, key.Column)
		if err != nil {
			return nil, key, err
		}
		daysPerChunk := int(chunkSize / 1000)
		if daysPerChunk < 1 {
			daysPerChunk = 1
		}
		return planner.NewDateChunker(daysPerChunk).Plan(
			jobID, table.SourceSchema, table.TableName, key.Column, bounds,
		), key, nil
	case ChunkKeyUUID:
		bounds, err := boundsReader.ReadUUID(ctx, src, table.SourceSchema, table.TableName, key.Column)
		if err != nil {
			return nil, key, err
		}
		return planner.UUIDChunker{}.Plan(
			jobID, table.SourceSchema, table.TableName, key.Column, bounds,
		), key, nil
	default:
		bounds, err := boundsReader.ReadInteger(ctx, src, table.SourceSchema, table.TableName, key.Column)
		if err != nil {
			return nil, key, err
		}
		return planner.NewPrimaryKeyChunker(chunkSize).Plan(
			jobID, table.SourceSchema, table.TableName, key.Column, bounds,
		), key, nil
	}
}

// BuildExtractOptions maps dispatch payload + chunk key into SQL Server extract hints.
func BuildExtractOptions(table GoTableDispatchPayload, key ChunkKeyInfo, useNoLock bool) extractor.ExtractOptions {
	return extractor.ExtractOptions{
		WhereClause:  table.WhereClause,
		OrderColumn:  table.OrderColumn,
		MaxDOP:       table.SourceMaxDOP,
		NoLock:       useNoLock,
		UUIDKeyRange: key.Kind == ChunkKeyUUID,
	}
}

// ResolveConflictColumns picks UPSERT conflict columns from dispatch or discovered PK.
func ResolveConflictColumns(jobConflict []string, key ChunkKeyInfo) []string {
	if len(jobConflict) > 0 {
		return append([]string(nil), jobConflict...)
	}
	if len(key.Composite) > 0 {
		return append([]string(nil), key.Composite...)
	}
	if key.Column != "" {
		return []string{key.Column}
	}
	return nil
}
