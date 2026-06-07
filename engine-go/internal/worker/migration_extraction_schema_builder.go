// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"strings"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// BuildMigrationExtractionSchema builds an extraction schema from dispatch metadata.
// When columnTypes is empty every column defaults to LogicalUtf8 (legacy Phase 3).
func BuildMigrationExtractionSchema(
	columnNames []string,
	columnTypes map[string]string,
) extractor.ExtractionSchema {
	cols := make([]extractor.ExtractionColumn, 0, len(columnNames))
	for _, name := range columnNames {
		lt := core.LogicalUtf8
		if columnTypes != nil {
			if typeName, ok := columnTypes[name]; ok && typeName != "" {
				lt = core.MapSQLServerType(typeName, sqlServerMaxLengthFromTypeName(typeName))
			}
		}
		cols = append(cols, extractor.ExtractionColumn{
			Name:        name,
			LogicalType: lt,
			IsNullable:  true,
		})
	}
	return extractor.ExtractionSchema{Columns: cols}
}

// sqlServerMaxLengthFromTypeName returns -1 only for explicit (max) types.
func sqlServerMaxLengthFromTypeName(typeName string) int32 {
	if strings.Contains(strings.ToLower(strings.TrimSpace(typeName)), "(max)") {
		return -1
	}
	return 0
}

// NormalizeDispatchColumnType strips precision/scale for MapSQLServerType input.
func NormalizeDispatchColumnType(typeName string) string {
	base := strings.TrimSpace(typeName)
	if i := strings.IndexByte(base, '('); i >= 0 {
		base = strings.TrimSpace(base[:i])
	}
	return base
}
