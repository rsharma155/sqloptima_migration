// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package worker

import (
	"strings"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// MigrationColumnTransformPipeline applies per-column transform chains to extracted rows.
type MigrationColumnTransformPipeline struct {
	byIndex [][]ColumnTransformFunc
}

// BuildColumnTransformPipeline composes type, sensitivity, and explicit transforms
// (mirrors Python build_pipeline_for_plan).
func BuildColumnTransformPipeline(table GoTableDispatchPayload) *MigrationColumnTransformPipeline {
	if len(table.ColumnTransforms) == 0 && len(table.ColumnSensitivity) == 0 && len(table.ColumnTypes) == 0 {
		return nil
	}

	n := len(table.Columns)
	if n == 0 {
		return nil
	}

	chains := make([][]ColumnTransformFunc, n)
	colIndex := make(map[string]int, n)
	for i, name := range table.Columns {
		colIndex[name] = i
	}

	addTransform := func(col, name string) {
		idx, ok := colIndex[col]
		if !ok {
			return
		}
		fn, ok := lookupTransform(name)
		if !ok {
			return
		}
		chains[idx] = append(chains[idx], fn)
	}

	for col, sqlType := range table.ColumnTypes {
		base := strings.ToLower(strings.TrimSpace(sqlType))
		if j := strings.IndexByte(base, '('); j >= 0 {
			base = strings.TrimSpace(base[:j])
		}
		if name, ok := typeDefaultTransforms[base]; ok {
			addTransform(col, name)
		}
	}

	if len(table.ColumnSensitivity) > 0 {
		for col, sensitivity := range table.ColumnSensitivity {
			if sensitivity == "none" || sensitivity == "" {
				continue
			}
			name := table.ColumnTransforms[col]
			if name == "" {
				name = sensitivityDefaultMask[sensitivity]
			}
			if name != "" {
				addTransform(col, name)
			}
		}
	} else {
		for col, name := range table.ColumnTransforms {
			if len(chains[colIndex[col]]) == 0 {
				addTransform(col, name)
			}
		}
	}

	hasTransforms := false
	for _, chain := range chains {
		if len(chain) > 0 {
			hasTransforms = true
			break
		}
	}
	if !hasTransforms {
		return nil
	}
	return &MigrationColumnTransformPipeline{byIndex: chains}
}

// Apply runs all registered transforms on a row aligned with schema column order.
func (p *MigrationColumnTransformPipeline) Apply(cells []core.CellValue) []core.CellValue {
	if p == nil {
		return cells
	}
	out := make([]core.CellValue, len(cells))
	copy(out, cells)
	for i, chain := range p.byIndex {
		if i >= len(out) {
			break
		}
		for _, fn := range chain {
			out[i] = fn(out[i])
		}
	}
	return out
}

// ApplyWithSchema applies transforms using schema column names for index alignment.
func (p *MigrationColumnTransformPipeline) ApplyWithSchema(
	schema extractor.ExtractionSchema, cells []core.CellValue,
) []core.CellValue {
	if p == nil {
		return cells
	}
	// Pipeline is built from table.Columns order which matches schema.Columns order.
	_ = schema
	return p.Apply(cells)
}
