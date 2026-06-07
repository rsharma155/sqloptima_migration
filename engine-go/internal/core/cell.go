// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core

// CellValue represents a single decoded column value flowing through the
// extraction → loading pipeline.
//
// Temporal CellDate and CellTimestampMicros store values using the Unix epoch
// (1970-01-01) as produced by the SQL Server driver.  The loader applies the
// PostgreSQL epoch shift (to 2000-01-01) when encoding the binary COPY payload.
//
// The interface is sealed (unexported marker method) so only this package can
// implement new cell types, preventing accidental extension in tests.
type CellValue interface {
	isCellValue()
}

// CellNull represents a SQL NULL in any column.
type CellNull struct{}

// CellBool holds a boolean value (SQL Server "bit").
type CellBool struct{ V bool }

// CellI16 holds a 16-bit signed integer (SQL Server tinyint / smallint).
type CellI16 struct{ V int16 }

// CellI32 holds a 32-bit signed integer (SQL Server int).
type CellI32 struct{ V int32 }

// CellI64 holds a 64-bit signed integer (SQL Server bigint).
type CellI64 struct{ V int64 }

// CellF32 holds a 32-bit float (SQL Server real).
type CellF32 struct{ V float32 }

// CellF64 holds a 64-bit float (SQL Server float).
type CellF64 struct{ V float64 }

// CellStr holds a UTF-8 string (char / varchar / nvarchar / xml).
type CellStr struct{ V string }

// CellBin holds raw bytes (binary / varbinary / rowversion).
type CellBin struct{ V []byte }

// CellDate holds days since the Unix epoch (1970-01-01).
// The loader shifts to the PostgreSQL epoch (2000-01-01) on encode.
type CellDate struct{ V int32 }

// CellTimestampMicros holds microseconds since the Unix epoch (1970-01-01).
// The loader shifts to the PostgreSQL epoch on encode.
type CellTimestampMicros struct{ V int64 }

// CellTimeMicros holds microseconds since midnight (time-of-day only).
type CellTimeMicros struct{ V int64 }

// CellUUID holds a 16-byte UUID in big-endian network byte order.
type CellUUID struct{ V [16]byte }

// Sealed marker implementations.
func (CellNull) isCellValue()            {}
func (CellBool) isCellValue()            {}
func (CellI16) isCellValue()             {}
func (CellI32) isCellValue()             {}
func (CellI64) isCellValue()             {}
func (CellF32) isCellValue()             {}
func (CellF64) isCellValue()             {}
func (CellStr) isCellValue()             {}
func (CellBin) isCellValue()             {}
func (CellDate) isCellValue()            {}
func (CellTimestampMicros) isCellValue() {}
func (CellTimeMicros) isCellValue()      {}
func (CellUUID) isCellValue()            {}
