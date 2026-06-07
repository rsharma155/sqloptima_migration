// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

import "github.com/ravisharma/sql-optima/engine-go/internal/core"

// ExtractionColumn describes a single column in the extraction schema,
// combining the column name with its normalised logical type.
type ExtractionColumn struct {
	Name        string
	LogicalType core.LogicalType
	IsNullable  bool
}

// ExtractionSchema holds the ordered list of columns to extract from SQL Server.
// The ordering must match the SELECT column list in the extraction query.
type ExtractionSchema struct {
	Columns []ExtractionColumn
}

// ColumnNames returns the ordered column names suitable for passing to
// BuildExtractQuery and BuildCopyStatement.
func (s *ExtractionSchema) ColumnNames() []string {
	names := make([]string, len(s.Columns))
	for i, c := range s.Columns {
		names[i] = c.Name
	}
	return names
}

// FromTableMeta derives an ExtractionSchema from discovery metadata.
// LOB columns (LargeUtf8 / LargeBinary) are included but flagged for the
// streaming path via LogicalType.IsLOB().
func FromTableMeta(meta core.TableMeta) ExtractionSchema {
	cols := make([]ExtractionColumn, 0, len(meta.Columns))
	for _, cm := range meta.Columns {
		lt := core.MapSQLServerType(cm.DataType, cm.MaxLength)
		cols = append(cols, ExtractionColumn{
			Name:        cm.ColumnName,
			LogicalType: lt,
			IsNullable:  cm.IsNullable,
		})
	}
	return ExtractionSchema{Columns: cols}
}
