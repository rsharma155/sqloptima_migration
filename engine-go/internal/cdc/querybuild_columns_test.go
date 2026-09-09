// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func TestBuildCaptureReadQueryWithColumnsIncludesDataColsAndTop(t *testing.T) {
	sql := cdc.BuildCaptureReadQueryWithColumns("dbo_orders", []string{"id", "amount"}, 500)
	if !strings.Contains(sql, "TOP (500)") {
		t.Errorf("expected TOP (500), got: %s", sql)
	}
	if !strings.Contains(sql, "[id]") || !strings.Contains(sql, "[amount]") {
		t.Errorf("expected data columns, got: %s", sql)
	}
	if !strings.Contains(sql, "__$start_lsn > @P1") {
		t.Errorf("expected @P1 parameter, got: %s", sql)
	}
}

func TestBuildCaptureReadQueryWithColumnsQuotesInjection(t *testing.T) {
	sql := cdc.BuildCaptureReadQueryWithColumns("dbo_t", []string{"a]; DROP--"}, 10)
	if !strings.Contains(sql, "[a]]; DROP--]") {
		t.Errorf("column must be bracket-escaped, got: %s", sql)
	}
}
