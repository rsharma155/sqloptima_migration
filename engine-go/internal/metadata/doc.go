// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package metadata provides the PostgreSQL metadata-repository client used by
// the engine to read commands, write chunk progress, and sync job status.
// The metadata DB is shared between the Python control plane and this Go data plane.
package metadata
