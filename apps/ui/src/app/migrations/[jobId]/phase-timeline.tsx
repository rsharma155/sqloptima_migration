/**
 * Module: app/migrations/[jobId]/phase-timeline.tsx
 * Purpose: Phase timeline component showing migration pipeline progress
 *          (Discovery → Schema → Data → Validation → Finalize).
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { Fragment } from "react";
import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type Phase = "discovery" | "schema" | "data" | "validation" | "finalize";

interface PhaseInfo {
  key: Phase;
  label: string;
}

const PHASES: PhaseInfo[] = [
  { key: "discovery", label: "Discovery" },
  { key: "schema", label: "Schema" },
  { key: "data", label: "Data" },
  { key: "validation", label: "Validation" },
  { key: "finalize", label: "Finalize" },
];

export function derivePhase(status: string, pct: number): Phase {
  const s = status.toUpperCase();

  if (["PENDING", "QUEUED", "STARTING"].includes(s)) {
    return "discovery";
  }

  if (["RUNNING", "IN_PROGRESS"].includes(s)) {
    if (pct < 20) return "schema";
    if (pct < 95) return "data";
    return "validation";
  }

  if (s === "COMPLETED") {
    return "finalize";
  }

  return "discovery";
}

interface PhaseTimelineProps {
  status: string;
  pct: number;
  /** When set, the Finalize step links to the post-migration dashboard. */
  jobId?: string;
}

export function PhaseTimeline({ status, pct, jobId }: PhaseTimelineProps) {
  const active = derivePhase(status, pct);
  const activeIdx = PHASES.findIndex((p) => p.key === active);
  const isCompleted = status.toUpperCase() === "COMPLETED";

  return (
    <div className="flex items-center gap-0">
      {PHASES.map((phase, i) => {
        const done = isCompleted ? i <= activeIdx : i < activeIdx;
        const current = i === activeIdx && !isCompleted;
        const isFinalizeStep = phase.key === "finalize";
        const finalizeHref = jobId && isFinalizeStep
          ? `/migrations/${jobId}/post-migration`
          : undefined;

        return (
          <Fragment key={phase.key}>
            <div className="flex flex-col items-center gap-1">
              <div
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full border-2 text-xs font-semibold transition-colors",
                  done && "border-primary bg-primary text-primary-foreground",
                  current && "border-primary bg-primary/10 text-primary stage-active-pulse",
                  !done &&
                    !current &&
                    "border-muted-foreground/30 text-muted-foreground",
                )}
              >
                {done ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <span>{i + 1}</span>
                )}
              </div>
              {finalizeHref && (done || current || isCompleted) ? (
                <Link
                  href={finalizeHref}
                  className={cn(
                    "text-[10px] whitespace-nowrap underline-offset-2 hover:underline",
                    (done || current || (isCompleted && isFinalizeStep))
                      ? "text-primary font-medium"
                      : "text-muted-foreground",
                  )}
                >
                  {phase.label}
                </Link>
              ) : (
                <span
                  className={cn(
                    "text-[10px] whitespace-nowrap",
                    (done || current)
                      ? "text-foreground font-medium"
                      : "text-muted-foreground",
                  )}
                >
                  {phase.label}
                </span>
              )}
            </div>
            {i < PHASES.length - 1 && (
              <div
                className={cn(
                  "h-0.5 flex-1 mb-4 transition-colors",
                  i < activeIdx || isCompleted ? "bg-primary" : "bg-muted-foreground/20",
                )}
              />
            )}
          </Fragment>
        );
      })}
    </div>
  );
}
