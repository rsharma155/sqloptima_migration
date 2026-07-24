/**
 * Module: components/shared/__tests__/platform-error.test.tsx
 * Purpose: Unit tests for PlatformError display (§13.11)
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { render, screen } from "@testing-library/react";
import { PlatformError } from "../platform-error";
import { ApiError } from "@/lib/api";

describe("PlatformError", () => {
  it("renders title, cause, remediation, and correlation id", () => {
    render(
      <PlatformError
        error={{
          title: "Target conflict",
          cause: "Tables already exist",
          remediation: "Choose truncate and reload",
          correlation_id: "corr-123",
          error_code: "MIG_TARGET_CONFLICT",
        }}
      />,
    );

    expect(screen.getByText("Target conflict")).toBeInTheDocument();
    expect(screen.getByText(/Tables already exist/)).toBeInTheDocument();
    expect(screen.getByText(/Choose truncate and reload/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy correlation id/i })).toBeInTheDocument();
  });

  it("unwraps ApiError payload", () => {
    const err = new ApiError(409, "conflict", {
      title: "From API",
      remediation: "Retry later",
    });
    render(<PlatformError error={err} />);
    expect(screen.getByText("From API")).toBeInTheDocument();
    expect(screen.getAllByText(/Retry later/).length).toBeGreaterThan(0);
  });

  it("shows retry when provided", () => {
    const onRetry = vi.fn();
    render(<PlatformError error="Boom" onRetry={onRetry} />);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
