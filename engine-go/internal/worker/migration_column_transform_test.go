// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

func TestTransformBitToBool(t *testing.T) {
	out := transformBitToBool(core.CellI32{V: 1})
	b, ok := out.(core.CellBool)
	if !ok || !b.V {
		t.Fatalf("expected true bool, got %#v", out)
	}
}

func TestTransformMaskHash(t *testing.T) {
	out := transformMaskHash(core.CellStr{V: "secret"})
	s, ok := out.(core.CellStr)
	if !ok || len(s.V) != 64 {
		t.Fatalf("expected 64-char hex hash, got %#v", out)
	}
	if transformMaskHash(core.CellNull{}) != (core.CellNull{}) {
		t.Fatal("null must stay null")
	}
}

func TestTransformMaskPartialEmail(t *testing.T) {
	out := transformMaskPartialEmail(core.CellStr{V: "alice@example.com"})
	s := out.(core.CellStr)
	if s.V != "a***@example.com" {
		t.Fatalf("got %q", s.V)
	}
}

func TestTransformMaskLastFour(t *testing.T) {
	out := transformMaskLastFour(core.CellStr{V: "4111-1111-1111-1234"})
	s := out.(core.CellStr)
	if s.V != "****1234" {
		t.Fatalf("got %q", s.V)
	}
}

func TestTransformStripTrailingNulls(t *testing.T) {
	out := transformStripTrailingNulls(core.CellStr{V: "abc\x00\x00"})
	if out.(core.CellStr).V != "abc" {
		t.Fatalf("got %#v", out)
	}
}

func TestBuildColumnTransformPipeline_sensitivityAndTypes(t *testing.T) {
	table := GoTableDispatchPayload{
		Columns: []string{"is_active", "email", "amount"},
		ColumnTypes: map[string]string{
			"is_active": "bit",
			"amount":    "money",
		},
		ColumnSensitivity: map[string]string{
			"email": "pii",
		},
	}
	p := BuildColumnTransformPipeline(table)
	if p == nil {
		t.Fatal("expected pipeline")
	}
	cells := []core.CellValue{
		core.CellI32{V: 1},
		core.CellStr{V: "user@test.com"},
		core.CellF64{V: 9.99},
	}
	out := p.Apply(cells)
	if _, ok := out[0].(core.CellBool); !ok {
		t.Fatalf("bit column: got %#v", out[0])
	}
	if out[1].(core.CellStr).V == "user@test.com" {
		t.Fatal("email should be hashed")
	}
	if out[2].(core.CellStr).V == "" {
		t.Fatal("amount should be string decimal")
	}
}

func TestBuildColumnTransformPipeline_explicitOverride(t *testing.T) {
	table := GoTableDispatchPayload{
		Columns: []string{"ssn"},
		ColumnSensitivity: map[string]string{
			"ssn": "pii",
		},
		ColumnTransforms: map[string]string{
			"ssn": "mask_redact",
		},
	}
	p := BuildColumnTransformPipeline(table)
	out := p.Apply([]core.CellValue{core.CellStr{V: "123-45-6789"}})
	if out[0].(core.CellStr).V != "***REDACTED***" {
		t.Fatalf("got %#v", out[0])
	}
}

func TestBuildColumnTransformPipeline_nilWhenEmpty(t *testing.T) {
	if p := BuildColumnTransformPipeline(GoTableDispatchPayload{Columns: []string{"id"}}); p != nil {
		t.Fatal("expected nil pipeline")
	}
}
