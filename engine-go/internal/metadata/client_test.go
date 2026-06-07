// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata_test

// Integration tests for MetadataClient require a live PostgreSQL instance.
// Run with: go test -tags integration ./internal/metadata/...
//
// Example:
//
//	METADATA_DB_URL="postgresql://postgres:postgres@localhost:5432/migration_platform" \
//	    go test -tags integration -v ./internal/metadata/...

// Unit coverage for this package is intentionally limited because every method
// in Client and CommandPoller requires a real database connection. The command
// semantics are verified in poller_test.go via the shared core.Command type.
