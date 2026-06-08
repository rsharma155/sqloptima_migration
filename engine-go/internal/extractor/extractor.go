// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	"github.com/google/uuid"
	// Register the SQL Server driver side-effect.
	_ "github.com/microsoft/go-mssqldb"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// Extractor streams rows from a SQL Server table chunk into a channel of
// CellValue slices. Each element of the channel is one row, represented as
// an ordered slice matching the ExtractionSchema column order.
//
// Usage:
//
//	out := make(chan []core.CellValue, 32)
//	go func() {
//	    defer close(out)
//	    extractor.Run(ctx, cfg, chunk, schema, out)
//	}()
//	for row := range out { ... }
type Extractor struct {
	cfg SQLServerConfig
}

// New creates an Extractor with the given SQL Server connection configuration.
func New(cfg SQLServerConfig) *Extractor { return &Extractor{cfg: cfg} }

// Run opens a SQL Server connection, executes the chunk extraction query, and
// sends each decoded row to out. Closes the connection when done; does NOT
// close the channel (caller's responsibility).
//
// This method is the live I/O layer. Integration tests cover it with a real
// SQL Server instance (build tag: integration).
func (e *Extractor) Run(ctx context.Context, chunk core.ChunkPlan,
	schema ExtractionSchema, out chan<- []core.CellValue) error {
	return e.RunWithOptions(ctx, chunk, schema, ExtractOptions{}, out)
}

// RunWithOptions executes the chunk query with optional NOLOCK, WHERE, ORDER BY, and MAXDOP hints.
func (e *Extractor) RunWithOptions(ctx context.Context, chunk core.ChunkPlan,
	schema ExtractionSchema, opts ExtractOptions, out chan<- []core.CellValue) error {

	db, err := sql.Open("sqlserver", e.cfg.ConnectionString())
	if err != nil {
		return fmt.Errorf("open SQL Server connection: %w", err)
	}
	defer db.Close()

	db.SetConnMaxLifetime(5 * time.Minute)
	db.SetMaxOpenConns(1)

	querySchema, lobIndexes := SplitSchemaForLOBStreaming(schema, chunk.PKColumn, opts)
	lobReader := DefaultLobChunkReader()

	query := BuildExtractQueryWithOptions(
		chunk.TableSchema, chunk.TableName,
		chunk.PKColumn, querySchema.ColumnNames(), opts,
	)

	rows, err := db.QueryContext(ctx, query,
		sql.Named("P1", chunk.StartKey),
		sql.Named("P2", chunk.EndKey),
	)
	if err != nil {
		return fmt.Errorf("execute extract query: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		partial, err := scanRow(rows, querySchema)
		if err != nil {
			return fmt.Errorf("scan row: %w", err)
		}
		var cells []core.CellValue
		if len(lobIndexes) > 0 {
			pkVal, err := pkValueFromRow(querySchema, partial, chunk.PKColumn)
			if err != nil {
				return err
			}
			cells, err = EnrichRowWithLOBs(
				ctx, db, schema, lobIndexes, querySchema, partial,
				chunk.TableSchema, chunk.TableName, chunk.PKColumn, pkVal, lobReader,
			)
			if err != nil {
				return fmt.Errorf("read LOB columns: %w", err)
			}
		} else {
			cells = partial
		}
		select {
		case out <- cells:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return rows.Err()
}

// scanRow reads the current row from *sql.Rows and converts each column value
// to the matching CellValue type using the ExtractionSchema for type guidance.
func scanRow(rows *sql.Rows, schema ExtractionSchema) ([]core.CellValue, error) {
	// Scan into interface{} first, then convert to typed CellValue.
	raw := make([]interface{}, len(schema.Columns))
	ptrs := make([]interface{}, len(raw))
	for i := range raw {
		ptrs[i] = &raw[i]
	}
	if err := rows.Scan(ptrs...); err != nil {
		return nil, err
	}

	cells := make([]core.CellValue, len(schema.Columns))
	for i, col := range schema.Columns {
		cells[i] = convertCell(raw[i], col.LogicalType)
	}
	return cells, nil
}

// convertCell maps a raw database/sql value to the appropriate CellValue type.
// The go-mssqldb driver surfaces values as Go native types (int64, float64,
// string, []byte, time.Time, bool, etc.).
func convertCell(v interface{}, lt core.LogicalType) core.CellValue {
	if v == nil {
		return core.CellNull{}
	}
	switch lt {
	case core.LogicalBool:
		if b, ok := v.(bool); ok {
			return core.CellBool{V: b}
		}
	case core.LogicalInt16:
		switch n := v.(type) {
		case int64:
			return core.CellI16{V: int16(n)}
		case int32:
			return core.CellI16{V: int16(n)}
		}
	case core.LogicalInt32:
		switch n := v.(type) {
		case int64:
			return core.CellI32{V: int32(n)}
		case int32:
			return core.CellI32{V: n}
		case int:
			return core.CellI32{V: int32(n)}
		}
	case core.LogicalInt64:
		if n, ok := v.(int64); ok {
			return core.CellI64{V: n}
		}
	case core.LogicalFloat32:
		if f, ok := v.(float64); ok {
			return core.CellF32{V: float32(f)}
		}
	case core.LogicalFloat64:
		if f, ok := v.(float64); ok {
			return core.CellF64{V: f}
		}
	case core.LogicalDecimal:
		switch n := v.(type) {
		case float64:
			return core.CellF64{V: n}
		case string:
			return core.CellStr{V: n}
		case []byte:
			return core.CellStr{V: string(n)}
		}
	case core.LogicalUtf8, core.LogicalLargeUtf8:
		if s, ok := v.(string); ok {
			return core.CellStr{V: s}
		}
	case core.LogicalBinary, core.LogicalLargeBinary:
		if b, ok := v.([]byte); ok {
			return core.CellBin{V: b}
		}
	case core.LogicalDate:
		if t, ok := v.(time.Time); ok {
			// Days since Unix epoch (1970-01-01).
			days := int32(t.Unix() / 86400)
			return core.CellDate{V: days}
		}
	case core.LogicalTimestamp, core.LogicalTimestampTz:
		if t, ok := v.(time.Time); ok {
			return core.CellTimestampMicros{V: t.UnixMicro()}
		}
	case core.LogicalTime:
		if t, ok := v.(time.Time); ok {
			micros := int64(t.Hour())*3_600_000_000 +
				int64(t.Minute())*60_000_000 +
				int64(t.Second())*1_000_000 +
				int64(t.Nanosecond())/1_000
			return core.CellTimeMicros{V: micros}
		}
	case core.LogicalUUID:
		if b, ok := v.([]byte); ok && len(b) == 16 {
			var arr [16]byte
			copy(arr[:], b)
			return core.CellUUID{V: arr}
		}
		if s, ok := v.(string); ok {
			if u, err := uuid.Parse(s); err == nil {
				return core.CellUUID{V: u}
			}
		}
	}
	// Fallback: stringify unsupported or unexpected types.
	return core.CellStr{V: fmt.Sprintf("%v", v)}
}
