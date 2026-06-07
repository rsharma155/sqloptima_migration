// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metrics_test

import (
	"context"
	"testing"
	"time"

	"github.com/ravisharma/sql-optima/engine-go/internal/metrics"
)

func TestInitProviderEmptyEndpointIsNoOp(t *testing.T) {
	shutdown, err := metrics.InitProvider(context.Background(), "", time.Second)
	if err != nil {
		t.Fatalf("InitProvider: %v", err)
	}
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
}

func TestInitProviderAcceptsURLFormEndpoint(t *testing.T) {
	// Should not fail parsing — export may fail later if nothing listens.
	shutdown, err := metrics.InitProvider(context.Background(), "http://localhost:4317", time.Hour)
	if err != nil {
		t.Fatalf("InitProvider with URL endpoint: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	_ = shutdown(ctx) // may time out without a collector; normalisation is what we verify
}
