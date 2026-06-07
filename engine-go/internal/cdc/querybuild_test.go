// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func TestCaptureReadTargetsCTTable(t *testing.T) {
	sql := cdc.BuildCaptureReadQuery("dbo_orders")
	if !strings.Contains(sql, "cdc.[dbo_orders_CT]") {
		t.Errorf("query must target cdc.[dbo_orders_CT], got: %s", sql)
	}
}

func TestCaptureReadIsParameterisedAndOrdered(t *testing.T) {
	sql := cdc.BuildCaptureReadQuery("dbo_orders")
	if !strings.Contains(sql, "__$start_lsn > @P1") {
		t.Errorf("query must use @P1 parameter, got: %s", sql)
	}
	if !strings.Contains(sql, "ORDER BY __$start_lsn, __$seqval") {
		t.Errorf("query must order by LSN then seqval, got: %s", sql)
	}
	// No literal LSN value must be interpolated.
	if strings.Contains(sql, "0x") {
		t.Errorf("query must not contain literal 0x LSN value, got: %s", sql)
	}
}

func TestCaptureInstanceInjectionNeutralised(t *testing.T) {
	sql := cdc.BuildCaptureReadQuery("x]; DROP TABLE users; --")
	if !strings.Contains(sql, "[x]]; DROP TABLE users; --_CT]") {
		t.Errorf("closing bracket must be doubled, got: %s", sql)
	}
}

func TestMaxLSNQueryUsesBuiltin(t *testing.T) {
	if !strings.Contains(cdc.BuildMaxLSNQuery(), "sys.fn_cdc_get_max_lsn()") {
		t.Error("max LSN query must use sys.fn_cdc_get_max_lsn()")
	}
}

func TestCDCEnabledQueryChecksCurrentDB(t *testing.T) {
	sql := cdc.BuildCDCEnabledQuery()
	if !strings.Contains(sql, "is_cdc_enabled") {
		t.Error("CDC enabled query must select is_cdc_enabled")
	}
	if !strings.Contains(sql, "DB_ID()") {
		t.Error("CDC enabled query must use DB_ID()")
	}
}
