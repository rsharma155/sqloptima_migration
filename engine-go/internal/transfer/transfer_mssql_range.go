// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"fmt"
	"math"
	"strings"
)

const (
	MSSQLCopyInsertSelect = "insert_select"
	MSSQLCopyStreamBulk   = "stream_bulk"
	MSSQLCopyBCPNative    = "bcp_native"
)

type sqlServerEndpoint struct {
	Host     string
	Port     int
	Database string
}

func SameSQLServerInstance(a, b *sqlServerEndpoint) bool {
	if a == nil || b == nil {
		return false
	}
	return strings.EqualFold(strings.TrimSpace(a.Host), strings.TrimSpace(b.Host)) && a.Port == b.Port
}

func SelectMSSQLCopyMode(sameServer bool, offload TransferFileOffloadSettings, rowEstimate int64, sizeMB float64) string {
	if sameServer {
		return MSSQLCopyInsertSelect
	}
	if ShouldFileOffload(false, offload, rowEstimate, sizeMB) {
		return MSSQLCopyBCPNative
	}
	return MSSQLCopyStreamBulk
}

func NextIntegerRange(current, max, chunk int64) (lo, hi int64, done bool) {
	if chunk < 1 {
		chunk = 1
	}
	if current > max {
		return 0, 0, true
	}
	hi = current + chunk - 1
	if hi < current {
		return 0, 0, true
	}
	if hi > max {
		hi = max
	}
	return current, hi, false
}

func HeapCopyPolicy(orderColumn string, rowEstimate, chunkSize int64) error {
	if strings.TrimSpace(orderColumn) != "" {
		return nil
	}
	if chunkSize < 1 {
		chunkSize = 1
	}
	if rowEstimate <= chunkSize {
		return nil
	}
	return fmt.Errorf(
		"table has no order column and estimate %d exceeds chunk size %d — refuse cursor scan",
		rowEstimate, chunkSize,
	)
}

func MaxCopyIters(rowEstimate, chunk int64) int {
	if chunk < 1 {
		chunk = 1
	}
	n := rowEstimate/chunk + 32
	if n < 8 {
		n = 8
	}
	if n > 1_000_000 {
		n = 1_000_000
	}
	if n > math.MaxInt32 {
		return 1_000_000
	}
	return int(n)
}

// ShouldSkipInsertOnlyDelta is true when the destination already has the source max key
// (insert-only watermark). cmp is targetMax compared to sourceMax: <0 behind, 0 equal, >0 ahead.
func ShouldSkipInsertOnlyDelta(hasSourceMax, hasTargetMax bool, cmp int) bool {
	if !hasSourceMax || !hasTargetMax {
		return false
	}
	return cmp >= 0
}

func isIntegerSQLType(typeName string) bool {
	switch strings.ToLower(strings.TrimSpace(typeName)) {
	case "tinyint", "smallint", "int", "bigint":
		return true
	default:
		return false
	}
}
