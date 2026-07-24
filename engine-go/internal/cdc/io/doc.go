// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/doc.go
// Purpose: Package documentation for the CDC live I/O adapter layer
// Domain: Replication / CDC (data plane infrastructure)
// Author: Ravi Sharma

// Package cdcio is the infrastructure adapter that connects the pure
// [cdc] domain package to live databases:
//
//   - EventSource  — read change rows from SQL Server CDC CT tables (go-mssqldb)
//   - EventApplier — apply UPSERT/DELETE to PostgreSQL (pgx/v5)
//
// Domain logic (LSN ordering, operation codes, SQL builders, state machine)
// stays in engine-go/internal/cdc with no driver imports. This package only
// owns I/O, scanning, parameter binding, and the poll loop that drives the
// CDC state machine.
//
// Enable the optional env worker with MIGRATION_CDC_ENABLED=1.
package cdcio
