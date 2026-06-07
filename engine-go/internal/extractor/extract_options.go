// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

// ExtractOptions configures optional SQL Server extraction hints.
type ExtractOptions struct {
	WhereClause  string
	OrderColumn  string
	MaxDOP       int
	NoLock       bool
	UUIDKeyRange bool
}
