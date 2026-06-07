/**
 * Module: components/shared/tier-badge.tsx
 * Purpose: Visual badge for SAFE / WARNING / BLOCKER migration tiers.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { cn } from "@/lib/utils";

type Tier = "SAFE" | "WARNING" | "BLOCKER";

interface TierBadgeProps {
  tier: Tier;
  className?: string;
}

const CONFIG: Record<Tier, { label: string; classes: string }> = {
  SAFE:    { label: "SAFE",    classes: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
  WARNING: { label: "WARNING", classes: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  BLOCKER: { label: "BLOCKER", classes: "bg-red-500/15 text-red-400 border-red-500/30" },
};

export function TierBadge({ tier, className }: TierBadgeProps) {
  const cfg = CONFIG[tier] ?? CONFIG.BLOCKER;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold tracking-wide",
        cfg.classes,
        className,
      )}
    >
      {cfg.label}
    </span>
  );
}
