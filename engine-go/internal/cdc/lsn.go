// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"strings"
)

// LSN is a SQL Server Log Sequence Number stored as 10 big-endian bytes.
//
// Because the bytes are stored big-endian, lexicographic comparison of the raw
// 10-byte array yields correct chronological ordering — so LSN.Compare() and
// Go's standard sort package can be used directly without clock-skew issues
// that a timestamp watermark would suffer.
type LSN [10]byte

// ZeroLSN is the zero-value LSN; it sorts before any real LSN and indicates
// that no changes have been consumed yet.
var ZeroLSN LSN

// LSNFromBytes constructs an LSN from a raw 10-byte array.
func LSNFromBytes(b [10]byte) LSN { return LSN(b) }

// LSNFromHex parses a hex string (with or without a "0x" prefix) into an LSN.
// The string must decode to exactly 10 bytes; returns (ZeroLSN, false) otherwise.
func LSNFromHex(s string) (LSN, bool) {
	s = strings.TrimPrefix(s, "0x")
	if len(s) != 20 {
		return ZeroLSN, false
	}
	b, err := hex.DecodeString(s)
	if err != nil || len(b) != 10 {
		return ZeroLSN, false
	}
	var lsn LSN
	copy(lsn[:], b)
	return lsn, true
}

// ToHex returns the LSN as a 20-character lowercase hex string (no "0x" prefix).
func (l LSN) ToHex() string { return hex.EncodeToString(l[:]) }

// String returns the LSN in the canonical "0x<20 hex chars>" display format.
func (l LSN) String() string { return fmt.Sprintf("0x%s", l.ToHex()) }

// IsZero reports whether this is the zero LSN (no changes consumed yet).
func (l LSN) IsZero() bool { return l == ZeroLSN }

// Compare returns -1, 0, or 1 mirroring bytes.Compare.
// Big-endian byte ordering equals chronological ordering, so this is safe.
func (l LSN) Compare(other LSN) int { return bytes.Compare(l[:], other[:]) }

// Less reports whether l precedes other chronologically.
func (l LSN) Less(other LSN) bool { return l.Compare(other) < 0 }

// Equal reports whether l and other represent the same log position.
func (l LSN) Equal(other LSN) bool { return l == other }
