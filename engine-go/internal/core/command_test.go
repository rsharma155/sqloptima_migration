// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestCommandPauseIsPause(t *testing.T) {
	if !core.CommandPause.IsPause() {
		t.Fatal("PAUSE must be pause")
	}
	if core.CommandPause.IsStop() {
		t.Fatal("PAUSE must not be stop")
	}
}

func TestCommandStopIsStop(t *testing.T) {
	if !core.CommandStop.IsStop() {
		t.Fatal("STOP must be stop")
	}
}

func TestCommandCancelIsStop(t *testing.T) {
	if !core.CommandCancel.IsStop() {
		t.Fatal("CANCEL must be classified as stop")
	}
}

func TestCommandResumeIsNeither(t *testing.T) {
	if core.CommandResume.IsPause() || core.CommandResume.IsStop() {
		t.Fatal("RESUME must be neither pause nor stop")
	}
}

func TestParseCommandKnownValues(t *testing.T) {
	for _, want := range []core.Command{
		core.CommandStart,
		core.CommandPause, core.CommandResume, core.CommandStop, core.CommandCancel,
	} {
		got, err := core.ParseCommand(string(want))
		if err != nil {
			t.Fatalf("ParseCommand(%q) unexpected error: %v", want, err)
		}
		if got != want {
			t.Fatalf("ParseCommand(%q) = %q, want %q", want, got, want)
		}
	}
}

func TestParseCommandUnknown(t *testing.T) {
	if _, err := core.ParseCommand("NUKE"); err == nil {
		t.Fatal("expected error for unknown command")
	}
}
