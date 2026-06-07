// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

// Package queue provides a crash-safe, embedded key-value store for migration
// chunk lifecycle state. It uses bbolt (pure Go B+tree) as the storage engine,
// replacing the Rust implementation's RocksDB dependency and eliminating the
// ~4–5 GB native-library build artefact.
package queue
