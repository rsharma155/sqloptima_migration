// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"encoding/binary"
	"fmt"
	"math"
)

// PostgreSQL binary COPY wire-format encoder.
//
// Implements the format documented under "Binary Format" in the PostgreSQL COPY
// protocol. All multi-byte integers are big-endian (network byte order).
//
// Layout:
//
//	Header  : 11-byte signature "PGCOPY\n\xff\r\n\0"
//	          + Int32 flags (0)
//	          + Int32 header-extension length (0)
//	Tuple   : Int16 field count
//	          + per-field: Int32 length, then that many data bytes
//	            (length = -1 means SQL NULL; no data bytes follow)
//	Trailer : Int16 = -1

// pgCopySignature is the fixed 11-byte header that begins every binary COPY stream.
var pgCopySignature = [11]byte{'P', 'G', 'C', 'O', 'P', 'Y', '\n', 0xff, '\r', '\n', 0}

// CopyValue is the interface implemented by all column values in a COPY row.
// Values are responsible for encoding their own data bytes.
type CopyValue interface {
	// copyDataBytes returns the encoded data bytes for this value, or nil for NULL.
	copyDataBytes() []byte
}

// ---------------------------------------------------------------------------
// Concrete CopyValue types
// ---------------------------------------------------------------------------

// CopyNull encodes SQL NULL (length = -1, no data bytes).
type CopyNull struct{}

// CopyBool encodes a PostgreSQL boolean (1 byte: 0x01 = true, 0x00 = false).
type CopyBool struct{ V bool }

// CopyInt16 encodes a PostgreSQL smallint (2 bytes, big-endian).
type CopyInt16 struct{ V int16 }

// CopyInt32 encodes a PostgreSQL integer (4 bytes, big-endian).
type CopyInt32 struct{ V int32 }

// CopyInt64 encodes a PostgreSQL bigint (8 bytes, big-endian).
type CopyInt64 struct{ V int64 }

// CopyFloat32 encodes a PostgreSQL real (4 bytes, IEEE 754 big-endian).
type CopyFloat32 struct{ V float32 }

// CopyFloat64 encodes a PostgreSQL double precision (8 bytes, IEEE 754 big-endian).
type CopyFloat64 struct{ V float64 }

// CopyText encodes a PostgreSQL text / varchar as raw UTF-8 bytes.
type CopyText struct{ V string }

// CopyBytes encodes a PostgreSQL bytea as raw bytes.
type CopyBytes struct{ V []byte }

// CopyDate encodes a PostgreSQL date as days since 2000-01-01 (PostgreSQL epoch).
// The extractor returns days since 1970-01-01; the loader shifts by pgEpochDays.
type CopyDate struct{ V int32 }

// CopyTimestampMicros encodes a PostgreSQL timestamp / timestamptz as
// microseconds since 2000-01-01 (PostgreSQL epoch).
type CopyTimestampMicros struct{ V int64 }

// CopyTimeMicros encodes a PostgreSQL time as microseconds since midnight.
type CopyTimeMicros struct{ V int64 }

// CopyUUID encodes a PostgreSQL uuid as 16 raw bytes.
type CopyUUID struct{ V [16]byte }

func (v CopyNull) copyDataBytes() []byte            { return nil }
func (v CopyBool) copyDataBytes() []byte            { if v.V { return []byte{1} }; return []byte{0} }
func (v CopyInt16) copyDataBytes() []byte           { b := [2]byte{}; binary.BigEndian.PutUint16(b[:], uint16(v.V)); return b[:] }
func (v CopyInt32) copyDataBytes() []byte           { b := [4]byte{}; binary.BigEndian.PutUint32(b[:], uint32(v.V)); return b[:] }
func (v CopyInt64) copyDataBytes() []byte           { b := [8]byte{}; binary.BigEndian.PutUint64(b[:], uint64(v.V)); return b[:] }
func (v CopyFloat32) copyDataBytes() []byte         { b := [4]byte{}; binary.BigEndian.PutUint32(b[:], math.Float32bits(v.V)); return b[:] }
func (v CopyFloat64) copyDataBytes() []byte         { b := [8]byte{}; binary.BigEndian.PutUint64(b[:], math.Float64bits(v.V)); return b[:] }
func (v CopyText) copyDataBytes() []byte            { return []byte(v.V) }
func (v CopyBytes) copyDataBytes() []byte           { return v.V }
func (v CopyDate) copyDataBytes() []byte            { return CopyInt32{V: v.V}.copyDataBytes() }
func (v CopyTimestampMicros) copyDataBytes() []byte { return CopyInt64{V: v.V}.copyDataBytes() }
func (v CopyTimeMicros) copyDataBytes() []byte      { return CopyInt64{V: v.V}.copyDataBytes() }
func (v CopyUUID) copyDataBytes() []byte            { return v.V[:] }

// ---------------------------------------------------------------------------
// BinaryCopyEncoder
// ---------------------------------------------------------------------------

// BinaryCopyEncoder builds a complete PostgreSQL binary COPY payload in memory.
//
// Lifecycle:
//  1. NewBinaryCopyEncoder(fieldCount) — emits the fixed COPY header.
//  2. WriteRow(values)                 — appends one tuple; returns error on arity mismatch.
//  3. Finish()                         — appends the -1 trailer and returns the full payload.
type BinaryCopyEncoder struct {
	buf         []byte
	fieldCount  int
	rowsWritten int64
}

// NewBinaryCopyEncoder creates an encoder for rows with fieldCount columns and
// immediately writes the COPY file header to the internal buffer.
func NewBinaryCopyEncoder(fieldCount int) *BinaryCopyEncoder {
	e := &BinaryCopyEncoder{
		fieldCount: fieldCount,
		buf:        make([]byte, 0, 256),
	}
	e.buf = append(e.buf, pgCopySignature[:]...)
	e.buf = appendInt32BE(e.buf, 0) // flags
	e.buf = appendInt32BE(e.buf, 0) // header extension length
	return e
}

// WriteRow appends a single tuple. Returns an error if len(values) != fieldCount.
func (e *BinaryCopyEncoder) WriteRow(values []CopyValue) error {
	if len(values) != e.fieldCount {
		return fmt.Errorf("row arity mismatch: expected %d fields, got %d",
			e.fieldCount, len(values))
	}
	e.buf = appendInt16BE(e.buf, int16(e.fieldCount))
	for _, v := range values {
		data := v.copyDataBytes()
		if data == nil {
			e.buf = appendInt32BE(e.buf, -1) // SQL NULL
		} else {
			e.buf = appendInt32BE(e.buf, int32(len(data)))
			e.buf = append(e.buf, data...)
		}
	}
	e.rowsWritten++
	return nil
}

// RowsWritten returns the number of tuples written so far.
func (e *BinaryCopyEncoder) RowsWritten() int64 { return e.rowsWritten }

// Finish writes the Int16(-1) trailer and returns the complete COPY payload.
// The encoder must not be used after calling Finish.
func (e *BinaryCopyEncoder) Finish() []byte {
	e.buf = appendInt16BE(e.buf, -1)
	return e.buf
}

// ---------------------------------------------------------------------------
// Big-endian write helpers
// ---------------------------------------------------------------------------

func appendInt16BE(b []byte, v int16) []byte {
	return append(b, byte(uint16(v)>>8), byte(v))
}

func appendInt32BE(b []byte, v int32) []byte {
	u := uint32(v)
	return append(b, byte(u>>24), byte(u>>16), byte(u>>8), byte(u))
}
