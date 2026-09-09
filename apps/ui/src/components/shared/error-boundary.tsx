/**
 * Module: components/shared/error-boundary.tsx
 * Purpose: Root error boundary — render-time exceptions via PlatformError (§13.11)
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { Component, type ReactNode } from "react";
import { PlatformError } from "@/components/shared/platform-error";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error) {
    console.error("ErrorBoundary caught:", error);
  }

  handleReload = () => {
    this.setState({ hasError: false, message: "" });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center p-6 min-h-[400px]">
          <div className="w-full max-w-lg">
            <PlatformError
              error={{
                title: "Something went wrong",
                detail: this.state.message || "An unexpected error occurred.",
                remediation: "Reload the page. If the problem persists, contact support.",
                error_code: "INTERNAL_ERROR",
              }}
              onRetry={this.handleReload}
            />
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
