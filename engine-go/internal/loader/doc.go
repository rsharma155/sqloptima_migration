// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package loader handles high-throughput data loading into PostgreSQL via
// binary COPY FROM STDIN. Pure sub-packages (statement, pgbinary) carry no
// driver dependency and are covered by byte-exact unit tests. The live I/O
// layer (loader.go) uses pgx/v5 and is covered by integration tests.
package loader
