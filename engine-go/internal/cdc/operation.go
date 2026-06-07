// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc

import "fmt"

// CDCOperation is the type of change recorded in a SQL Server capture table.
//
// SQL Server stores the change kind in the __$operation column of every
// cdc.<capture>_CT row using the following coding:
//
//	1 = DELETE
//	2 = INSERT
//	3 = UPDATE (before image)
//	4 = UPDATE (after image)
//
// When applying changes to the target we act on DELETE, INSERT, and the UPDATE
// after-image; the before-image (3) carries the old values and is skipped.
type CDCOperation int

const (
	OpDelete       CDCOperation = 1
	OpInsert       CDCOperation = 2
	OpUpdateBefore CDCOperation = 3
	OpUpdateAfter  CDCOperation = 4
)

// OperationFromCode parses the raw __$operation integer. Returns an error for
// unknown values so callers can quarantine malformed change rows.
func OperationFromCode(code int) (CDCOperation, error) {
	switch code {
	case 1:
		return OpDelete, nil
	case 2:
		return OpInsert, nil
	case 3:
		return OpUpdateBefore, nil
	case 4:
		return OpUpdateAfter, nil
	}
	return 0, fmt.Errorf("unknown CDC operation code %d", code)
}

// Code returns the __$operation integer value for this operation.
func (op CDCOperation) Code() int { return int(op) }

// IsApplicable reports whether this operation should be applied to the target.
// The UPDATE before-image (3) is informational only and is not applied.
func (op CDCOperation) IsApplicable() bool { return op != OpUpdateBefore }

// String satisfies fmt.Stringer.
func (op CDCOperation) String() string {
	switch op {
	case OpDelete:
		return "DELETE"
	case OpInsert:
		return "INSERT"
	case OpUpdateBefore:
		return "UPDATE_BEFORE"
	case OpUpdateAfter:
		return "UPDATE_AFTER"
	}
	return fmt.Sprintf("UNKNOWN(%d)", int(op))
}
