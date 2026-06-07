// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader

import "testing"

func TestBuildUpsertUpdateSet(t *testing.T) {
	got := buildUpsertUpdateSet([]string{"id", "name"})
	want := `"id" = EXCLUDED."id", "name" = EXCLUDED."name"`
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestQuoteColumnList(t *testing.T) {
	got := quoteColumnList([]string{"Id", "bad\"col"})
	if got != `"Id", "bad""col"` {
		t.Fatalf("got %q", got)
	}
}
