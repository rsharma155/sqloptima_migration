"use client";

/**
 * Module: comparison-summary.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { CheckCircle2, AlertTriangle, Database, ArrowRightFromLine, ArrowLeftFromLine } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ComparisonResult } from "@/types/comparison";

interface ComparisonSummaryProps {
  result: ComparisonResult | null;
}

export function ComparisonSummary({ result }: ComparisonSummaryProps) {
  if (!result) {
    return (
      <div className="flex items-center justify-between px-6 py-4 border-b bg-card">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Database className="h-4 w-4" />
          <span className="text-sm">No comparison loaded</span>
        </div>
      </div>
    );
  }

  const total = result.totalSourceObjects + result.totalTargetObjects;
  const matchPercent = total > 0 ? Math.round((result.matched / total) * 100) : 0;

  return (
    <div className="flex items-center justify-between px-6 py-3 border-b bg-card">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-cyan-500" />
          <span className="text-sm font-medium">{result.sourceDatabase}</span>
          <span className="text-muted-foreground text-xs">→</span>
          <Database className="h-4 w-4 text-blue-500" />
          <span className="text-sm font-medium">{result.targetDatabase}</span>
        </div>

        <div className="h-4 w-px bg-border" />

        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">Total:</span>
          <span className="text-sm font-semibold">{result.totalSourceObjects + result.totalTargetObjects}</span>
        </div>

        <div className="h-4 w-px bg-border" />

        <div className="flex items-center gap-1">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
          <span className="text-sm font-semibold text-emerald-500">{matchPercent}%</span>
          <span className="text-xs text-muted-foreground">matched</span>
        </div>

        <div className="flex items-center gap-1">
          <ArrowRightFromLine className="h-3.5 w-3.5 text-blue-500" />
          <span className="text-sm font-medium text-blue-500">{result.sourceOnly}</span>
          <span className="text-xs text-muted-foreground">source-only</span>
        </div>

        <div className="flex items-center gap-1">
          <ArrowLeftFromLine className="h-3.5 w-3.5 text-purple-500" />
          <span className="text-sm font-medium text-purple-500">{result.targetOnly}</span>
          <span className="text-xs text-muted-foreground">target-only</span>
        </div>

        <div className="flex items-center gap-1">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
          <span className="text-sm font-medium text-amber-500">{result.partialMatch}</span>
          <span className="text-xs text-muted-foreground">partial</span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Completed in {(result.durationMs / 1000).toFixed(1)}s</span>
        <div
          className={cn(
            "h-2 w-24 rounded-full bg-secondary overflow-hidden"
          )}
        >
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${matchPercent}%`,
              background: matchPercent >= 90
                ? "hsl(var(--primary))"
                : matchPercent >= 70
                ? "hsl(var(--warning))"
                : "hsl(var(--destructive))",
            }}
          />
        </div>
      </div>
    </div>
  );
}
