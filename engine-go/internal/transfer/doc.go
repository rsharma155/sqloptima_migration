// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package transfer is the Go data-plane loop for Cross-Database Transfer jobs.
// It claims transfer_jobs only — never migration_jobs.
package transfer
