// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

type fakeCommandMeta struct {
	commands []core.Command
	calls    []string
}

func (f *fakeCommandMeta) UpsertWorkerHeartbeat(context.Context, string, string, string) error {
	return nil
}
func (f *fakeCommandMeta) ListQueuedGoJobs(context.Context, int) ([]QueuedJob, error) {
	return nil, nil
}
func (f *fakeCommandMeta) ClaimQueuedJob(context.Context, uuid.UUID) (bool, error) {
	return false, nil
}
func (f *fakeCommandMeta) LoadJobDispatchConfig(context.Context, uuid.UUID) (json.RawMessage, error) {
	return nil, nil
}
func (f *fakeCommandMeta) AppendMigrationJobLog(_ context.Context, _ uuid.UUID, level, message string) error {
	f.calls = append(f.calls, level+":"+message)
	return nil
}
func (f *fakeCommandMeta) SetMigrationJobStatus(_ context.Context, _ uuid.UUID, status string) error {
	f.calls = append(f.calls, "status:"+status)
	return nil
}
func (f *fakeCommandMeta) SetMigrationJobError(context.Context, uuid.UUID, string) error { return nil }
func (f *fakeCommandMeta) UpdateTablePlanProgress(context.Context, uuid.UUID, string, string, int64) error {
	return nil
}
func (f *fakeCommandMeta) AckCommand(_ context.Context, _ uuid.UUID) error {
	f.calls = append(f.calls, "ack")
	return nil
}
func (f *fakeCommandMeta) GetCommand(_ context.Context, _ uuid.UUID) (core.Command, bool, error) {
	if len(f.commands) == 0 {
		return "", false, nil
	}
	cmd := f.commands[0]
	f.commands = f.commands[1:]
	return cmd, true, nil
}
func (f *fakeCommandMeta) LoadProjectConnection(context.Context, uuid.UUID) (*metadata.ProjectConnection, error) {
	return nil, nil
}
func (f *fakeCommandMeta) UpdateMigrationJobTotals(context.Context, uuid.UUID, int64, int) error {
	return nil
}
func (f *fakeCommandMeta) InsertMigrationQuarantine(context.Context, uuid.UUID, string, string, uint32, string, *string, *string, string) error {
	return nil
}

func TestMigrationJobCommandController_stop(t *testing.T) {
	jobID := uuid.New()
	meta := &fakeCommandMeta{commands: []core.Command{core.CommandStop}}
	ctrl := NewMigrationJobCommandController(meta, jobID, nil)

	err := ctrl.CheckBeforeChunk(context.Background())
	if !errors.Is(err, ErrJobStopped) {
		t.Fatalf("expected ErrJobStopped, got %v", err)
	}
	if meta.calls[0] != "ack" {
		t.Fatalf("expected ack first, got %v", meta.calls)
	}
}

func TestMigrationJobCommandController_pauseThenResume(t *testing.T) {
	jobID := uuid.New()
	meta := &fakeCommandMeta{
		commands: []core.Command{
			core.CommandPause,
			core.CommandResume,
		},
	}
	ctrl := NewMigrationJobCommandController(meta, jobID, nil)

	if err := ctrl.CheckBeforeChunk(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	foundPaused := false
	foundRunning := false
	for _, call := range meta.calls {
		if call == "status:paused" {
			foundPaused = true
		}
		if call == "status:running" {
			foundRunning = true
		}
	}
	if !foundPaused || !foundRunning {
		t.Fatalf("expected paused then running statuses, got %v", meta.calls)
	}
}
