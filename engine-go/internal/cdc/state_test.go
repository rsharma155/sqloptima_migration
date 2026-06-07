// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func newMachine() *cdc.CDCStateMachine { return cdc.NewCDCStateMachine() }

func advance(t *testing.T, m *cdc.CDCStateMachine, states ...cdc.CDCState) {
	t.Helper()
	for _, s := range states {
		if err := m.TransitionTo(s); err != nil {
			t.Fatalf("TransitionTo(%s) failed: %v", s, err)
		}
	}
}

func TestHappyPathRunsToStreaming(t *testing.T) {
	m := newMachine()
	advance(t, m,
		cdc.StateStarting,
		cdc.StateSnapshotting,
		cdc.StateCDCCatchup,
		cdc.StateCDCStreaming,
	)
	if m.State() != cdc.StateCDCStreaming {
		t.Errorf("state = %s, want CDC_STREAMING", m.State())
	}
}

func TestCannotSkipSnapshot(t *testing.T) {
	m := newMachine()
	advance(t, m, cdc.StateStarting)
	if err := m.TransitionTo(cdc.StateCDCStreaming); err == nil {
		t.Error("Starting → CDCStreaming must be rejected")
	}
}

func TestPauseAndResume(t *testing.T) {
	m := newMachine()
	advance(t, m,
		cdc.StateStarting, cdc.StateSnapshotting,
		cdc.StateCDCCatchup, cdc.StateCDCStreaming,
	)
	advance(t, m, cdc.StatePaused, cdc.StateCDCStreaming)
	if m.State() != cdc.StateCDCStreaming {
		t.Errorf("state after resume = %s, want CDC_STREAMING", m.State())
	}
}

func TestFailureCanRetryViaCatchup(t *testing.T) {
	m := newMachine()
	advance(t, m,
		cdc.StateStarting, cdc.StateSnapshotting,
		cdc.StateCDCCatchup, cdc.StateCDCStreaming, cdc.StateFailed,
	)
	advance(t, m, cdc.StateCDCCatchup) // retry
	if m.State() != cdc.StateCDCCatchup {
		t.Errorf("state after retry = %s, want CDC_CATCHUP", m.State())
	}
}

func TestCompletedIsTerminal(t *testing.T) {
	m := newMachine()
	advance(t, m,
		cdc.StateStarting, cdc.StateSnapshotting,
		cdc.StateCDCCatchup, cdc.StateCDCStreaming, cdc.StateCompleted,
	)
	if !m.State().IsTerminal() {
		t.Error("COMPLETED must be terminal")
	}
	if err := m.TransitionTo(cdc.StateCDCStreaming); err == nil {
		t.Error("transition from COMPLETED must be rejected")
	}
}

func TestInvalidTransitionPreservesState(t *testing.T) {
	m := newMachine()
	// IDLE → CDCStreaming is illegal
	_ = m.TransitionTo(cdc.StateCDCStreaming)
	if m.State() != cdc.StateIdle {
		t.Errorf("state after illegal transition = %s, want IDLE", m.State())
	}
}

func TestStoppingFromStreamingThenCompleted(t *testing.T) {
	m := newMachine()
	advance(t, m,
		cdc.StateStarting, cdc.StateSnapshotting,
		cdc.StateCDCCatchup, cdc.StateCDCStreaming,
		cdc.StateStopping, cdc.StateCompleted,
	)
	if m.State() != cdc.StateCompleted {
		t.Errorf("state = %s, want COMPLETED", m.State())
	}
}

func TestStartingCanFailFast(t *testing.T) {
	m := newMachine()
	advance(t, m, cdc.StateStarting, cdc.StateFailed)
	if m.State() != cdc.StateFailed {
		t.Errorf("state = %s, want FAILED", m.State())
	}
}
