/**
 * Module: components/shared/error-boundary.tsx
 * Purpose: Root error boundary to catch render-time exceptions and display recovery UI.
 *          React requires class components for error boundaries.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { Component, type ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

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
          <Card className="w-full max-w-md border-destructive/30 bg-destructive/5">
            <CardContent className="pt-6 text-center space-y-4">
              <AlertCircle className="h-12 w-12 mx-auto text-destructive" />
              <div className="space-y-2">
                <h2 className="text-lg font-semibold text-foreground">
                  Something went wrong
                </h2>
                <p className="text-sm text-muted-foreground break-words">
                  {this.state.message || "An unexpected error occurred. Please try reloading the page."}
                </p>
              </div>
              <Button
                onClick={this.handleReload}
                className="w-full"
                variant="default"
              >
                Reload page
              </Button>
            </CardContent>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}
