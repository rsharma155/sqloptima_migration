// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core

import "strings"

// LogicalType is the normalized column type used throughout the engine.
// Both the PostgreSQL DDL type and the in-memory Go representation are
// derived from this enum, guaranteeing a single source of truth for the
// SQL Server → PostgreSQL conversion matrix.
type LogicalType int

const (
	LogicalBool        LogicalType = iota
	LogicalInt16                   // SQL Server tinyint / smallint → PostgreSQL smallint
	LogicalInt32                   // SQL Server int → PostgreSQL integer
	LogicalInt64                   // SQL Server bigint → PostgreSQL bigint
	LogicalFloat32                 // SQL Server real → PostgreSQL real
	LogicalFloat64                 // SQL Server float → PostgreSQL double precision
	LogicalDecimal                 // SQL Server decimal/numeric/money → PostgreSQL numeric
	LogicalUtf8                    // fixed-length or bounded varchar/nvarchar → varchar
	LogicalLargeUtf8               // varchar(max) / nvarchar(max) / text / xml → text
	LogicalBinary                  // binary / varbinary → bytea
	LogicalLargeBinary             // varbinary(max) / image → bytea
	LogicalDate                    // SQL Server date → PostgreSQL date
	LogicalTime                    // SQL Server time → PostgreSQL time
	LogicalTimestamp               // datetime / datetime2 / smalldatetime → timestamp
	LogicalTimestampTz             // datetimeoffset → timestamptz
	LogicalUUID                    // uniqueidentifier → uuid
	LogicalUnsupported             // hierarchyid / geography / geometry / sql_variant
)

// PostgresType returns the PostgreSQL DDL type name for this logical type.
func (l LogicalType) PostgresType() string {
	switch l {
	case LogicalBool:        return "boolean"
	case LogicalInt16:       return "smallint"
	case LogicalInt32:       return "integer"
	case LogicalInt64:       return "bigint"
	case LogicalFloat32:     return "real"
	case LogicalFloat64:     return "double precision"
	case LogicalDecimal:     return "numeric"
	case LogicalUtf8:        return "varchar"
	case LogicalLargeUtf8:   return "text"
	case LogicalBinary:      return "bytea"
	case LogicalLargeBinary: return "bytea"
	case LogicalDate:        return "date"
	case LogicalTime:        return "time"
	case LogicalTimestamp:   return "timestamp"
	case LogicalTimestampTz: return "timestamptz"
	case LogicalUUID:        return "uuid"
	default:                 return "text" // fallback for Unsupported
	}
}

// IsLOB reports whether this type requires the LOB streaming path rather than
// inline row buffering.
func (l LogicalType) IsLOB() bool {
	return l == LogicalLargeUtf8 || l == LogicalLargeBinary
}

// NeedsManualReview reports whether this type has no safe automatic mapping.
func (l LogicalType) NeedsManualReview() bool { return l == LogicalUnsupported }

// maxLengthSentinel is the value SQL Server stores in max_length for (max) types.
const maxLengthSentinel int32 = -1

// MapSQLServerType maps a SQL Server column type + max_length to a LogicalType.
// The type name is matched case-insensitively and any precision/scale suffix
// (e.g. "decimal(18,2)") is stripped before matching.
// max_length == -1 means the type is declared as (MAX), i.e. unbounded.
func MapSQLServerType(typeName string, maxLength int32) LogicalType {
	// Strip any "(...)" precision/scale suffix and normalise case.
	base := strings.ToLower(strings.TrimSpace(typeName))
	if i := strings.IndexByte(base, '('); i >= 0 {
		base = strings.TrimSpace(base[:i])
	}

	isMax := maxLength == maxLengthSentinel

	switch base {
	case "bit":
		return LogicalBool
	case "tinyint":
		return LogicalInt16 // PostgreSQL has no tinyint; widen to smallint
	case "smallint":
		return LogicalInt16
	case "int":
		return LogicalInt32
	case "bigint":
		return LogicalInt64
	case "real":
		return LogicalFloat32
	case "float":
		return LogicalFloat64
	case "decimal", "numeric", "money", "smallmoney":
		return LogicalDecimal
	case "char", "varchar":
		if isMax {
			return LogicalLargeUtf8
		}
		return LogicalUtf8
	case "nchar", "nvarchar":
		if isMax {
			return LogicalLargeUtf8
		}
		return LogicalUtf8
	case "text", "ntext":
		return LogicalLargeUtf8
	case "binary", "varbinary":
		if isMax {
			return LogicalLargeBinary
		}
		return LogicalBinary
	case "image":
		return LogicalLargeBinary
	case "rowversion", "timestamp":
		return LogicalBinary // 8-byte row-version token
	case "date":
		return LogicalDate
	case "time":
		return LogicalTime
	case "datetime", "datetime2", "smalldatetime":
		return LogicalTimestamp
	case "datetimeoffset":
		return LogicalTimestampTz
	case "uniqueidentifier":
		return LogicalUUID
	case "xml":
		return LogicalLargeUtf8
	default:
		// hierarchyid, geography, geometry, sql_variant have no safe mapping.
		return LogicalUnsupported
	}
}
