// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

// ExtractOptions configures optional SQL Server extraction hints.
type ExtractOptions struct {
	WhereClause  string
	OrderColumn  string
	MaxDOP       int
	NoLock       bool
	UUIDKeyRange   bool
	StringKeyRange bool
    // InlineTextLOBs selects nvarchar(max)/varchar(max)/text in the main row query
    // instead of per-row SUBSTRING round-trips. Safe for NULL-heavy text columns.
    InlineTextLOBs bool
    // InlineBinaryLOBs selects varbinary(max)/image in the main row query instead of
    // per-row SUBSTRING round-trips. Bounded varbinary columns still load inline.
    InlineBinaryLOBs bool
    // ColumnExtractCasts maps column name → SQL Server SELECT expression (user-approved casts).
    ColumnExtractCasts map[string]string
}
