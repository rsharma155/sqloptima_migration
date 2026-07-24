/**
 * Module: components/shared/platform-error.tsx
 * Purpose: Dedicated platform error display (§13.11) — title, cause, remediation, correlation ID
 * Domain: UX / Error experience
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { AlertTriangle, BookOpen, Copy, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PlatformErrorPayload } from "@/lib/platform-errors";
import { formatUserMessage } from "@/lib/platform-errors";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";

export interface PlatformErrorProps {
  error: PlatformErrorPayload | ApiError | Error | string | null | undefined;
  onRetry?: () => void;
  className?: string;
}

function toPayload(
  error: PlatformErrorProps["error"],
): PlatformErrorPayload | null {
  if (!error) return null;
  if (typeof error === "string") {
    return { title: "Error", detail: error };
  }
  if (error instanceof ApiError && error.payload) {
    return error.payload;
  }
  if (error instanceof Error) {
    return { title: error.name || "Error", detail: error.message };
  }
  return error;
}

export function PlatformError({ error, onRetry, className }: PlatformErrorProps) {
  const payload = toPayload(error);
  if (!payload) return null;

  const title = payload.title || "Something went wrong";
  const message = formatUserMessage(payload);

  const copyCorrelation = async () => {
    if (!payload.correlation_id) return;
    try {
      await navigator.clipboard.writeText(payload.correlation_id);
      toast.success("Correlation ID copied");
    } catch {
      toast.error("Could not copy correlation ID");
    }
  };

  return (
    <Card
      className={`border-destructive/40 bg-destructive/5 ${className ?? ""}`}
      role="alert"
      aria-live="assertive"
    >
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base text-destructive">
          <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden />
          {title}
          {payload.error_code ? (
            <span className="ml-auto text-xs font-mono font-normal text-muted-foreground">
              {payload.error_code}
            </span>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {payload.cause ? (
          <p className="text-muted-foreground">
            <span className="font-medium text-foreground">Cause: </span>
            {payload.cause}
          </p>
        ) : (
          <p className="text-muted-foreground">{message}</p>
        )}
        {payload.remediation ? (
          <p>
            <span className="font-medium">What to do: </span>
            {payload.remediation}
          </p>
        ) : null}
        {payload.doc_anchor ? (
          <p className="flex items-center gap-1.5 text-muted-foreground">
            <BookOpen className="h-3.5 w-3.5" aria-hidden />
            See docs: <code className="text-xs">{payload.doc_anchor}</code>
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2 pt-1">
          {onRetry ? (
            <Button type="button" size="sm" variant="outline" onClick={onRetry}>
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              Retry
            </Button>
          ) : null}
          {payload.correlation_id ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={copyCorrelation}
              title={payload.correlation_id}
            >
              <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              Copy correlation ID
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
