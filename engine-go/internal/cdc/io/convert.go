// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT
//
// Module: engine-go/internal/cdc/io/convert.go
// Purpose: Pure row → CDCEvent mapping (no DB I/O; fully unit-testable)
// Domain: Replication / CDC (data plane)
// Author: Ravi Sharma

package cdcio

import (
	"fmt"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

// rowToEvent maps a scanned CT-table row into a domain CDCEvent.
func rowToEvent(schema, table string, colNames []string, values []interface{}) (*cdc.CDCEvent, error) {
	if len(colNames) != len(values) {
		return nil, fmt.Errorf("column/value length mismatch: %d vs %d", len(colNames), len(values))
	}
	ev := &cdc.CDCEvent{
		Schema:  schema,
		Table:   table,
		Columns: make(map[string]interface{}),
	}
	var startRaw, seqRaw []byte
	var opCode int
	for i, name := range colNames {
		v := values[i]
		switch name {
		case "__$start_lsn":
			startRaw = asBytes(v)
		case "__$seqval":
			seqRaw = asBytes(v)
		case "__$operation":
			opCode = asInt(v)
		default:
			if len(name) >= 3 && name[:3] == "__$" {
				continue
			}
			ev.Columns[name] = unwrap(v)
		}
	}
	start, err := bytesToLSN(startRaw)
	if err != nil {
		return nil, err
	}
	seq, err := bytesToLSN(seqRaw)
	if err != nil {
		return nil, err
	}
	op, err := cdc.OperationFromCode(opCode)
	if err != nil {
		return nil, err
	}
	ev.StartLSN = start
	ev.CommitLSN = start
	ev.SeqVal = seq
	ev.Operation = op
	return ev, nil
}

func bytesToLSN(raw []byte) (cdc.LSN, error) {
	var lsn cdc.LSN
	if len(raw) == 0 {
		return cdc.ZeroLSN, nil
	}
	if len(raw) < 10 {
		copy(lsn[10-len(raw):], raw)
		return lsn, nil
	}
	copy(lsn[:], raw[:10])
	return lsn, nil
}

func asBytes(v interface{}) []byte {
	switch t := v.(type) {
	case nil:
		return nil
	case []byte:
		return t
	case string:
		return []byte(t)
	default:
		return nil
	}
}

func asInt(v interface{}) int {
	switch t := v.(type) {
	case int64:
		return int(t)
	case int32:
		return int(t)
	case int:
		return t
	case []byte:
		if len(t) == 1 {
			return int(t[0])
		}
	}
	return 0
}

func unwrap(v interface{}) interface{} {
	if b, ok := v.([]byte); ok {
		return append([]byte(nil), b...)
	}
	return v
}

func bindArgs(ev *cdc.CDCEvent, stmt cdc.ApplyStatement, columns, pkColumns []string) ([]interface{}, error) {
	switch ev.Operation {
	case cdc.OpDelete:
		args := make([]interface{}, len(pkColumns))
		for i, c := range pkColumns {
			v, ok := ev.Columns[c]
			if !ok {
				return nil, fmt.Errorf("missing PK column %q in CDC event", c)
			}
			args[i] = v
		}
		return args, nil
	case cdc.OpInsert, cdc.OpUpdateAfter:
		args := make([]interface{}, len(columns))
		for i, c := range columns {
			args[i] = ev.Columns[c]
		}
		_ = stmt
		return args, nil
	default:
		return nil, nil
	}
}

// RowToEventForTest exports rowToEvent for unit tests (same package API boundary).
func RowToEventForTest(schema, table string, colNames []string, values []interface{}) (*cdc.CDCEvent, error) {
	return rowToEvent(schema, table, colNames, values)
}

// BindArgsForTest exports bindArgs for unit tests.
func BindArgsForTest(ev *cdc.CDCEvent, stmt cdc.ApplyStatement, columns, pkColumns []string) ([]interface{}, error) {
	return bindArgs(ev, stmt, columns, pkColumns)
}

// BytesToLSNForTest exports bytesToLSN for unit tests.
func BytesToLSNForTest(raw []byte) (cdc.LSN, error) {
	return bytesToLSN(raw)
}
