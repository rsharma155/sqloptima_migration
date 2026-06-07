// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package cdc_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/cdc"
)

func cols() []string { return []string{"id", "name", "total"} }
func pk() []string   { return []string{"id"} }

func TestInsertBuildsUpsert(t *testing.T) {
	stmt := cdc.BuildApplyStatement("public", "orders", cdc.OpInsert, cols(), pk())
	if !stmt.Applicable {
		t.Fatal("INSERT must be applicable")
	}
	want := `INSERT INTO "public"."orders" ("id", "name", "total") VALUES ($1, $2, $3) ` +
		`ON CONFLICT ("id") DO UPDATE SET "name" = EXCLUDED."name", "total" = EXCLUDED."total"`
	if stmt.SQL != want {
		t.Errorf("INSERT SQL:\n  got:  %s\n  want: %s", stmt.SQL, want)
	}
}

func TestUpdateAfterBuildsUpsertSameAsInsert(t *testing.T) {
	ins := cdc.BuildApplyStatement("public", "orders", cdc.OpInsert, cols(), pk())
	upd := cdc.BuildApplyStatement("public", "orders", cdc.OpUpdateAfter, cols(), pk())
	if ins.SQL != upd.SQL {
		t.Error("INSERT and UPDATE_AFTER must produce identical upsert SQL")
	}
}

func TestDeleteBuildsPKPredicate(t *testing.T) {
	stmt := cdc.BuildApplyStatement("public", "orders", cdc.OpDelete, cols(), pk())
	if !stmt.Applicable {
		t.Fatal("DELETE must be applicable")
	}
	want := `DELETE FROM "public"."orders" WHERE "id" = $1`
	if stmt.SQL != want {
		t.Errorf("DELETE SQL:\n  got:  %s\n  want: %s", stmt.SQL, want)
	}
}

func TestDeleteWithCompositePK(t *testing.T) {
	compositePK := []string{"tenant_id", "id"}
	stmt := cdc.BuildApplyStatement("public", "orders", cdc.OpDelete, cols(), compositePK)
	want := `DELETE FROM "public"."orders" WHERE "tenant_id" = $1 AND "id" = $2`
	if stmt.SQL != want {
		t.Errorf("composite PK DELETE:\n  got:  %s\n  want: %s", stmt.SQL, want)
	}
}

func TestUpdateBeforeReturnsNotApplicable(t *testing.T) {
	stmt := cdc.BuildApplyStatement("public", "orders", cdc.OpUpdateBefore, cols(), pk())
	if stmt.Applicable {
		t.Error("UPDATE_BEFORE must not be applicable")
	}
}

func TestAllPKTableUsesDoNothing(t *testing.T) {
	allPK := []string{"a", "b"}
	stmt := cdc.BuildApplyStatement("public", "t", cdc.OpInsert, allPK, allPK)
	if !strings.Contains(stmt.SQL, "DO NOTHING") {
		t.Errorf("all-PK table must use DO NOTHING, got: %s", stmt.SQL)
	}
}

func TestMissingPKReturnsNotApplicable(t *testing.T) {
	stmt := cdc.BuildApplyStatement("public", "t", cdc.OpInsert, cols(), nil)
	if stmt.Applicable {
		t.Error("missing PK must return not-applicable")
	}
}

func TestPlaceholdersMatchColumnCount(t *testing.T) {
	stmt := cdc.BuildApplyStatement("public", "orders", cdc.OpInsert, cols(), pk())
	if !strings.Contains(stmt.SQL, "$1, $2, $3") {
		t.Errorf("must have 3 placeholders, got: %s", stmt.SQL)
	}
}

func TestIdentifierInjectionNeutralised(t *testing.T) {
	stmt := cdc.BuildApplyStatement("public", `t"; DROP TABLE users; --`, cdc.OpDelete, cols(), pk())
	if !strings.Contains(stmt.SQL, `"t""; DROP TABLE users; --"`) {
		t.Errorf("double-quote injection must be neutralised, got: %s", stmt.SQL)
	}
}
