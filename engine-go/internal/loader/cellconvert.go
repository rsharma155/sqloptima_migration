// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"fmt"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// pgEpochDays is the number of days between the Unix epoch (1970-01-01) and
// the PostgreSQL epoch (2000-01-01). Applied when converting CellDate and
// CellTimestampMicros from Unix-epoch values to PostgreSQL-epoch values.
const pgEpochDays int32 = 10957

// pgEpochMicros is pgEpochDays converted to microseconds.
const pgEpochMicros int64 = int64(pgEpochDays) * 24 * 3600 * 1_000_000

// ToCopyValue converts a core.CellValue (using Unix epoch for temporals) to
// the corresponding CopyValue (using PostgreSQL epoch for temporals).
func ToCopyValue(c core.CellValue) CopyValue {
	return ToCopyValueForColumn(c, core.LogicalUtf8)
}

// ToCopyValueForColumn converts a cell using column logical type (required for numeric).
func ToCopyValueForColumn(c core.CellValue, lt core.LogicalType) CopyValue {
	if lt == core.LogicalDecimal {
		switch c.(type) {
		case core.CellNull:
			return CopyNull{}
		case core.CellStr:
			return CopyNumeric{V: c.(core.CellStr).V}
		case core.CellF64:
			return CopyNumeric{V: fmt.Sprintf("%g", c.(core.CellF64).V)}
		}
	}
	switch v := c.(type) {
	case core.CellNull:
		return CopyNull{}
	case core.CellBool:
		return CopyBool{V: v.V}
	case core.CellI16:
		return CopyInt16{V: v.V}
	case core.CellI32:
		return CopyInt32{V: v.V}
	case core.CellI64:
		return CopyInt64{V: v.V}
	case core.CellF32:
		return CopyFloat32{V: v.V}
	case core.CellF64:
		return CopyFloat64{V: v.V}
	case core.CellStr:
		return CopyText{V: v.V}
	case core.CellBin:
		return CopyBytes{V: v.V}
	case core.CellDate:
		return CopyDate{V: v.V - pgEpochDays}
	case core.CellTimestampMicros:
		return CopyTimestampMicros{V: v.V - pgEpochMicros}
	case core.CellTimeMicros:
		return CopyTimeMicros{V: v.V}
	case core.CellUUID:
		return CopyUUID{V: v.V}
	default:
		return CopyNull{}
	}
}

// CellsToCopyRow converts an extracted row to COPY values using schema column types.
func CellsToCopyRow(schema extractor.ExtractionSchema, cells []core.CellValue) ([]CopyValue, error) {
	if len(cells) != len(schema.Columns) {
		return nil, fmt.Errorf("row width mismatch: %d cells, %d columns", len(cells), len(schema.Columns))
	}
	row := make([]CopyValue, len(cells))
	for i, c := range cells {
		lt := schema.Columns[i].LogicalType
		if lt == core.LogicalDecimal {
			if _, ok := c.(core.CellNull); !ok {
				if _, err := encodeNumericBinaryString(decimalStringFromCell(c)); err != nil {
					return nil, fmt.Errorf("column %s: %w", schema.Columns[i].Name, err)
				}
			}
		}
		row[i] = ToCopyValueForColumn(c, lt)
	}
	return row, nil
}

func decimalStringFromCell(c core.CellValue) string {
	switch v := c.(type) {
	case core.CellStr:
		return v.V
	case core.CellF64:
		return fmt.Sprintf("%g", v.V)
	case core.CellNull:
		return "0"
	default:
		return fmt.Sprintf("%v", c)
	}
}
