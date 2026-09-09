// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractport

import (
	"strconv"
	"strings"
)

func quoteIdentMSSQL(ident string) string {
	return "[" + strings.ReplaceAll(ident, "]", "]]") + "]"
}

func quotedTableMSSQL(schema, table string) string {
	return quoteIdentMSSQL(schema) + "." + quoteIdentMSSQL(table)
}

func quotedFourPartMSSQL(database, schema, table string) string {
	return quoteIdentMSSQL(database) + "." + quotedTableMSSQL(schema, table)
}

func quotedColumnsMSSQL(columns []string) string {
	quoted := make([]string, len(columns))
	for i, c := range columns {
		quoted[i] = quoteIdentMSSQL(c)
	}
	return strings.Join(quoted, ", ")
}

func requireColumnsMSSQL(columns []string) string {
	if len(columns) == 0 {
		return ""
	}
	return quotedColumnsMSSQL(columns)
}

// BuildSQLServerFullTableQuery returns a parameterized-safe full-table SELECT.
// Identifiers are bracket-quoted; no user values are interpolated.
func BuildSQLServerFullTableQuery(schema, table string, columns []string) string {
	colList := "*"
	if len(columns) > 0 {
		colList = quotedColumnsMSSQL(columns)
	}
	return "SELECT " + colList + " FROM " + quotedTableMSSQL(schema, table)
}

// BuildSQLServerPartitionRowEstimateQuery uses sys.dm_db_partition_stats.
// Schema and table names are @P1/@P2 — never concatenated.
func BuildSQLServerPartitionRowEstimateQuery() string {
	return "" +
		"SELECT COALESCE(SUM(p.row_count), 0) AS row_count " +
		"FROM sys.dm_db_partition_stats AS p " +
		"INNER JOIN sys.objects AS o ON p.object_id = o.object_id " +
		"INNER JOIN sys.schemas AS s ON o.schema_id = s.schema_id " +
		"WHERE s.name = @P1 AND o.name = @P2 AND p.index_id IN (0, 1)"
}

// BuildSQLServerPartitionRowEstimateFallbackQuery uses sys.partitions when the DMV is denied.
func BuildSQLServerPartitionRowEstimateFallbackQuery() string {
	return "" +
		"SELECT COALESCE(SUM(p.rows), 0) AS row_count " +
		"FROM sys.partitions AS p " +
		"INNER JOIN sys.objects AS o ON p.object_id = o.object_id " +
		"INNER JOIN sys.schemas AS s ON o.schema_id = s.schema_id " +
		"WHERE s.name = @P1 AND o.name = @P2 AND p.index_id IN (0, 1)"
}

// BuildSQLServerIntegerRangeSelect is worker-driven key-range extract SQL.
func BuildSQLServerIntegerRangeSelect(schema, table, orderColumn string, columns []string) string {
	cols := requireColumnsMSSQL(columns)
	if cols == "" {
		cols = "*"
	}
	order := quoteIdentMSSQL(orderColumn)
	return "SELECT " + cols + " FROM " + quotedTableMSSQL(schema, table) +
		" WHERE " + order + " >= @P1 AND " + order + " <= @P2 ORDER BY " + order
}

// BuildSQLServerIntegerRangeInsertSelect copies a key range on the same instance (four-part names).
func BuildSQLServerIntegerRangeInsertSelect(
	srcDB, srcSchema, srcTable, tgtDB, tgtSchema, tgtTable, orderColumn string, columns []string,
) string {
	cols := quotedColumnsMSSQL(columns)
	order := quoteIdentMSSQL(orderColumn)
	return "INSERT INTO " + quotedFourPartMSSQL(tgtDB, tgtSchema, tgtTable) +
		" (" + cols + ") SELECT " + cols + " FROM " + quotedFourPartMSSQL(srcDB, srcSchema, srcTable) +
		" WHERE " + order + " >= @P1 AND " + order + " <= @P2"
}

// BuildSQLServerKeysetSelect pages by a strictly advancing unique key (not OFFSET).
// firstBatch uses TOP (@P1) from the start; subsequent batches use WHERE key > @P1 TOP (@P2).
func BuildSQLServerKeysetSelect(schema, table, orderColumn string, columns []string, hasLastKey bool) string {
	cols := requireColumnsMSSQL(columns)
	if cols == "" {
		cols = "*"
	}
	order := quoteIdentMSSQL(orderColumn)
	from := quotedTableMSSQL(schema, table)
	if !hasLastKey {
		return "SELECT TOP (@P1) " + cols + " FROM " + from + " ORDER BY " + order
	}
	return "SELECT TOP (@P2) " + cols + " FROM " + from +
		" WHERE " + order + " > @P1 ORDER BY " + order
}

// BuildSQLServerDeltaSelect copies rows strictly after a watermark (insert-only).
func BuildSQLServerDeltaSelect(schema, table, orderColumn string, columns []string) string {
	cols := requireColumnsMSSQL(columns)
	if cols == "" {
		cols = "*"
	}
	order := quoteIdentMSSQL(orderColumn)
	return "SELECT " + cols + " FROM " + quotedTableMSSQL(schema, table) +
		" WHERE " + order + " > @P1 ORDER BY " + order
}

// BuildSQLServerBoundsQuery returns MIN/MAX of the order column.
func BuildSQLServerBoundsQuery(schema, table, orderColumn string) string {
	order := quoteIdentMSSQL(orderColumn)
	return "SELECT MIN(" + order + ") AS lo, MAX(" + order + ") AS hi FROM " +
		quotedTableMSSQL(schema, table)
}

// BuildSQLServerCountBigQuery is for post-copy validation on small tables only.
func BuildSQLServerCountBigQuery(schema, table string) string {
	return "SELECT COUNT_BIG(*) AS cnt FROM " + quotedTableMSSQL(schema, table)
}

// BuildSQLServerIdentityInsert toggles IDENTITY_INSERT around copies that include identity columns.
func BuildSQLServerIdentityInsert(schema, table string, on bool) string {
	flag := "OFF"
	if on {
		flag = "ON"
	}
	return "SET IDENTITY_INSERT " + quotedTableMSSQL(schema, table) + " " + flag
}

// BuildSQLServerDiscoverIdentityQuery returns identity column names for a table.
func BuildSQLServerDiscoverIdentityQuery() string {
	return "" +
		"SELECT c.name " +
		"FROM sys.columns AS c " +
		"INNER JOIN sys.objects AS o ON c.object_id = o.object_id " +
		"INNER JOIN sys.schemas AS s ON o.schema_id = s.schema_id " +
		"WHERE s.name = @P1 AND o.name = @P2 AND c.is_identity = 1"
}

// BuildSQLServerDiscoverPrimaryKeyQuery returns the first column of a single-column PK plus type name.
func BuildSQLServerDiscoverPrimaryKeyQuery() string {
	return "" +
		"SELECT c.name, ty.name " +
		"FROM sys.indexes AS i " +
		"INNER JOIN sys.index_columns AS ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id " +
		"INNER JOIN sys.columns AS c ON ic.object_id = c.object_id AND ic.column_id = c.column_id " +
		"INNER JOIN sys.types AS ty ON c.user_type_id = ty.user_type_id " +
		"INNER JOIN sys.objects AS o ON i.object_id = o.object_id " +
		"INNER JOIN sys.schemas AS s ON o.schema_id = s.schema_id " +
		"WHERE s.name = @P1 AND o.name = @P2 AND i.is_primary_key = 1 " +
		"ORDER BY ic.key_ordinal"
}

// BuildSQLServerOrderColumnTypeQuery returns the type name of one column.
func BuildSQLServerOrderColumnTypeQuery() string {
	return "" +
		"SELECT ty.name " +
		"FROM sys.columns AS c " +
		"INNER JOIN sys.types AS ty ON c.user_type_id = ty.user_type_id " +
		"INNER JOIN sys.objects AS o ON c.object_id = o.object_id " +
		"INNER JOIN sys.schemas AS s ON o.schema_id = s.schema_id " +
		"WHERE s.name = @P1 AND o.name = @P2 AND c.name = @P3"
}

// BuildSQLServerIntegerRangeSelectLiteral is only for bcp queryout integer keys.
// lo/hi are formatted as decimal integers after the worker type-checked them.
func BuildSQLServerIntegerRangeSelectLiteral(
	database, schema, table, orderColumn string, columns []string, lo, hi int64,
) string {
	cols := requireColumnsMSSQL(columns)
	if cols == "" {
		cols = "*"
	}
	order := quoteIdentMSSQL(orderColumn)
	return "SELECT " + cols + " FROM " + quotedFourPartMSSQL(database, schema, table) +
		" WHERE " + order + " >= " + strconv.FormatInt(lo, 10) +
		" AND " + order + " <= " + strconv.FormatInt(hi, 10) +
		" ORDER BY " + order
}

// QuotedTableMSSQL exports [schema].[table] for bulk-copy destinations.
func QuotedTableMSSQL(schema, table string) string {
	return quotedTableMSSQL(schema, table)
}
