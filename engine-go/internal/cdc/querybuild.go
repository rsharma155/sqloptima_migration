// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc

import (
	"fmt"
	"strings"
)

// quoteIdentMSSQL bracket-quotes a SQL Server identifier.
// Any embedded ']' characters are doubled to prevent identifier injection.
func quoteIdentMSSQL(ident string) string {
	return "[" + strings.ReplaceAll(ident, "]", "]]") + "]"
}

// BuildCaptureReadQuery returns the parameterised SQL that reads all CDC
// changes strictly after the checkpoint LSN.
//
// The caller must bind the current checkpoint LSN to positional parameter @P1.
// No LSN value is ever interpolated into the SQL text.
//
//	SELECT __$start_lsn, __$seqval, __$operation
//	FROM cdc.[<capture_instance>_CT]
//	WHERE __$start_lsn > @P1
//	ORDER BY __$start_lsn, __$seqval
func BuildCaptureReadQuery(captureInstance string) string {
	return BuildCaptureReadQueryWithColumns(captureInstance, nil, 0)
}

// BuildCaptureReadQueryWithColumns returns a parameterised CT read that also
// projects the named data columns (in addition to CDC metadata columns).
// When limit > 0, a TOP (n) clause is included. Column identifiers are bracket-quoted.
func BuildCaptureReadQueryWithColumns(captureInstance string, columns []string, limit int) string {
	ct := quoteIdentMSSQL(captureInstance + "_CT")
	var colList strings.Builder
	colList.WriteString("__$start_lsn, __$seqval, __$operation")
	for _, c := range columns {
		colList.WriteString(", ")
		colList.WriteString(quoteIdentMSSQL(c))
	}
	top := ""
	if limit > 0 {
		top = fmt.Sprintf("TOP (%d) ", limit)
	}
	return fmt.Sprintf(
		"SELECT %s%s FROM cdc.%s WHERE __$start_lsn > @P1 ORDER BY __$start_lsn, __$seqval",
		top,
		colList.String(),
		ct,
	)
}

// BuildMaxLSNQuery returns the SQL to retrieve the current maximum LSN.
// Used to bound catch-up reads and measure CDC lag.
func BuildMaxLSNQuery() string {
	return "SELECT sys.fn_cdc_get_max_lsn() AS max_lsn"
}

// BuildCDCEnabledQuery returns the SQL to check whether CDC is enabled for
// the current database.
func BuildCDCEnabledQuery() string {
	return "SELECT is_cdc_enabled FROM sys.databases WHERE database_id = DB_ID()"
}
