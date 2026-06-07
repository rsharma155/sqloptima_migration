// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractor

import (
	"context"
	"database/sql"
	"fmt"
)

const defaultLOBChunkSizeBytes = 1024 * 1024 // 1 MB — mirrors Python LobChunkReader default

// LobChunkReader reads a single LOB column via SQL Server SUBSTRING() in bounded chunks.
type LobChunkReader struct {
	ChunkSizeBytes int
}

// DefaultLobChunkReader returns a reader with the Python-default 1 MB chunk size.
func DefaultLobChunkReader() *LobChunkReader {
	return &LobChunkReader{ChunkSizeBytes: defaultLOBChunkSizeBytes}
}

// BuildLOBSubstringQuery returns parameterised SUBSTRING SQL for one LOB chunk.
func BuildLOBSubstringQuery(schema, table, col, pkCol string) string {
	return fmt.Sprintf(
		"SELECT SUBSTRING(%s, @P1, @P2) AS chunk FROM %s WHERE %s = @P3",
		quoteIdentMSSQL(col),
		quotedTableMSSQL(schema, table),
		quoteIdentMSSQL(pkCol),
	)
}

// ReadLOB assembles a full LOB value for one row using 1-based SUBSTRING offsets.
func (r *LobChunkReader) ReadLOB(
	ctx context.Context,
	db *sql.DB,
	schema, table, pkCol, col string,
	pkValue any,
) (any, error) {
	if r.ChunkSizeBytes < 1 {
		r.ChunkSizeBytes = defaultLOBChunkSizeBytes
	}
	query := BuildLOBSubstringQuery(schema, table, col, pkCol)

	sqlOffset := 1
	var chunksBin [][]byte
	var chunksText []string
	var isBinary *bool

	for {
		var chunk any
		err := db.QueryRowContext(ctx, query,
			sql.Named("P1", sqlOffset),
			sql.Named("P2", r.ChunkSizeBytes),
			sql.Named("P3", pkValue),
		).Scan(&chunk)
		if err == sql.ErrNoRows {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("read LOB chunk for %s.%s: %w", schema, table, err)
		}
		if chunk == nil {
			if sqlOffset == 1 {
				return nil, nil
			}
			break
		}

		switch v := chunk.(type) {
		case []byte:
			if len(v) == 0 {
				if isBinary == nil {
					return nil, nil
				}
				goto done
			}
			if isBinary == nil {
				b := true
				isBinary = &b
			}
			chunksBin = append(chunksBin, v)
		case string:
			if len(v) == 0 {
				if isBinary == nil {
					return nil, nil
				}
				goto done
			}
			if isBinary == nil {
				b := false
				isBinary = &b
			}
			chunksText = append(chunksText, v)
		default:
			return nil, fmt.Errorf("unexpected LOB chunk type %T", chunk)
		}
		sqlOffset += r.ChunkSizeBytes
	}
done:
	if isBinary == nil {
		return nil, nil
	}
	if *isBinary {
		total := 0
		for _, c := range chunksBin {
			total += len(c)
		}
		out := make([]byte, 0, total)
		for _, c := range chunksBin {
			out = append(out, c...)
		}
		return out, nil
	}
	return joinStrings(chunksText), nil
}

func joinStrings(parts []string) string {
	if len(parts) == 0 {
		return ""
	}
	if len(parts) == 1 {
		return parts[0]
	}
	n := 0
	for _, p := range parts {
		n += len(p)
	}
	b := make([]byte, 0, n)
	for _, p := range parts {
		b = append(b, p...)
	}
	return string(b)
}
