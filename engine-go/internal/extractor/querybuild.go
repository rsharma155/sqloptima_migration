// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

import (
	"fmt"
	"strings"
)

// quoteIdentMSSQL bracket-quotes a SQL Server identifier.
func quoteIdentMSSQL(ident string) string {
	return "[" + strings.ReplaceAll(ident, "]", "]]") + "]"
}

func quotedTableMSSQL(schema, table string) string {
	return quoteIdentMSSQL(schema) + "." + quoteIdentMSSQL(table)
}

func tableFromClause(schema, table string, noLock bool) string {
	tbl := quotedTableMSSQL(schema, table)
	if noLock {
		return tbl + " WITH (NOLOCK)"
	}
	return tbl
}

// BuildExtractQuery returns parameterised chunk-extraction SQL for SQL Server.
func BuildExtractQuery(schema, table, pkCol string, columns []string) string {
	return BuildExtractQueryWithOptions(schema, table, pkCol, columns, ExtractOptions{})
}

// BuildExtractQueryWithOptions supports NOLOCK, optional WHERE, ORDER BY override, MAXDOP, UUID casts.
func BuildExtractQueryWithOptions(
	schema, table, pkCol string, columns []string, opts ExtractOptions,
) string {
	var colList string
	if len(columns) == 0 {
		colList = "*"
	} else {
		quoted := make([]string, len(columns))
		for i, c := range columns {
			quoted[i] = quoteIdentMSSQL(c)
		}
		colList = strings.Join(quoted, ", ")
	}

	orderCol := pkCol
	if opts.OrderColumn != "" {
		orderCol = opts.OrderColumn
	}
	order := quoteIdentMSSQL(orderCol)

	var pkExpr string
	if opts.UUIDKeyRange {
		pkExpr = fmt.Sprintf("CAST(%s AS CHAR(36))", quoteIdentMSSQL(pkCol))
	} else {
		pkExpr = quoteIdentMSSQL(pkCol)
	}

	where := fmt.Sprintf("%s >= @P1 AND %s <= @P2", pkExpr, pkExpr)
	if strings.TrimSpace(opts.WhereClause) != "" {
		where = where + " AND (" + strings.TrimSpace(opts.WhereClause) + ")"
	}

	query := fmt.Sprintf(
		"SELECT %s FROM %s WHERE %s ORDER BY %s",
		colList, tableFromClause(schema, table, opts.NoLock), where, order,
	)
	if opts.MaxDOP > 0 {
		query += fmt.Sprintf(" OPTION (MAXDOP %d)", opts.MaxDOP)
	}
	return query
}

// BuildCountQuery returns a COUNT_BIG(*) for a table.
func BuildCountQuery(schema, table string) string {
	return fmt.Sprintf("SELECT COUNT_BIG(*) FROM %s", quotedTableMSSQL(schema, table))
}

// BuildBoundsQuery returns MIN/MAX for an integer-like PK column.
func BuildBoundsQuery(schema, table, pkCol string) string {
	pk := quoteIdentMSSQL(pkCol)
	return fmt.Sprintf(
		"SELECT MIN(%s) AS lo, MAX(%s) AS hi FROM %s",
		pk, pk, quotedTableMSSQL(schema, table),
	)
}

// BuildDateBoundsQuery returns MIN/MAX for a datetime PK column.
func BuildDateBoundsQuery(schema, table, col string) string {
	c := quoteIdentMSSQL(col)
	return fmt.Sprintf(
		"SELECT MIN(%s) AS lo, MAX(%s) AS hi FROM %s",
		c, c, quotedTableMSSQL(schema, table),
	)
}

// BuildUUIDBoundsQuery returns lexicographic MIN/MAX for a uniqueidentifier column.
func BuildUUIDBoundsQuery(schema, table, col string) string {
	c := quoteIdentMSSQL(col)
	expr := fmt.Sprintf("CAST(%s AS CHAR(36))", c)
	return fmt.Sprintf(
		"SELECT MIN(%s) AS lo, MAX(%s) AS hi FROM %s",
		expr, expr, quotedTableMSSQL(schema, table),
	)
}
