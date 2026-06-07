// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core

import (
	"errors"
	"fmt"

	"github.com/google/uuid"
)

// Sentinel errors — callers use errors.Is() for matching.
var (
	ErrChunkNotFound          = errors.New("chunk not found")
	ErrJobNotFound            = errors.New("job not found")
	ErrInvalidStateTransition = errors.New("invalid state transition")
	ErrQueueFailure           = errors.New("queue failure")
	ErrDatabaseFailure        = errors.New("database failure")
	ErrConfigFailure          = errors.New("config failure")
	ErrSerializationFailure   = errors.New("serialization failure")
)

// ChunkNotFoundError wraps ErrChunkNotFound with the offending ID.
type ChunkNotFoundError struct{ ID uuid.UUID }

func (e *ChunkNotFoundError) Error() string  { return fmt.Sprintf("chunk not found: %s", e.ID) }
func (e *ChunkNotFoundError) Unwrap() error  { return ErrChunkNotFound }

// JobNotFoundError wraps ErrJobNotFound with the offending ID.
type JobNotFoundError struct{ ID uuid.UUID }

func (e *JobNotFoundError) Error() string { return fmt.Sprintf("job not found: %s", e.ID) }
func (e *JobNotFoundError) Unwrap() error { return ErrJobNotFound }

// StateTransitionError wraps ErrInvalidStateTransition with context.
type StateTransitionError struct{ Msg string }

func (e *StateTransitionError) Error() string { return fmt.Sprintf("invalid state transition: %s", e.Msg) }
func (e *StateTransitionError) Unwrap() error { return ErrInvalidStateTransition }

// QueueError wraps ErrQueueFailure with context.
type QueueError struct{ Msg string }

func (e *QueueError) Error() string { return fmt.Sprintf("queue error: %s", e.Msg) }
func (e *QueueError) Unwrap() error { return ErrQueueFailure }
