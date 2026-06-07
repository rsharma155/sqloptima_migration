// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// ColumnTransformFunc mutates a single cell value (mirrors Python ColumnTransform).
type ColumnTransformFunc func(core.CellValue) core.CellValue

var emailLocalMask = regexp.MustCompile(`[^\d]`)

func transformBitToBool(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	if b, ok := c.(core.CellBool); ok {
		return b
	}
	switch v := c.(type) {
	case core.CellI16:
		return core.CellBool{V: v.V != 0}
	case core.CellI32:
		return core.CellBool{V: v.V != 0}
	case core.CellI64:
		return core.CellBool{V: v.V != 0}
	default:
		return c
	}
}

func transformMoneyToDecimal(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	switch v := c.(type) {
	case core.CellF64:
		return core.CellStr{V: fmt.Sprintf("%g", v.V)}
	case core.CellF32:
		return core.CellStr{V: fmt.Sprintf("%g", v.V)}
	case core.CellStr:
		return v
	case core.CellI64:
		return core.CellStr{V: fmt.Sprintf("%d", v.V)}
	default:
		return core.CellStr{V: cellValueString(c)}
	}
}

func transformDatetimeToUTC(c core.CellValue) core.CellValue {
	// Go driver surfaces time.Time → CellTimestampMicros; no tz attach needed at cell layer.
	return c
}

func transformStripTrailingNulls(c core.CellValue) core.CellValue {
	s, ok := c.(core.CellStr)
	if !ok {
		return c
	}
	return core.CellStr{V: strings.TrimRight(s.V, "\x00")}
}

func transformIdentity(c core.CellValue) core.CellValue { return c }

func transformMaskNullify(core.CellValue) core.CellValue { return core.CellNull{} }

func transformMaskRedact(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	return core.CellStr{V: "***REDACTED***"}
}

func transformMaskHash(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	sum := sha256.Sum256([]byte(cellValueString(c)))
	return core.CellStr{V: hex.EncodeToString(sum[:])}
}

func transformMaskTokenize(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	sum := sha256.Sum256([]byte(cellValueString(c)))
	return core.CellStr{V: fmt.Sprintf("TOK_%s", hex.EncodeToString(sum[:])[:12])}
}

func transformMaskPartialEmail(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	text := cellValueString(c)
	at := strings.Index(text, "@")
	if at < 0 {
		return transformMaskRedact(c)
	}
	local, domain := text[:at], text[at+1:]
	if local == "" {
		return core.CellStr{V: "*@" + domain}
	}
	r, _ := utf8.DecodeRuneInString(local)
	return core.CellStr{V: fmt.Sprintf("%c***@%s", r, domain)}
}

func transformMaskLastFour(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	digits := emailLocalMask.ReplaceAllString(cellValueString(c), "")
	if len(digits) <= 4 {
		return core.CellStr{V: "****"}
	}
	return core.CellStr{V: "****" + digits[len(digits)-4:]}
}

func transformMaskFPENumeric(c core.CellValue) core.CellValue {
	if _, ok := c.(core.CellNull); ok {
		return c
	}
	raw := cellValueString(c)
	var digits strings.Builder
	for _, ch := range raw {
		if ch >= '0' && ch <= '9' {
			digits.WriteRune(ch)
		}
	}
	digStr := digits.String()
	if digStr == "" {
		return transformMaskRedact(c)
	}
	h := sha256.Sum256([]byte(digStr))
	mapped := make([]byte, len(digStr))
	for i := range digStr {
		mapped[i] = byte('0' + (h[i%len(h)] % 10))
	}
	di := 0
	out := make([]rune, 0, len(raw))
	for _, ch := range raw {
		if ch >= '0' && ch <= '9' {
			out = append(out, rune(mapped[di]))
			di++
		} else {
			out = append(out, ch)
		}
	}
	return core.CellStr{V: string(out)}
}

func cellValueString(c core.CellValue) string {
	switch v := c.(type) {
	case core.CellNull:
		return ""
	case core.CellBool:
		if v.V {
			return "true"
		}
		return "false"
	case core.CellStr:
		return v.V
	case core.CellI16:
		return fmt.Sprintf("%d", v.V)
	case core.CellI32:
		return fmt.Sprintf("%d", v.V)
	case core.CellI64:
		return fmt.Sprintf("%d", v.V)
	case core.CellF32:
		return fmt.Sprintf("%g", v.V)
	case core.CellF64:
		return fmt.Sprintf("%g", v.V)
	case core.CellBin:
		return string(v.V)
	default:
		return fmt.Sprintf("%v", c)
	}
}

// builtInColumnTransforms mirrors Python BUILT_IN_TRANSFORMS keys.
var builtInColumnTransforms = map[string]ColumnTransformFunc{
	"bit_to_bool":          transformBitToBool,
	"money_to_decimal":       transformMoneyToDecimal,
	"datetime_to_utc":        transformDatetimeToUTC,
	"strip_trailing_nulls":   transformStripTrailingNulls,
	"identity":               transformIdentity,
	"mask_nullify":           transformMaskNullify,
	"mask_redact":            transformMaskRedact,
	"mask_hash":              transformMaskHash,
	"mask_tokenize":          transformMaskTokenize,
	"mask_partial_email":     transformMaskPartialEmail,
	"mask_last_four":         transformMaskLastFour,
	"mask_fpe_numeric":       transformMaskFPENumeric,
}

var typeDefaultTransforms = map[string]string{
	"bit":          "bit_to_bool",
	"money":        "money_to_decimal",
	"smallmoney":   "money_to_decimal",
	"datetime2":    "datetime_to_utc",
	"datetime":     "datetime_to_utc",
	"smalldatetime": "datetime_to_utc",
	"nchar":        "strip_trailing_nulls",
	"char":         "strip_trailing_nulls",
}

var sensitivityDefaultMask = map[string]string{
	"pii":        "mask_hash",
	"phi":        "mask_nullify",
	"pci":        "mask_fpe_numeric",
	"credential": "mask_nullify",
}

func lookupTransform(name string) (ColumnTransformFunc, bool) {
	fn, ok := builtInColumnTransforms[name]
	return fn, ok
}
