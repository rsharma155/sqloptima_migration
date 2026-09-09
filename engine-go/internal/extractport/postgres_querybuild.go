// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package extractport builds parameterized extract SQL for Transfer sources.
package extractport

import (
	"fmt"
	"strings"
)

func quoteIdentPG(ident string) string {
	return `"` + strings.ReplaceAll(ident, `"`, `""`) + `"`
}

func quotedTablePG(schema, table string) string {
	return quoteIdentPG(schema) + "." + quoteIdentPG(table)
}

func quotedColumnsPG(columns []string) string {
	quoted := make([]string, len(columns))
	for i, c := range columns {
		quoted[i] = quoteIdentPG(c)
	}
	return strings.Join(quoted, ", ")
}

// BuildPostgresExtractQuery returns parameterized key-range SQL, or a full-table
// SELECT when orderColumn is empty. Identifiers are double-quoted.
func BuildPostgresExtractQuery(schema, table, orderColumn string, columns []string) string {
	colList := "*"
	if len(columns) > 0 {
		colList = quotedColumnsPG(columns)
	}
	from := quotedTablePG(schema, table)
	if strings.TrimSpace(orderColumn) == "" {
		return fmt.Sprintf("SELECT %s FROM %s", colList, from)
	}
	order := quoteIdentPG(orderColumn)
	return fmt.Sprintf(
		"SELECT %s FROM %s WHERE %s >= $1 AND %s <= $2 ORDER BY %s",
		colList, from, order, order, order,
	)
}

// BuildPostgresBoundsQuery returns MIN/MAX for integer/text key chunking.
func BuildPostgresBoundsQuery(schema, table, orderColumn string) string {
	order := quoteIdentPG(orderColumn)
	return fmt.Sprintf(
		`SELECT MIN(%s) AS lo, MAX(%s) AS hi FROM %s`,
		order, order, quotedTablePG(schema, table),
	)
}
