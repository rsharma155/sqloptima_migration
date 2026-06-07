// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metrics

import (
	"context"
	"fmt"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/sdk/metric"
)

// normalizeOTLPEndpoint strips scheme/path so otlpmetricgrpc receives host:port.
// WithEndpoint expects "localhost:4317", not "http://localhost:4317".
func normalizeOTLPEndpoint(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	raw = strings.TrimPrefix(raw, "https://")
	raw = strings.TrimPrefix(raw, "http://")
	if slash := strings.Index(raw, "/"); slash >= 0 {
		raw = raw[:slash]
	}
	return raw
}

// InitProvider initialises the global OpenTelemetry MeterProvider with an OTLP
// gRPC exporter. Call Shutdown on the returned function when the process exits.
//
// If otlpEndpoint is empty, a no-op provider is installed (metrics disabled).
func InitProvider(ctx context.Context, otlpEndpoint string, exportInterval time.Duration) (func(context.Context) error, error) {
	endpoint := normalizeOTLPEndpoint(otlpEndpoint)
	if endpoint == "" {
		// No-op: leave the global no-op provider in place.
		return func(context.Context) error { return nil }, nil
	}

	exporter, err := otlpmetricgrpc.New(ctx,
		otlpmetricgrpc.WithEndpoint(endpoint),
		otlpmetricgrpc.WithInsecure(),
	)
	if err != nil {
		return nil, fmt.Errorf("create OTLP exporter: %w", err)
	}

	provider := metric.NewMeterProvider(
		metric.WithReader(metric.NewPeriodicReader(exporter,
			metric.WithInterval(exportInterval),
		)),
	)
	otel.SetMeterProvider(provider)

	return provider.Shutdown, nil
}
