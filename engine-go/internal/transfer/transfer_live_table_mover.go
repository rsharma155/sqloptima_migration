// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

// LiveTransferTableMover copies one table using engine-aware extract/load.
type LiveTransferTableMover struct {
	factory     TransferConnectionFactory
	meta        TransferMetadataPort
	offload     TransferFileOffloadSettings
	beforeChunk func(ctx context.Context) error
}

func NewLiveTransferTableMover(masterKey string) *LiveTransferTableMover {
	return &LiveTransferTableMover{
		factory: TransferConnectionFactory{MasterKey: masterKey},
		offload: DefaultFileOffloadSettings(),
	}
}

func (m *LiveTransferTableMover) ConfigureTransferJob(cfg *TransferDispatchConfig, meta TransferMetadataPort) {
	m.meta = meta
	if cfg != nil && cfg.FileOffload != nil {
		m.offload = *cfg.FileOffload
	} else {
		m.offload = DefaultFileOffloadSettings()
	}
}

var _ TransferTableMover = (*LiveTransferTableMover)(nil)

func (m *LiveTransferTableMover) Move(
	ctx context.Context,
	jobID uuid.UUID,
	src *metadata.ProjectConnection,
	tgt *metadata.ProjectConnection,
	table TransferTablePayload,
) (int64, error) {
	srcEngine := EffectiveEngine(src)
	tgtEngine := EffectiveEngine(tgt)
	switch {
	case srcEngine == "postgres" && tgtEngine == "postgres":
		srcURL, err := m.factory.PostgresURL(src)
		if err != nil {
			return 0, err
		}
		tgtURL, err := m.factory.PostgresURL(tgt)
		if err != nil {
			return 0, err
		}
		return CopyPostgresTableText(
			ctx, srcURL, tgtURL,
			table.SourceSchema, table.SourceTable,
			table.TargetSchema, table.TargetTable,
			table.Columns,
		)
	case srcEngine == "sqlserver" && tgtEngine == "postgres":
		cfg, err := m.factory.SQLServerConfig(src)
		if err != nil {
			return 0, err
		}
		tgtURL, err := m.factory.PostgresURL(tgt)
		if err != nil {
			return 0, err
		}
		return CopySQLServerToPostgres(
			ctx, cfg.ConnectionString(), tgtURL,
			table.SourceSchema, table.SourceTable,
			table.TargetSchema, table.TargetTable,
			table.Columns,
		)
	case srcEngine == "sqlserver" && tgtEngine == "sqlserver":
		srcCfg, err := m.factory.SQLServerConfig(src)
		if err != nil {
			return 0, err
		}
		tgtCfg, err := m.factory.SQLServerConfig(tgt)
		if err != nil {
			return 0, err
		}
		return CopySQLServerToSQLServer(ctx, srcCfg, tgtCfg, table, m.mssqlRuntime(jobID, table))
	default:
		return 0, fmt.Errorf("live transfer mover does not support %s → %s", srcEngine, tgtEngine)
	}
}

func (m *LiveTransferTableMover) mssqlRuntime(jobID uuid.UUID, table TransferTablePayload) MSSQLCopyRuntime {
	rt := MSSQLCopyRuntime{
		ChunkSize:   int64(table.ChunkSize),
		FileOffload: m.offload,
		BeforeChunk: m.beforeChunk,
	}
	if m.meta != nil {
		rt.ReloadChunkSize = func(ctx context.Context) (int64, error) {
			chunk, _, err := m.meta.LoadTransferRuntimeSettings(ctx, jobID)
			return chunk, err
		}
		rt.AfterChunk = func(ctx context.Context, rowsCopied int64) error {
			return m.meta.UpdateTransferTableProgress(ctx, jobID, table.SourceTable, "running", rowsCopied)
		}
	}
	return rt
}
