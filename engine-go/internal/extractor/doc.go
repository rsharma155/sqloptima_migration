// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package extractor handles streaming row extraction from SQL Server.
// Pure sub-packages (querybuild, schema) have no database driver dependency
// and are fully unit-testable. The live connection layer (extractor.go) uses
// go-mssqldb and is covered by integration tests.
package extractor
