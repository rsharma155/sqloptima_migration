// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc

import (
	"fmt"
	"sync"
)

// CDCState represents one of the nine lifecycle states of the CDC pipeline.
//
// State-transition diagram (mirrors the Rust implementation §11.2):
//
//	IDLE → STARTING → SNAPSHOTTING → CDC_CATCHUP → CDC_STREAMING
//	                                                    │
//	                         ┌──────────────────────────┼──────────────┐
//	                         ▼          ▼               ▼              ▼
//	                      PAUSED    STOPPING          FAILED       (continues)
//	                         │          │               │
//	                         └►STREAMING └►COMPLETED    └►CDC_CATCHUP (retry)
type CDCState int

const (
	StateIdle         CDCState = iota
	StateStarting
	StateSnapshotting
	StateCDCCatchup
	StateCDCStreaming
	StatePaused
	StateStopping
	StateFailed
	StateCompleted
)

var cdcStateNames = [...]string{
	"IDLE", "STARTING", "SNAPSHOTTING", "CDC_CATCHUP",
	"CDC_STREAMING", "PAUSED", "STOPPING", "FAILED", "COMPLETED",
}

// String satisfies fmt.Stringer.
func (s CDCState) String() string {
	if int(s) < len(cdcStateNames) {
		return cdcStateNames[s]
	}
	return fmt.Sprintf("UNKNOWN(%d)", int(s))
}

// IsTerminal reports whether this state has no outgoing transitions.
func (s CDCState) IsTerminal() bool { return s == StateCompleted }

// canTransitionTo returns true if next is a legal successor of s.
// The adjacency rules match the Rust CDC state machine exactly.
func (s CDCState) canTransitionTo(next CDCState) bool {
	switch s {
	case StateIdle:
		return next == StateStarting
	case StateStarting:
		return next == StateSnapshotting || next == StateFailed
	case StateSnapshotting:
		return next == StateCDCCatchup || next == StateFailed || next == StateStopping
	case StateCDCCatchup:
		return next == StateCDCStreaming || next == StateFailed || next == StateStopping
	case StateCDCStreaming:
		return next == StatePaused || next == StateStopping || next == StateFailed || next == StateCompleted
	case StatePaused:
		return next == StateCDCStreaming || next == StateStopping
	case StateStopping:
		return next == StateCompleted || next == StateFailed
	case StateFailed:
		// Failure can be retried by re-entering CDC catch-up.
		return next == StateCDCCatchup || next == StateStopping
	case StateCompleted:
		return false // terminal
	}
	return false
}

// CDCStateMachine is a goroutine-safe CDC lifecycle guard. It enforces legal
// state transitions and rejects illegal ones with a descriptive error.
type CDCStateMachine struct {
	mu    sync.Mutex
	state CDCState
}

// NewCDCStateMachine creates a machine starting in the IDLE state.
func NewCDCStateMachine() *CDCStateMachine {
	return &CDCStateMachine{state: StateIdle}
}

// State returns the current state (goroutine-safe).
func (m *CDCStateMachine) State() CDCState {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state
}

// TransitionTo attempts to move to next. Returns an error if the transition is
// illegal; the state is left unchanged on error.
func (m *CDCStateMachine) TransitionTo(next CDCState) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.state.canTransitionTo(next) {
		return fmt.Errorf("invalid CDC transition: %s → %s", m.state, next)
	}
	m.state = next
	return nil
}
