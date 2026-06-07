// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// SplitSchemaForLOBStreaming returns a SELECT schema without LOB columns (PK always included).
func SplitSchemaForLOBStreaming(schema ExtractionSchema, pkColumn string) (ExtractionSchema, []int) {
	var lobIndexes []int
	for i, c := range schema.Columns {
		if c.LogicalType.IsLOB() {
			lobIndexes = append(lobIndexes, i)
		}
	}
	if len(lobIndexes) == 0 {
		return schema, nil
	}

	seen := make(map[string]struct{}, len(schema.Columns))
	var queryCols []ExtractionColumn
	addCol := func(c ExtractionColumn) {
		if _, ok := seen[c.Name]; ok {
			return
		}
		seen[c.Name] = struct{}{}
		queryCols = append(queryCols, c)
	}

	for _, c := range schema.Columns {
		if c.LogicalType.IsLOB() {
			continue
		}
		addCol(c)
	}
	if pkColumn != "" {
		for _, c := range schema.Columns {
			if c.Name == pkColumn {
				addCol(c)
				break
			}
		}
	}
	return ExtractionSchema{Columns: queryCols}, lobIndexes
}

func pkValueFromRow(querySchema ExtractionSchema, cells []core.CellValue, pkColumn string) (any, error) {
	for i, c := range querySchema.Columns {
		if c.Name == pkColumn {
			return cellToDriverValue(cells[i])
		}
	}
	return nil, fmt.Errorf("pk column %q not found in extract row", pkColumn)
}

func cellToDriverValue(c core.CellValue) (any, error) {
	switch v := c.(type) {
	case core.CellNull:
		return nil, nil
	case core.CellI16:
		return int64(v.V), nil
	case core.CellI32:
		return int64(v.V), nil
	case core.CellI64:
		return v.V, nil
	case core.CellStr:
		return v.V, nil
	case core.CellUUID:
		return v.V[:], nil
	default:
		return fmt.Sprintf("%v", c), nil
	}
}

func lobCellFromData(data any, lt core.LogicalType) core.CellValue {
	if data == nil {
		return core.CellNull{}
	}
	switch lt {
	case core.LogicalLargeBinary:
		if b, ok := data.([]byte); ok {
			return core.CellBin{V: b}
		}
	case core.LogicalLargeUtf8:
		switch v := data.(type) {
		case string:
			return core.CellStr{V: v}
		case []byte:
			return core.CellStr{V: string(v)}
		}
	}
	if b, ok := data.([]byte); ok {
		return core.CellBin{V: b}
	}
	if s, ok := data.(string); ok {
		return core.CellStr{V: s}
	}
	return core.CellNull{}
}

// EnrichRowWithLOBs fetches LOB columns via SUBSTRING and merges into the full row shape.
func EnrichRowWithLOBs(
	ctx context.Context,
	db *sql.DB,
	schema ExtractionSchema,
	lobIndexes []int,
	querySchema ExtractionSchema,
	partial []core.CellValue,
	tableSchema, table, pkColumn string,
	pkValue any,
	reader *LobChunkReader,
) ([]core.CellValue, error) {
	if reader == nil {
		reader = DefaultLobChunkReader()
	}
	full := make([]core.CellValue, len(schema.Columns))
	q := 0
	for i, col := range schema.Columns {
		if containsInt(lobIndexes, i) {
			data, err := reader.ReadLOB(ctx, db, tableSchema, table, pkColumn, col.Name, pkValue)
			if err != nil {
				return nil, err
			}
			full[i] = lobCellFromData(data, col.LogicalType)
			continue
		}
		if q >= len(partial) {
			return nil, fmt.Errorf("partial row too short for schema merge")
		}
		full[i] = partial[q]
		q++
	}
	return full, nil
}

func containsInt(xs []int, v int) bool {
	for _, x := range xs {
		if x == v {
			return true
		}
	}
	return false
}
