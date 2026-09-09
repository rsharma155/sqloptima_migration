// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"database/sql"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	_ "github.com/microsoft/go-mssqldb"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
	"github.com/ravisharma/sql-optima/engine-go/internal/metadata"
)

type LiveTransferConstraintApplier struct {
	factory TransferConnectionFactory
}

func NewLiveTransferConstraintApplier(masterKey string) *LiveTransferConstraintApplier {
	return &LiveTransferConstraintApplier{factory: TransferConnectionFactory{MasterKey: masterKey}}
}

var _ TransferConstraintApplier = (*LiveTransferConstraintApplier)(nil)

func (a *LiveTransferConstraintApplier) Apply(
	ctx context.Context,
	target *metadata.ProjectConnection,
	items []TransferConstraintItem,
) error {
	return a.applyOrRestore(ctx, target, items, false)
}

func (a *LiveTransferConstraintApplier) Restore(
	ctx context.Context,
	target *metadata.ProjectConnection,
	items []TransferConstraintItem,
) error {
	return a.applyOrRestore(ctx, target, items, true)
}

func orderedConstraintItems(items []TransferConstraintItem, restore bool) []TransferConstraintItem {
	rank := map[string]int{
		"foreign_key": 0,
		"check":       1,
		"unique":      2,
		"index":       3,
		"secondary":   3,
		"trigger":     4,
	}
	out := append([]TransferConstraintItem(nil), items...)
	less := func(i, j int) bool {
		ri, rj := rank[out[i].Kind], rank[out[j].Kind]
		if ri != rj {
			if restore {
				return ri > rj
			}
			return ri < rj
		}
		return out[i].ObjectID < out[j].ObjectID
	}
	for i := 0; i < len(out); i++ {
		for j := i + 1; j < len(out); j++ {
			if less(j, i) {
				out[i], out[j] = out[j], out[i]
			}
		}
	}
	return out
}

func constraintDisableSQL(engine string, item TransferConstraintItem) (string, error) {
	kind := strings.ToLower(item.Kind)
	switch engine {
	case "postgres":
		switch kind {
		case "foreign_key", "check", "unique":
			return extractport.BuildPostgresDropConstraint(item.Schema, item.Table, item.ObjectID), nil
		case "index", "secondary":
			return extractport.BuildPostgresDropIndex(item.Schema, item.ObjectID), nil
		case "trigger":
			return extractport.BuildPostgresDisableTrigger(item.Schema, item.Table, item.ObjectID), nil
		default:
			return "", fmt.Errorf("cannot disable %s %s", item.Kind, item.ObjectID)
		}
	case "sqlserver":
		switch kind {
		case "foreign_key", "check":
			return extractport.BuildMSSQLNoCheckConstraint(item.Schema, item.Table, item.ObjectID), nil
		case "index", "secondary", "unique":
			return extractport.BuildMSSQLDisableIndex(item.Schema, item.Table, item.ObjectID), nil
		case "trigger":
			return extractport.BuildMSSQLDisableTrigger(item.Schema, item.Table, item.ObjectID), nil
		default:
			return "", fmt.Errorf("cannot disable %s %s", item.Kind, item.ObjectID)
		}
	default:
		return "", fmt.Errorf("unsupported target engine %s", engine)
	}
}

func constraintRestoreSQL(engine string, item TransferConstraintItem) (string, error) {
	kind := strings.ToLower(item.Kind)
	switch engine {
	case "postgres":
		switch kind {
		case "foreign_key", "check", "unique":
			return extractport.BuildPostgresAddConstraint(item.Schema, item.Table, item.ObjectID, item.Definition)
		case "index", "secondary":
			return extractport.BuildPostgresCreateIndex(item.Definition)
		case "trigger":
			return extractport.BuildPostgresEnableTrigger(item.Schema, item.Table, item.ObjectID), nil
		default:
			return "", fmt.Errorf("cannot restore %s %s", item.Kind, item.ObjectID)
		}
	case "sqlserver":
		switch kind {
		case "foreign_key", "check":
			return extractport.BuildMSSQLCheckConstraint(item.Schema, item.Table, item.ObjectID), nil
		case "index", "secondary", "unique":
			return extractport.BuildMSSQLRebuildIndex(item.Schema, item.Table, item.ObjectID), nil
		case "trigger":
			return extractport.BuildMSSQLEnableTrigger(item.Schema, item.Table, item.ObjectID), nil
		default:
			return "", fmt.Errorf("cannot restore %s %s", item.Kind, item.ObjectID)
		}
	default:
		return "", fmt.Errorf("unsupported target engine %s", engine)
	}
}

func (a *LiveTransferConstraintApplier) applyOrRestore(
	ctx context.Context,
	target *metadata.ProjectConnection,
	items []TransferConstraintItem,
	restore bool,
) error {
	engine := EffectiveEngine(target)
	execSQL := func(query string) error {
		if engine == "postgres" {
			url, err := a.factory.PostgresURL(target)
			if err != nil {
				return err
			}
			conn, err := pgx.Connect(ctx, url)
			if err != nil {
				return fmt.Errorf("connect target postgres for constraints: %w", err)
			}
			defer conn.Close(ctx)
			_, err = conn.Exec(ctx, query)
			return err
		}
		cfg, err := a.factory.SQLServerConfig(target)
		if err != nil {
			return err
		}
		db, err := sql.Open("sqlserver", cfg.ConnectionString())
		if err != nil {
			return err
		}
		defer db.Close()
		_, err = db.ExecContext(ctx, query)
		return err
	}

	ordered := orderedConstraintItems(items, restore)
	for _, item := range ordered {
		var query string
		var err error
		if restore {
			query, err = constraintRestoreSQL(engine, item)
		} else {
			query, err = constraintDisableSQL(engine, item)
		}
		if err != nil {
			return err
		}
		if err := execSQL(query); err != nil {
			return fmt.Errorf("%s %s: %w", item.Kind, item.ObjectID, err)
		}
	}
	return nil
}
