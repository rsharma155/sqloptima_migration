// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"bytes"
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	mssql "github.com/microsoft/go-mssqldb"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

type MSSQLCopyRuntime struct {
	ChunkSize       int64
	FileOffload     TransferFileOffloadSettings
	BCP             TransferBCPRunner
	ReloadChunkSize func(ctx context.Context) (int64, error)
	BeforeChunk     func(ctx context.Context) error
	AfterChunk      func(ctx context.Context, rowsCopied int64) error
}

func CopySQLServerToSQLServer(
	ctx context.Context,
	srcCfg, tgtCfg extractor.SQLServerConfig,
	table TransferTablePayload,
	rt MSSQLCopyRuntime,
) (int64, error) {
	if len(table.Columns) == 0 {
		return 0, fmt.Errorf("table %s has no resolved columns", table.SourceTable)
	}
	srcDB, err := sql.Open("sqlserver", srcCfg.ConnectionString())
	if err != nil {
		return 0, fmt.Errorf("open transfer SQL Server source: %w", err)
	}
	defer srcDB.Close()
	tgtDB, err := sql.Open("sqlserver", tgtCfg.ConnectionString())
	if err != nil {
		return 0, fmt.Errorf("open transfer SQL Server target: %w", err)
	}
	defer tgtDB.Close()

	copier := &mssqlToMSSQLCopier{
		src:   srcDB,
		tgt:   tgtDB,
		srcEP: sqlServerEndpoint{Host: srcCfg.Host, Port: srcCfg.Port, Database: srcCfg.Database},
		tgtEP: sqlServerEndpoint{Host: tgtCfg.Host, Port: tgtCfg.Port, Database: tgtCfg.Database},
		srcCfg: srcCfg,
		tgtCfg: tgtCfg,
		table: table,
		rt:    rt,
	}
	if copier.rt.ChunkSize < 1 {
		copier.rt.ChunkSize = int64(table.ChunkSize)
	}
	if copier.rt.ChunkSize < 1 {
		copier.rt.ChunkSize = 10_000
	}
	return copier.copy(ctx)
}

type mssqlToMSSQLCopier struct {
	src, tgt           *sql.DB
	srcEP, tgtEP       sqlServerEndpoint
	srcCfg, tgtCfg     extractor.SQLServerConfig
	table              TransferTablePayload
	rt                 MSSQLCopyRuntime
	order              string
	integer            bool
	keepIdentity       bool
}

func (c *mssqlToMSSQLCopier) copy(ctx context.Context) (int64, error) {
	estimate, err := c.rowEstimate(ctx)
	if err != nil {
		return 0, err
	}
	if estimate == 0 {
		estimate = c.table.RowCountEstimate
	}
	if err := c.resolveOrderColumn(ctx); err != nil {
		return 0, err
	}
	if err := HeapCopyPolicy(c.order, estimate, c.chunkSize()); err != nil {
		return 0, err
	}
	if err := c.resolveIdentity(ctx); err != nil {
		return 0, err
	}

	same := SameSQLServerInstance(&c.srcEP, &c.tgtEP)
	mode := SelectMSSQLCopyMode(same, c.rt.FileOffload, estimate, 0)
	if mode == MSSQLCopyBCPNative && c.rt.BCP == nil {
		runner, bcpErr := newExecBCPRunner()
		if bcpErr != nil {
			mode = MSSQLCopyStreamBulk
		} else {
			c.rt.BCP = runner
		}
	}

	if c.order != "" {
		skip, err := c.deltaSkip(ctx)
		if err != nil {
			return 0, err
		}
		if skip {
			return 0, nil
		}
	}

	switch mode {
	case MSSQLCopyInsertSelect:
		return c.copyInsertSelect(ctx)
	case MSSQLCopyBCPNative:
		n, err := c.copyBCP(ctx)
		if err != nil {
			streamed, streamErr := c.copyStream(ctx)
			if streamErr != nil {
				return streamed, fmt.Errorf("bcp offload failed (%v); stream fallback failed: %w", err, streamErr)
			}
			return streamed, nil
		}
		return n, nil
	default:
		return c.copyStream(ctx)
	}
}

func (c *mssqlToMSSQLCopier) chunkSize() int64 {
	if c.rt.ChunkSize < 1 {
		return 10_000
	}
	return c.rt.ChunkSize
}

func (c *mssqlToMSSQLCopier) reloadChunkSize(ctx context.Context) error {
	if c.rt.ReloadChunkSize == nil {
		return nil
	}
	size, err := c.rt.ReloadChunkSize(ctx)
	if err != nil || size < 1 {
		return err
	}
	c.rt.ChunkSize = size
	return nil
}

func (c *mssqlToMSSQLCopier) beforeChunk(ctx context.Context) error {
	if c.rt.BeforeChunk == nil {
		return nil
	}
	return c.rt.BeforeChunk(ctx)
}

func (c *mssqlToMSSQLCopier) afterChunk(ctx context.Context, total int64) error {
	if c.rt.AfterChunk == nil {
		return nil
	}
	return c.rt.AfterChunk(ctx, total)
}

func (c *mssqlToMSSQLCopier) rowEstimate(ctx context.Context) (int64, error) {
	n, err := queryInt64(ctx, c.src, extractport.BuildSQLServerPartitionRowEstimateQuery(),
		sql.Named("P1", c.table.SourceSchema), sql.Named("P2", c.table.SourceTable))
	if err == nil {
		return n, nil
	}
	return queryInt64(ctx, c.src, extractport.BuildSQLServerPartitionRowEstimateFallbackQuery(),
		sql.Named("P1", c.table.SourceSchema), sql.Named("P2", c.table.SourceTable))
}

func (c *mssqlToMSSQLCopier) resolveOrderColumn(ctx context.Context) error {
	c.order = strings.TrimSpace(c.table.OrderColumn)
	if c.order == "" {
		name, typeName, n, err := c.discoverPK(ctx)
		if err != nil {
			return err
		}
		if n > 1 {
			return fmt.Errorf(
				"table %s.%s has a composite primary key — set a single unique order_column",
				c.table.SourceSchema, c.table.SourceTable,
			)
		}
		c.order = name
		c.integer = isIntegerSQLType(typeName)
		return nil
	}
	var typeName string
	err := c.src.QueryRowContext(ctx, extractport.BuildSQLServerOrderColumnTypeQuery(),
		sql.Named("P1", c.table.SourceSchema),
		sql.Named("P2", c.table.SourceTable),
		sql.Named("P3", c.order),
	).Scan(&typeName)
	if err == sql.ErrNoRows {
		c.integer = false
		return nil
	}
	if err != nil {
		return fmt.Errorf("order column type: %w", err)
	}
	c.integer = isIntegerSQLType(typeName)
	return nil
}

func (c *mssqlToMSSQLCopier) discoverPK(ctx context.Context) (name, typeName string, count int, err error) {
	rows, err := c.src.QueryContext(ctx, extractport.BuildSQLServerDiscoverPrimaryKeyQuery(),
		sql.Named("P1", c.table.SourceSchema), sql.Named("P2", c.table.SourceTable))
	if err != nil {
		return "", "", 0, fmt.Errorf("discover primary key: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var n, t string
		if err := rows.Scan(&n, &t); err != nil {
			return "", "", 0, err
		}
		count++
		if count == 1 {
			name, typeName = n, t
		}
	}
	return name, typeName, count, rows.Err()
}

func (c *mssqlToMSSQLCopier) resolveIdentity(ctx context.Context) error {
	rows, err := c.tgt.QueryContext(ctx, extractport.BuildSQLServerDiscoverIdentityQuery(),
		sql.Named("P1", c.table.TargetSchema), sql.Named("P2", c.table.TargetTable))
	if err != nil {
		return fmt.Errorf("discover identity columns: %w", err)
	}
	defer rows.Close()
	wanted := map[string]struct{}{}
	for _, col := range c.table.Columns {
		wanted[strings.ToLower(col)] = struct{}{}
	}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return err
		}
		if _, ok := wanted[strings.ToLower(name)]; ok {
			c.keepIdentity = true
			break
		}
	}
	return rows.Err()
}

func (c *mssqlToMSSQLCopier) bounds(ctx context.Context, db *sql.DB, schema, table, order string) (lo, hi any, ok bool, err error) {
	var rawLo, rawHi any
	err = db.QueryRowContext(ctx, extractport.BuildSQLServerBoundsQuery(schema, table, order)).Scan(&rawLo, &rawHi)
	if err == sql.ErrNoRows {
		return nil, nil, false, nil
	}
	if err != nil {
		return nil, nil, false, err
	}
	if rawLo == nil || rawHi == nil {
		return nil, nil, false, nil
	}
	return normalizeDriverValue(rawLo), normalizeDriverValue(rawHi), true, nil
}

func (c *mssqlToMSSQLCopier) deltaSkip(ctx context.Context) (bool, error) {
	_, srcMax, srcOK, err := c.bounds(ctx, c.src, c.table.SourceSchema, c.table.SourceTable, c.order)
	if err != nil {
		return false, fmt.Errorf("source bounds: %w", err)
	}
	_, tgtMax, tgtOK, err := c.bounds(ctx, c.tgt, c.table.TargetSchema, c.table.TargetTable, c.order)
	if err != nil {
		return false, fmt.Errorf("target bounds: %w", err)
	}
	if !srcOK || !tgtOK {
		return false, nil
	}
	return ShouldSkipInsertOnlyDelta(true, true, compareAny(tgtMax, srcMax)), nil
}

func (c *mssqlToMSSQLCopier) copyInsertSelect(ctx context.Context) (int64, error) {
	if c.order == "" {
		return c.copyStream(ctx)
	}
	if c.integer {
		return c.copyInsertSelectInteger(ctx)
	}
	return c.copyStream(ctx)
}

func (c *mssqlToMSSQLCopier) copyInsertSelectInteger(ctx context.Context) (int64, error) {
	srcLo, srcHi, ok, err := c.bounds(ctx, c.src, c.table.SourceSchema, c.table.SourceTable, c.order)
	if err != nil || !ok {
		return 0, err
	}
	minV, okMin := asInt64(srcLo)
	maxV, okMax := asInt64(srcHi)
	if !okMin || !okMax {
		return c.copyStream(ctx)
	}
	current := minV
	_, tgtMax, tgtOK, err := c.bounds(ctx, c.tgt, c.table.TargetSchema, c.table.TargetTable, c.order)
	if err != nil {
		return 0, err
	}
	if tgtOK {
		if tm, ok := asInt64(tgtMax); ok {
			if tm >= maxV {
				return 0, nil
			}
			current = tm + 1
		}
	}
	sqlText := extractport.BuildSQLServerIntegerRangeInsertSelect(
		c.srcEP.Database, c.table.SourceSchema, c.table.SourceTable,
		c.tgtEP.Database, c.table.TargetSchema, c.table.TargetTable,
		c.order, c.table.Columns,
	)
	maxIters := MaxCopyIters(c.table.RowCountEstimate, c.chunkSize())
	var total int64
	for i := 0; i < maxIters; i++ {
		if err := c.beforeChunk(ctx); err != nil {
			return total, err
		}
		if err := c.reloadChunkSize(ctx); err != nil {
			return total, err
		}
		lo, hi, done := NextIntegerRange(current, maxV, c.chunkSize())
		if done {
			break
		}
		if err := c.withIdentity(ctx, func() error {
			res, execErr := c.tgt.ExecContext(ctx, sqlText, sql.Named("P1", lo), sql.Named("P2", hi))
			if execErr != nil {
				return execErr
			}
			n, _ := res.RowsAffected()
			total += n
			return nil
		}); err != nil {
			return total, fmt.Errorf("insert-select %s: %w", c.table.SourceTable, err)
		}
		if err := c.afterChunk(ctx, total); err != nil {
			return total, err
		}
		if hi >= maxV {
			break
		}
		current = hi + 1
		if current <= lo {
			break
		}
	}
	return total, nil
}

func (c *mssqlToMSSQLCopier) copyStream(ctx context.Context) (int64, error) {
	if c.order == "" {
		if err := c.beforeChunk(ctx); err != nil {
			return 0, err
		}
		n, err := c.streamQuery(ctx, extractport.BuildSQLServerFullTableQuery(
			c.table.SourceSchema, c.table.SourceTable, c.table.Columns,
		))
		if err != nil {
			return n, err
		}
		return n, c.afterChunk(ctx, n)
	}
	if c.integer {
		return c.streamInteger(ctx)
	}
	return c.streamKeyset(ctx)
}

func (c *mssqlToMSSQLCopier) streamInteger(ctx context.Context) (int64, error) {
	srcLo, srcHi, ok, err := c.bounds(ctx, c.src, c.table.SourceSchema, c.table.SourceTable, c.order)
	if err != nil || !ok {
		return 0, err
	}
	minV, okMin := asInt64(srcLo)
	maxV, okMax := asInt64(srcHi)
	if !okMin || !okMax {
		return c.streamKeyset(ctx)
	}
	current := minV
	_, tgtMax, tgtOK, err := c.bounds(ctx, c.tgt, c.table.TargetSchema, c.table.TargetTable, c.order)
	if err != nil {
		return 0, err
	}
	if tgtOK {
		if tm, ok := asInt64(tgtMax); ok {
			if tm >= maxV {
				return 0, nil
			}
			current = tm + 1
		}
	}
	query := extractport.BuildSQLServerIntegerRangeSelect(
		c.table.SourceSchema, c.table.SourceTable, c.order, c.table.Columns,
	)
	maxIters := MaxCopyIters(c.table.RowCountEstimate, c.chunkSize())
	var total int64
	for i := 0; i < maxIters; i++ {
		if err := c.beforeChunk(ctx); err != nil {
			return total, err
		}
		if err := c.reloadChunkSize(ctx); err != nil {
			return total, err
		}
		lo, hi, done := NextIntegerRange(current, maxV, c.chunkSize())
		if done {
			break
		}
		n, err := c.streamQuery(ctx, query, sql.Named("P1", lo), sql.Named("P2", hi))
		if err != nil {
			return total, err
		}
		total += n
		if err := c.afterChunk(ctx, total); err != nil {
			return total, err
		}
		if hi >= maxV {
			break
		}
		current = hi + 1
		if current <= lo {
			break
		}
	}
	return total, nil
}

func (c *mssqlToMSSQLCopier) streamKeyset(ctx context.Context) (int64, error) {
	var last any
	hasLast := false
	_, tgtMax, tgtOK, err := c.bounds(ctx, c.tgt, c.table.TargetSchema, c.table.TargetTable, c.order)
	if err != nil {
		return 0, err
	}
	if tgtOK {
		last = tgtMax
		hasLast = true
	}
	orderIdx := indexOfColumn(c.table.Columns, c.order)
	if orderIdx < 0 {
		return 0, fmt.Errorf("order column %s is not in the extract column list", c.order)
	}
	maxIters := MaxCopyIters(c.table.RowCountEstimate, c.chunkSize())
	var total int64
	for i := 0; i < maxIters; i++ {
		if err := c.beforeChunk(ctx); err != nil {
			return total, err
		}
		if err := c.reloadChunkSize(ctx); err != nil {
			return total, err
		}
		query := extractport.BuildSQLServerKeysetSelect(
			c.table.SourceSchema, c.table.SourceTable, c.order, c.table.Columns, hasLast,
		)
		var args []any
		if !hasLast {
			args = []any{sql.Named("P1", c.chunkSize())}
		} else {
			args = []any{sql.Named("P1", last), sql.Named("P2", c.chunkSize())}
		}
		n, newLast, err := c.streamQueryLastKey(ctx, query, orderIdx, args...)
		if err != nil {
			return total, err
		}
		if n == 0 {
			break
		}
		total += n
		if err := c.afterChunk(ctx, total); err != nil {
			return total, err
		}
		if !anyGreater(newLast, last) && hasLast {
			break
		}
		last = newLast
		hasLast = true
	}
	return total, nil
}

func (c *mssqlToMSSQLCopier) streamQuery(ctx context.Context, query string, args ...any) (int64, error) {
	n, _, err := c.streamQueryLastKey(ctx, query, -1, args...)
	return n, err
}

func (c *mssqlToMSSQLCopier) streamQueryLastKey(
	ctx context.Context, query string, orderIdx int, args ...any,
) (int64, any, error) {
	rows, err := c.src.QueryContext(ctx, query, args...)
	if err != nil {
		return 0, nil, fmt.Errorf("extract %s: %w", c.table.SourceTable, err)
	}
	defer rows.Close()

	txn, err := c.tgt.BeginTx(ctx, nil)
	if err != nil {
		return 0, nil, err
	}
	committed := false
	defer func() {
		if !committed {
			_ = txn.Rollback()
		}
	}()
	if c.keepIdentity {
		if _, err := txn.ExecContext(ctx, extractport.BuildSQLServerIdentityInsert(
			c.table.TargetSchema, c.table.TargetTable, true,
		)); err != nil {
			return 0, nil, fmt.Errorf("identity insert on: %w", err)
		}
		defer func() {
			_, _ = txn.ExecContext(context.Background(), extractport.BuildSQLServerIdentityInsert(
				c.table.TargetSchema, c.table.TargetTable, false,
			))
		}()
	}
	stmt, err := txn.PrepareContext(ctx, mssql.CopyIn(
		extractport.QuotedTableMSSQL(c.table.TargetSchema, c.table.TargetTable),
		mssql.BulkOptions{KeepNulls: true, Tablock: true},
		c.table.Columns...,
	))
	if err != nil {
		return 0, nil, fmt.Errorf("prepare bulk insert: %w", err)
	}
	defer stmt.Close()

	nCols := len(c.table.Columns)
	var copied int64
	var last any
	for rows.Next() {
		vals, err := scanSQLRow(rows, nCols)
		if err != nil {
			return copied, last, err
		}
		if _, err := stmt.ExecContext(ctx, vals...); err != nil {
			return copied, last, fmt.Errorf("bulk insert row: %w", err)
		}
		copied++
		if orderIdx >= 0 && orderIdx < len(vals) {
			last = vals[orderIdx]
		}
	}
	if err := rows.Err(); err != nil {
		return copied, last, err
	}
	if _, err := stmt.ExecContext(ctx); err != nil {
		return copied, last, fmt.Errorf("flush bulk insert: %w", err)
	}
	if err := txn.Commit(); err != nil {
		return copied, last, err
	}
	committed = true
	return copied, last, nil
}

func (c *mssqlToMSSQLCopier) copyBCP(ctx context.Context) (int64, error) {
	if c.rt.BCP == nil {
		return 0, fmt.Errorf("bcp runner is not configured")
	}
	if !c.integer || c.order == "" {
		return 0, fmt.Errorf("native bcp offload requires an integer order column")
	}
	srcLo, srcHi, ok, err := c.bounds(ctx, c.src, c.table.SourceSchema, c.table.SourceTable, c.order)
	if err != nil || !ok {
		return 0, err
	}
	minV, okMin := asInt64(srcLo)
	maxV, okMax := asInt64(srcHi)
	if !okMin || !okMax {
		return 0, fmt.Errorf("bcp offload requires integer bounds")
	}
	current := minV
	_, tgtMax, tgtOK, err := c.bounds(ctx, c.tgt, c.table.TargetSchema, c.table.TargetTable, c.order)
	if err != nil {
		return 0, err
	}
	if tgtOK {
		if tm, ok := asInt64(tgtMax); ok {
			if tm >= maxV {
				return 0, nil
			}
			current = tm + 1
		}
	}
	dir, err := os.MkdirTemp(c.stagingDir(), "xdt-")
	if err != nil {
		return 0, err
	}
	defer os.RemoveAll(dir)

	dest := bcpDestName(c.tgtCfg.Database, c.table.TargetSchema, c.table.TargetTable)
	maxIters := MaxCopyIters(c.table.RowCountEstimate, c.chunkSize())
	var total int64
	for i := 0; i < maxIters; i++ {
		if err := c.beforeChunk(ctx); err != nil {
			return total, err
		}
		if err := c.reloadChunkSize(ctx); err != nil {
			return total, err
		}
		lo, hi, done := NextIntegerRange(current, maxV, c.chunkSize())
		if done {
			break
		}
		query := extractport.BuildSQLServerIntegerRangeSelectLiteral(
			c.srcCfg.Database, c.table.SourceSchema, c.table.SourceTable, c.order, c.table.Columns, lo, hi,
		)
		file := filepath.Join(dir, fmt.Sprintf("chunk-%d.bcp", i))
		if err := c.rt.BCP.QueryOut(ctx, c.srcCfg, query, file); err != nil {
			return total, err
		}
		info, statErr := os.Stat(file)
		if statErr != nil || info.Size() == 0 {
			if hi >= maxV {
				break
			}
			current = hi + 1
			continue
		}
		batch := int(c.chunkSize())
		if err := c.rt.BCP.BulkIn(ctx, c.tgtCfg, dest, file, batch, c.keepIdentity); err != nil {
			return total, err
		}
		_ = os.Remove(file)
		total += hi - lo + 1
		if err := c.afterChunk(ctx, total); err != nil {
			return total, err
		}
		if hi >= maxV {
			break
		}
		current = hi + 1
		if current <= lo {
			break
		}
	}
	return total, nil
}

func (c *mssqlToMSSQLCopier) stagingDir() string {
	path := strings.TrimSpace(c.rt.FileOffload.StagingPath)
	if path != "" {
		return path
	}
	return os.TempDir()
}

func (c *mssqlToMSSQLCopier) withIdentity(ctx context.Context, fn func() error) error {
	if !c.keepIdentity {
		return fn()
	}
	if _, err := c.tgt.ExecContext(ctx, extractport.BuildSQLServerIdentityInsert(
		c.table.TargetSchema, c.table.TargetTable, true,
	)); err != nil {
		return err
	}
	defer func() {
		_, _ = c.tgt.ExecContext(context.Background(), extractport.BuildSQLServerIdentityInsert(
			c.table.TargetSchema, c.table.TargetTable, false,
		))
	}()
	return fn()
}

func queryInt64(ctx context.Context, db *sql.DB, query string, args ...any) (int64, error) {
	var n int64
	err := db.QueryRowContext(ctx, query, args...).Scan(&n)
	return n, err
}

func scanSQLRow(rows *sql.Rows, n int) ([]any, error) {
	raw := make([]any, n)
	ptrs := make([]any, n)
	for i := range raw {
		ptrs[i] = &raw[i]
	}
	if err := rows.Scan(ptrs...); err != nil {
		return nil, err
	}
	out := make([]any, n)
	for i, v := range raw {
		out[i] = normalizeDriverValue(v)
	}
	return out, nil
}

func indexOfColumn(columns []string, name string) int {
	for i, c := range columns {
		if strings.EqualFold(c, name) {
			return i
		}
	}
	return -1
}

func asInt64(v any) (int64, bool) {
	switch n := v.(type) {
	case int64:
		return n, true
	case int32:
		return int64(n), true
	case int:
		return int64(n), true
	case int16:
		return int64(n), true
	case uint8:
		return int64(n), true
	case float64:
		return int64(n), true
	default:
		return 0, false
	}
}

func compareAny(a, b any) int {
	if ai, ok := asInt64(a); ok {
		if bi, ok := asInt64(b); ok {
			switch {
			case ai < bi:
				return -1
			case ai > bi:
				return 1
			default:
				return 0
			}
		}
	}
	if at, ok := a.(time.Time); ok {
		if bt, ok := b.(time.Time); ok {
			switch {
			case at.Before(bt):
				return -1
			case at.After(bt):
				return 1
			default:
				return 0
			}
		}
	}
	ab, aOK := a.([]byte)
	bb, bOK := b.([]byte)
	if aOK && bOK {
		return bytes.Compare(ab, bb)
	}
	return strings.Compare(fmt.Sprint(a), fmt.Sprint(b))
}

func anyGreater(next, prev any) bool {
	if next != nil && prev == nil {
		return true
	}
	return compareAny(next, prev) > 0
}
