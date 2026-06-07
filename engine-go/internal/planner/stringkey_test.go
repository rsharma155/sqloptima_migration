// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package planner

import (
	"testing"

	"github.com/google/uuid"
)

func TestStringChunkerPlan(t *testing.T) {
	jobID := uuid.New()
	bounds := StringBounds{Min: "AE", Max: "ZW"}
	plans := StringChunker{}.Plan(jobID, "Sales", "CountryRegionCurrency", "CountryRegionCode", bounds)
	if len(plans) != 1 {
		t.Fatalf("expected 1 chunk, got %d", len(plans))
	}
	if plans[0].StartKey == nil || *plans[0].StartKey != "AE" {
		t.Fatalf("start key = %v, want AE", plans[0].StartKey)
	}
	if plans[0].EndKey == nil || *plans[0].EndKey != "ZW" {
		t.Fatalf("end key = %v, want ZW", plans[0].EndKey)
	}
}

func TestStringBoundsIsEmpty(t *testing.T) {
	if !(StringBounds{}).IsEmpty() {
		t.Fatal("zero bounds should be empty")
	}
	if !(StringBounds{Min: "Z", Max: "A"}).IsEmpty() {
		t.Fatal("inverted bounds should be empty")
	}
	if (StringBounds{Min: "      ", Max: "zh-cht"}).IsEmpty() {
		t.Fatal("whitespace-only min is a valid nchar PK bound (Production.Culture)")
	}
}

func TestStringChunkerWhitespacePKBounds(t *testing.T) {
	jobID := uuid.New()
	// AdventureWorks Production.Culture: MIN(CultureID) is six spaces, MAX is zh-cht.
	bounds := StringBounds{Min: "      ", Max: "zh-cht"}
	plans := StringChunker{}.Plan(jobID, "Production", "Culture", "CultureID", bounds)
	if len(plans) != 1 {
		t.Fatalf("expected 1 chunk for whitespace-padded nchar PK, got %d", len(plans))
	}
	if plans[0].StartKey == nil || *plans[0].StartKey != "      " {
		t.Fatalf("start key = %q, want six spaces", *plans[0].StartKey)
	}
}
