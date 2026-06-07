// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"fmt"
	"strings"
)

// quoteIdentPG double-quotes a PostgreSQL identifier.
// Any embedded '"' is doubled to prevent identifier injection.
func quoteIdentPG(ident string) string {
	return `"` + strings.ReplaceAll(ident, `"`, `""`) + `"`
}

// BuildCopyStatement returns a binary COPY FROM STDIN statement.
// All identifiers are double-quoted; injection via crafted names is neutralised.
//
//	COPY "schema"."table" ("col1", "col2") FROM STDIN WITH (FORMAT binary)
//
// When columns is empty, PostgreSQL expects all columns in table definition order.
func BuildCopyStatement(schema, table string, columns []string) string {
	target := fmt.Sprintf("%s.%s", quoteIdentPG(schema), quoteIdentPG(table))
	if len(columns) == 0 {
		return fmt.Sprintf("COPY %s FROM STDIN WITH (FORMAT binary)", target)
	}
	quoted := make([]string, len(columns))
	for i, c := range columns {
		quoted[i] = quoteIdentPG(c)
	}
	return fmt.Sprintf("COPY %s (%s) FROM STDIN WITH (FORMAT binary)",
		target, strings.Join(quoted, ", "))
}
