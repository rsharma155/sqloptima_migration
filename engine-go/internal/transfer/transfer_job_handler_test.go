// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

type fakeTransferMeta struct {
	queued   []QueuedTransferJob
	claimed  []uuid.UUID
	commands []core.Command
	calls    []string
	status   string
}

func (f *fakeTransferMeta) UpsertWorkerHeartbeat(context.Context, string, string, string) error {
	return nil
}
func (f *fakeTransferMeta) ListQueuedTransferJobs(context.Context, int) ([]QueuedTransferJob, error) {
	return f.queued, nil
}
func (f *fakeTransferMeta) ClaimQueuedTransferJob(_ context.Context, jobID uuid.UUID) (bool, error) {
	f.claimed = append(f.claimed, jobID)
	return true, nil
}
func (f *fakeTransferMeta) LoadTransferDispatchConfig(_ context.Context, jobID uuid.UUID) (json.RawMessage, error) {
	for _, j := range f.queued {
		if j.JobID == jobID {
			return j.Config, nil
		}
	}
	return nil, errors.New("missing config")
}
func (f *fakeTransferMeta) AppendTransferJobLog(_ context.Context, _ uuid.UUID, level, message string) error {
	f.calls = append(f.calls, level+":"+message)
	return nil
}
func (f *fakeTransferMeta) AppendTransferTableLog(_ context.Context, _ uuid.UUID, tableName, level, message string) error {
	f.calls = append(f.calls, tableName+":"+level+":"+message)
	return nil
}
func (f *fakeTransferMeta) SetTransferJobStatus(_ context.Context, _ uuid.UUID, status string) error {
	f.status = status
	f.calls = append(f.calls, "status:"+status)
	return nil
}
func (f *fakeTransferMeta) SetTransferJobError(context.Context, uuid.UUID, string) error { return nil }
func (f *fakeTransferMeta) SetTransferTableError(_ context.Context, _ uuid.UUID, sourceSchema, sourceTable, message string) error {
	f.calls = append(f.calls, "table-error:"+sourceSchema+"."+sourceTable+":"+message)
	return nil
}
func (f *fakeTransferMeta) UpdateTransferTableProgress(context.Context, uuid.UUID, string, string, int64) error {
	return nil
}
func (f *fakeTransferMeta) UpdateTransferJobTotals(context.Context, uuid.UUID, int64, int) error {
	return nil
}
func (f *fakeTransferMeta) AckTransferCommand(_ context.Context, _ uuid.UUID) error {
	f.calls = append(f.calls, "ack")
	return nil
}
func (f *fakeTransferMeta) GetTransferCommand(_ context.Context, _ uuid.UUID) (core.Command, bool, error) {
	if len(f.commands) == 0 {
		return "", false, nil
	}
	cmd := f.commands[0]
	f.commands = f.commands[1:]
	return cmd, true, nil
}
func (f *fakeTransferMeta) LoadProjectConnection(context.Context, uuid.UUID) (*metadata.ProjectConnection, error) {
	return &metadata.ProjectConnection{}, nil
}
func (f *fakeTransferMeta) LoadTransferRuntimeSettings(context.Context, uuid.UUID) (int64, *int64, error) {
	return 10000, nil, nil
}

type fakeMover struct {
	tables []string
	err    error
}

func (m *fakeMover) Move(_ context.Context, _ uuid.UUID, _ *metadata.ProjectConnection, _ *metadata.ProjectConnection, table TransferTablePayload) (int64, error) {
	m.tables = append(m.tables, table.SourceTable)
	return 3, m.err
}

func validConfigJSON(path, jobID string) json.RawMessage {
	return json.RawMessage(`{
		"job_id": "` + jobID + `",
		"kind": "transfer",
		"path": "` + path + `",
		"source": {"connection_id": "550e8400-e29b-41d4-a716-446655440001", "schema": "public", "engine": "postgres"},
		"target": {"connection_id": "550e8400-e29b-41d4-a716-446655440002", "schema": "public", "engine": "postgres"},
		"tables": [{
			"source_schema": "public",
			"source_table": "orders",
			"target_schema": "public",
			"target_table": "orders",
			"columns": ["id"],
			"chunk_size": 10000
		}]
	}`)
}

func TestTransferJobClaimerClaimsQueuedJob(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	meta := &fakeTransferMeta{
		queued: []QueuedTransferJob{{JobID: jobID, Config: validConfigJSON("pg_to_pg", jobID.String())}},
	}
	claimer := NewTransferJobClaimer(meta)
	job, err := claimer.ClaimNext(context.Background())
	if err != nil || job == nil {
		t.Fatalf("claim: %v %#v", err, job)
	}
	if job.JobID != jobID {
		t.Fatalf("job id = %s", job.JobID)
	}
}

func TestTransferGoJobHandlerCompletesMssqlToMssql(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := validConfigJSON("mssql_to_mssql", jobID.String())
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	mover := &fakeMover{}
	h := NewTransferGoJobHandler(meta, mover, nil)
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err != nil {
		t.Fatalf("run: %v", err)
	}
	if meta.status != "completed" {
		t.Fatalf("status = %s", meta.status)
	}
}

func TestTransferGoJobHandlerCompletesPgToPg(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := validConfigJSON("pg_to_pg", jobID.String())
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	mover := &fakeMover{}
	h := NewTransferGoJobHandler(meta, mover, nil)
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err != nil {
		t.Fatalf("run: %v", err)
	}
	if len(mover.tables) != 1 || mover.tables[0] != "orders" {
		t.Fatalf("mover tables = %v", mover.tables)
	}
	if meta.status != "completed" {
		t.Fatalf("status = %s", meta.status)
	}
}

func TestTransferGoJobHandlerRejectsUnimplementedPath(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := validConfigJSON("pg_to_mssql", jobID.String())
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	h := NewTransferGoJobHandler(meta, &fakeMover{}, nil)
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err == nil {
		t.Fatal("expected unimplemented path error")
	}
	if meta.status != "failed" {
		t.Fatalf("status = %s", meta.status)
	}
}

func TestTransferGoJobHandlerAppliesReviewedDisables(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := json.RawMessage(`{
		"job_id": "` + jobID.String() + `",
		"kind": "transfer",
		"path": "pg_to_pg",
		"source": {"connection_id": "550e8400-e29b-41d4-a716-446655440001", "schema": "public", "engine": "postgres"},
		"target": {"connection_id": "550e8400-e29b-41d4-a716-446655440002", "schema": "public", "engine": "postgres"},
		"tables": [{
			"source_schema": "public",
			"source_table": "orders",
			"target_schema": "public",
			"target_table": "orders",
			"columns": ["id"],
			"chunk_size": 10000
		}],
		"constraint_plan": {
			"operator_reviewed": true,
			"on_stop": "restore_now",
			"items": [{
				"object_id": "orders_fk",
				"kind": "foreign_key",
				"schema": "public",
				"table": "orders",
				"action": "disable",
				"definition": "FOREIGN KEY (customer_id) REFERENCES public.customers(id)"
			}]
		}
	}`)
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	applier := &fakeConstraintApplier{}
	h := NewTransferGoJobHandler(meta, &fakeMover{}, nil).WithConstraintApplier(applier)
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err != nil {
		t.Fatalf("run: %v", err)
	}
	if applier.applied != 1 || applier.restored != 1 {
		t.Fatalf("apply/restore counts = %d/%d", applier.applied, applier.restored)
	}
}

func TestTransferGoJobHandlerRejectsUnreviewedDisable(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := json.RawMessage(`{
		"job_id": "` + jobID.String() + `",
		"kind": "transfer",
		"path": "pg_to_pg",
		"source": {"connection_id": "550e8400-e29b-41d4-a716-446655440001", "schema": "public", "engine": "postgres"},
		"target": {"connection_id": "550e8400-e29b-41d4-a716-446655440002", "schema": "public", "engine": "postgres"},
		"tables": [{
			"source_schema": "public",
			"source_table": "orders",
			"target_schema": "public",
			"target_table": "orders",
			"columns": ["id"],
			"chunk_size": 10000
		}],
		"constraint_plan": {
			"operator_reviewed": false,
			"items": [{"object_id": "orders_fk", "kind": "foreign_key", "schema": "public", "table": "orders", "action": "disable"}]
		}
	}`)
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	h := NewTransferGoJobHandler(meta, &fakeMover{}, nil).WithConstraintApplier(&fakeConstraintApplier{})
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err == nil {
		t.Fatal("expected unreviewed disable to fail")
	}
}

func TestConstraintDisableSQLQuotesPostgres(t *testing.T) {
	item := TransferConstraintItem{Schema: "public", Table: "orders", ObjectID: "fk", Kind: "foreign_key"}
	sql, err := constraintDisableSQL("postgres", item)
	if err != nil {
		t.Fatal(err)
	}
	if sql != `ALTER TABLE "public"."orders" DROP CONSTRAINT "fk"` {
		t.Fatalf("got %s", sql)
	}
}

type fakeConstraintApplier struct {
	applied  int
	restored int
}

func (f *fakeConstraintApplier) Apply(context.Context, *metadata.ProjectConnection, []TransferConstraintItem) error {
	f.applied++
	return nil
}
func (f *fakeConstraintApplier) Restore(context.Context, *metadata.ProjectConnection, []TransferConstraintItem) error {
	f.restored++
	return nil
}

func TestTransferGoJobHandlerRecordsTableError(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := validConfigJSON("pg_to_pg", jobID.String())
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	h := NewTransferGoJobHandler(meta, &fakeMover{err: errors.New("copy failed: timeout")}, nil)
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err == nil {
		t.Fatal("expected move error")
	}
	if meta.status != "failed" {
		t.Fatalf("status = %s", meta.status)
	}
	foundTableError := false
	foundTableLog := false
	for _, call := range meta.calls {
		if call == "table-error:public.orders:copy failed: timeout" {
			foundTableError = true
		}
		if call == "public.orders:error:copy failed: timeout" {
			foundTableLog = true
		}
	}
	if !foundTableError || !foundTableLog {
		t.Fatalf("missing table-scoped error persistence, calls=%v", meta.calls)
	}
}

type fakeSchemaCloneApplier struct {
	phases []string
}

func (f *fakeSchemaCloneApplier) Apply(_ context.Context, _ *metadata.ProjectConnection, statements []SchemaCloneStatement) error {
	for _, s := range statements {
		f.phases = append(f.phases, s.Phase+":"+s.Kind)
	}
	return nil
}

func TestTransferGoJobHandlerRunsSchemaCloneAroundCopy(t *testing.T) {
	jobID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	cfg := json.RawMessage(`{
		"job_id": "` + jobID.String() + `",
		"kind": "transfer",
		"path": "mssql_to_mssql",
		"source": {"connection_id": "550e8400-e29b-41d4-a716-446655440001", "schema": "dbo", "engine": "sqlserver"},
		"target": {"connection_id": "550e8400-e29b-41d4-a716-446655440002", "schema": "dbo", "engine": "sqlserver"},
		"tables": [{
			"source_schema": "dbo",
			"source_table": "orders",
			"target_schema": "dbo",
			"target_table": "orders",
			"columns": ["id"],
			"chunk_size": 10000
		}],
		"schema_clone": {
			"create_if_missing": true,
			"clone_objects": true,
			"statements": [
				{"phase": "pre_copy", "kind": "table", "sql": "CREATE TABLE t (id int)", "schema": "dbo", "name": "orders", "skip_if_exists": true},
				{"phase": "post_copy", "kind": "view", "sql": "CREATE VIEW v AS SELECT 1 AS x", "schema": "dbo", "name": "v", "skip_if_exists": true}
			]
		}
	}`)
	meta := &fakeTransferMeta{queued: []QueuedTransferJob{{JobID: jobID, Config: cfg}}}
	clone := &fakeSchemaCloneApplier{}
	h := NewTransferGoJobHandler(meta, &fakeMover{}, nil).WithSchemaCloneApplier(clone)
	if err := h.Run(context.Background(), &QueuedTransferJob{JobID: jobID, Config: cfg}); err != nil {
		t.Fatalf("run: %v", err)
	}
	if len(clone.phases) != 2 || clone.phases[0] != "pre_copy:table" || clone.phases[1] != "post_copy:view" {
		t.Fatalf("clone phases = %v", clone.phases)
	}
	if meta.status != "completed" {
		t.Fatalf("status = %s", meta.status)
	}
}

func TestTransferJobCommandControllerStop(t *testing.T) {
	jobID := uuid.New()
	meta := &fakeTransferMeta{commands: []core.Command{core.CommandStop}}
	ctrl := NewTransferJobCommandController(meta, jobID, nil)
	err := ctrl.CheckBeforeChunk(context.Background())
	if !errors.Is(err, ErrTransferJobStopped) {
		t.Fatalf("expected ErrTransferJobStopped, got %v", err)
	}
}
