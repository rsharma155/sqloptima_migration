// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

// These tests verify command semantics without requiring a live database.

func TestCommandPauseIsPause(t *testing.T) {
	if !core.CommandPause.IsPause() {
		t.Error("PAUSE must be classified as pause")
	}
	if core.CommandPause.IsStop() {
		t.Error("PAUSE must not be classified as stop")
	}
}

func TestCommandStopIsStop(t *testing.T) {
	if !core.CommandStop.IsStop() {
		t.Error("STOP must be classified as stop")
	}
}

func TestCommandCancelIsStop(t *testing.T) {
	if !core.CommandCancel.IsStop() {
		t.Error("CANCEL must be classified as stop")
	}
}

func TestCommandResumeIsNeither(t *testing.T) {
	if core.CommandResume.IsPause() || core.CommandResume.IsStop() {
		t.Error("RESUME must be neither pause nor stop")
	}
}

func TestListenSQLAllowList(t *testing.T) {
	sql, err := metadata.ListenSQL("transfer_commands")
	if err != nil || sql != "LISTEN transfer_commands" {
		t.Fatalf("transfer_commands: %q %v", sql, err)
	}
	sql, err = metadata.ListenSQL("migration_commands")
	if err != nil || sql != "LISTEN migration_commands" {
		t.Fatalf("migration_commands: %q %v", sql, err)
	}
	if _, err = metadata.ListenSQL("drop_table"); err == nil {
		t.Fatal("unknown channel must be rejected")
	}
}
