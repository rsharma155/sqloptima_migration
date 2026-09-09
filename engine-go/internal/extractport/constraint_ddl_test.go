// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractport_test

import (
	"strings"
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractport"
)

func TestBuildPostgresDropConstraintQuotes(t *testing.T) {
	got := extractport.BuildPostgresDropConstraint("public", `ord"ers`, "orders_fk")
	want := `ALTER TABLE "public"."ord""ers" DROP CONSTRAINT "orders_fk"`
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestBuildPostgresAddConstraintRejectsSemicolon(t *testing.T) {
	_, err := extractport.BuildPostgresAddConstraint("public", "orders", "ck", "CHECK (x > 0); DROP TABLE t")
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestBuildPostgresAddConstraint(t *testing.T) {
	got, err := extractport.BuildPostgresAddConstraint("public", "orders", "ck", "CHECK ((amount > 0))")
	if err != nil {
		t.Fatal(err)
	}
	want := `ALTER TABLE "public"."orders" ADD CONSTRAINT "ck" CHECK ((amount > 0))`
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestBuildPostgresDisableTrigger(t *testing.T) {
	got := extractport.BuildPostgresDisableTrigger("public", "orders", "trg")
	if got != `ALTER TABLE "public"."orders" DISABLE TRIGGER "trg"` {
		t.Fatalf("got %s", got)
	}
}

func TestBuildMSSQLNocheckConstraint(t *testing.T) {
	got := extractport.BuildMSSQLNoCheckConstraint("dbo", "orders", "fk")
	if got != "ALTER TABLE [dbo].[orders] NOCHECK CONSTRAINT [fk]" {
		t.Fatalf("got %s", got)
	}
	if strings.Contains(got, "'") {
		t.Fatal("must not interpolate literals")
	}
}

func TestBuildMSSQLDisableIndex(t *testing.T) {
	got := extractport.BuildMSSQLDisableIndex("dbo", "orders", "ix")
	if got != "ALTER INDEX [ix] ON [dbo].[orders] DISABLE" {
		t.Fatalf("got %s", got)
	}
}
