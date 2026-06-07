// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package cdc implements SQL Server Change Data Capture primitives.
// It is intentionally pure (no database drivers, no async I/O) so that every
// component can be unit-tested without a running SQL Server instance.
package cdc
