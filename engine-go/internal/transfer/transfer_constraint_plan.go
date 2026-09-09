// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"encoding/json"
	"fmt"
	"strings"
)

// TransferConstraintPlan is the operator-reviewed destination disable/restore plan.
type TransferConstraintPlan struct {
	OperatorReviewed bool                     `json:"operator_reviewed"`
	OnStop           string                   `json:"on_stop"`
	Items            []TransferConstraintItem `json:"items"`
}

type TransferConstraintItem struct {
	Key        string `json:"key"`
	ObjectID   string `json:"object_id"`
	Kind       string `json:"kind"`
	Schema     string `json:"schema"`
	Table      string `json:"table"`
	Action     string `json:"action"`
	Definition string `json:"definition"`
}

func ParseTransferConstraintPlan(raw json.RawMessage) (*TransferConstraintPlan, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return &TransferConstraintPlan{}, nil
	}
	var plan TransferConstraintPlan
	if err := json.Unmarshal(raw, &plan); err != nil {
		return nil, fmt.Errorf("unmarshal transfer constraint plan: %w", err)
	}
	if plan.OnStop == "" {
		plan.OnStop = "restore_now"
	}
	return &plan, nil
}

func DisableConstraintItems(plan *TransferConstraintPlan) []TransferConstraintItem {
	if plan == nil {
		return nil
	}
	var out []TransferConstraintItem
	for _, item := range plan.Items {
		if strings.EqualFold(item.Action, "disable") {
			out = append(out, item)
		}
	}
	return out
}
