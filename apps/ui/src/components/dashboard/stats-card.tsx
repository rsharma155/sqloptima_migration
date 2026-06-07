/**
 * Module: stats-card.tsx
 * Purpose: KPI stat card with optional inline sparkline (Recharts AreaChart).
 *          When sparklineData is provided the card grows slightly to accommodate
 *          a 32px high chart below the value — no extra layout shift.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
"use client";

import { type LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

interface StatsCardProps {
  title: string;
  value: string | number;
  description?: string;
  icon: LucideIcon;
  iconColor?: string;
  sparklineData?: number[];
  sparklineColor?: string;
  trend?: "up" | "down" | "neutral";
  trendValue?: string;
  className?: string;
  href?: string;
}

export function StatsCard({
  title,
  value,
  description,
  icon: Icon,
  iconColor,
  sparklineData,
  sparklineColor = "hsl(var(--primary))",
  trend,
  trendValue,
  className,
  href,
}: StatsCardProps) {
  const showSparkline = sparklineData && sparklineData.length > 1;
  const chartData = sparklineData?.map((v, i) => ({ i, v }));

  return (
    <Card
      className={cn(
        href ? "cursor-pointer transition-colors hover:border-primary/40 hover:bg-muted/40" : "",
        className,
      )}
      {...(href ? { onClick: () => { window.location.href = href; } } : {})}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className={cn("h-4 w-4", iconColor ?? "text-muted-foreground")} />
      </CardHeader>
      <CardContent>
        <div key={String(value)} className="text-2xl font-bold stat-value-enter">
          {value}
        </div>
        {description && (
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        )}
        {trend && trendValue && (
          <div className="flex items-center gap-1 mt-2">
            <span
              className={cn(
                "text-xs font-medium",
                trend === "up" && "text-emerald-500",
                trend === "down" && "text-red-500",
                trend === "neutral" && "text-muted-foreground",
              )}
            >
              {trendValue}
            </span>
          </div>
        )}

        {/* Inline sparkline — renders below the value, no tooltip labels */}
        {showSparkline && (
          <div className="mt-2 h-8 -mx-1">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
                <defs>
                  <linearGradient id={`sg-${title}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={sparklineColor} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={sparklineColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Tooltip
                  content={() => null}
                  cursor={false}
                />
                <Area
                  type="monotone"
                  dataKey="v"
                  stroke={sparklineColor}
                  strokeWidth={1.5}
                  fill={`url(#sg-${title})`}
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
