// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc

import (
	"fmt"
	"strings"
)

// quoteIdentPG double-quotes a PostgreSQL identifier.
// Any embedded '"' characters are doubled to prevent identifier injection.
func quoteIdentPG(ident string) string {
	return `"` + strings.ReplaceAll(ident, `"`, `""`) + `"`
}

// quotedTablePG returns a safely-quoted "schema"."table" expression.
func quotedTablePG(schema, table string) string {
	return quoteIdentPG(schema) + "." + quoteIdentPG(table)
}

// ApplyStatement holds the generated parameterised DML and a flag indicating
// whether the statement should be executed at all.
type ApplyStatement struct {
	SQL        string
	Applicable bool
}

// BuildApplyStatement returns the parameterised DML for a single CDC event.
//
//   - INSERT / UPDATE_AFTER → idempotent upsert using ON CONFLICT … DO UPDATE.
//   - DELETE               → DELETE WHERE pk = $1 [AND pk2 = $2 …].
//   - UPDATE_BEFORE        → Applicable = false (before-images are not applied).
//
// All column and table identifiers are double-quoted. Change values are
// represented as positional parameters ($1, $2, …) — never interpolated.
//
// Returns Applicable=false when the operation is an UPDATE_BEFORE or when
// required metadata (columns / pk columns) is absent.
func BuildApplyStatement(schema, table string, op CDCOperation, columns, pkColumns []string) ApplyStatement {
	target := quotedTablePG(schema, table)

	switch op {
	case OpUpdateBefore:
		return ApplyStatement{}

	case OpDelete:
		if len(pkColumns) == 0 {
			return ApplyStatement{}
		}
		parts := make([]string, len(pkColumns))
		for i, c := range pkColumns {
			parts[i] = fmt.Sprintf("%s = $%d", quoteIdentPG(c), i+1)
		}
		return ApplyStatement{
			SQL:        fmt.Sprintf("DELETE FROM %s WHERE %s", target, strings.Join(parts, " AND ")),
			Applicable: true,
		}

	case OpInsert, OpUpdateAfter:
		if len(columns) == 0 || len(pkColumns) == 0 {
			return ApplyStatement{}
		}

		colList := make([]string, len(columns))
		placeholders := make([]string, len(columns))
		for i, c := range columns {
			colList[i] = quoteIdentPG(c)
			placeholders[i] = fmt.Sprintf("$%d", i+1)
		}

		conflictCols := make([]string, len(pkColumns))
		pkSet := make(map[string]bool, len(pkColumns))
		for i, c := range pkColumns {
			conflictCols[i] = quoteIdentPG(c)
			pkSet[c] = true
		}

		var updates []string
		for _, c := range columns {
			if !pkSet[c] {
				q := quoteIdentPG(c)
				updates = append(updates, fmt.Sprintf("%s = EXCLUDED.%s", q, q))
			}
		}

		var onConflict string
		if len(updates) == 0 {
			onConflict = fmt.Sprintf("ON CONFLICT (%s) DO NOTHING", strings.Join(conflictCols, ", "))
		} else {
			onConflict = fmt.Sprintf("ON CONFLICT (%s) DO UPDATE SET %s",
				strings.Join(conflictCols, ", "), strings.Join(updates, ", "))
		}

		return ApplyStatement{
			SQL: fmt.Sprintf("INSERT INTO %s (%s) VALUES (%s) %s",
				target,
				strings.Join(colList, ", "),
				strings.Join(placeholders, ", "),
				onConflict,
			),
			Applicable: true,
		}
	}
	return ApplyStatement{}
}
