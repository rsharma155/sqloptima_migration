// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import (
	"fmt"

	"github.com/jackc/pgx/v5/pgtype"
)

// CopyNumeric encodes a decimal string using PostgreSQL binary numeric format.
type CopyNumeric struct{ V string }

func (v CopyNumeric) copyDataBytes() []byte {
	b, err := encodeNumericBinaryString(v.V)
	if err != nil {
		return nil
	}
	return b
}

// encodeNumericBinaryString converts a decimal text value to PostgreSQL COPY binary numeric bytes.
func encodeNumericBinaryString(s string) ([]byte, error) {
	var n pgtype.Numeric
	if err := n.Scan(s); err != nil {
		return nil, fmt.Errorf("parse numeric %q: %w", s, err)
	}
	enc := pgtype.NumericCodec{}.PlanEncode(nil, pgtype.NumericOID, pgtype.BinaryFormatCode, n)
	if enc == nil {
		return nil, fmt.Errorf("numeric binary encoder unavailable")
	}
	return enc.Encode(n, nil)
}
