// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
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
