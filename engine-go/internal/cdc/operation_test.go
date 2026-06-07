// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func TestParsesKnownCodes(t *testing.T) {
	cases := []struct {
		code int
		want cdc.CDCOperation
	}{
		{1, cdc.OpDelete},
		{2, cdc.OpInsert},
		{3, cdc.OpUpdateBefore},
		{4, cdc.OpUpdateAfter},
	}
	for _, tc := range cases {
		got, err := cdc.OperationFromCode(tc.code)
		if err != nil {
			t.Fatalf("OperationFromCode(%d) unexpected error: %v", tc.code, err)
		}
		if got != tc.want {
			t.Errorf("OperationFromCode(%d) = %v, want %v", tc.code, got, tc.want)
		}
	}
}

func TestUnknownCodeIsError(t *testing.T) {
	for _, bad := range []int{0, 5, 99, -1} {
		if _, err := cdc.OperationFromCode(bad); err == nil {
			t.Errorf("OperationFromCode(%d) should return error", bad)
		}
	}
}

func TestCodeRoundtrips(t *testing.T) {
	for _, op := range []cdc.CDCOperation{cdc.OpDelete, cdc.OpInsert, cdc.OpUpdateBefore, cdc.OpUpdateAfter} {
		got, err := cdc.OperationFromCode(op.Code())
		if err != nil || got != op {
			t.Errorf("code roundtrip failed for %v", op)
		}
	}
}

func TestUpdateBeforeIsNotApplicable(t *testing.T) {
	if cdc.OpUpdateBefore.IsApplicable() {
		t.Error("UPDATE_BEFORE must not be applicable")
	}
}

func TestInsertUpdateDeleteAreApplicable(t *testing.T) {
	for _, op := range []cdc.CDCOperation{cdc.OpInsert, cdc.OpDelete, cdc.OpUpdateAfter} {
		if !op.IsApplicable() {
			t.Errorf("%v must be applicable", op)
		}
	}
}
