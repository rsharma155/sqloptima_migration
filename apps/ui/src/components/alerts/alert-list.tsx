"use client";

import Link from "next/link";
import { AlertTriangle, Info, X, XCircle } from "lucide-react";
import type { PlatformAlert } from "@/lib/api";
import { cn } from "@/lib/utils";

export function severityIcon(severity: string) {
  if (severity === "critical") return XCircle;
  if (severity === "warning") return AlertTriangle;
  return Info;
}

export function severityIconClass(severity: string): string {
  switch (severity) {
    case "critical":
      return "text-destructive";
    case "warning":
      return "text-amber-600 dark:text-amber-400";
    default:
      return "text-primary";
  }
}

export function alertRowClass(severity: string): string {
  switch (severity) {
    case "critical":
      return "border-destructive/25 bg-destructive/5 hover:bg-destructive/10";
    case "warning":
      return "border-amber-500/25 bg-amber-500/5 hover:bg-amber-500/10 dark:bg-amber-500/10";
    default:
      return "border-border bg-muted/40 hover:bg-muted/60";
  }
}

export function AlertListItem({
  alert,
  onDismiss,
  compact = false,
}: {
  alert: PlatformAlert;
  onDismiss?: (id: string) => void;
  compact?: boolean;
}) {
  const Icon = severityIcon(alert.severity);

  const body = (
    <div
      className={cn(
        "flex items-start gap-3 rounded-md border px-3 transition-colors",
        compact ? "py-2.5" : "py-3",
        alertRowClass(alert.severity),
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0 mt-0.5", severityIconClass(alert.severity))} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{alert.title}</p>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed break-words">
          {alert.message}
        </p>
        {!compact && alert.created_at && (
          <p className="text-[10px] text-muted-foreground/80 mt-1.5 font-mono">
            {new Date(alert.created_at).toLocaleString()}
          </p>
        )}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDismiss(alert.id);
          }}
          className="shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-background/60"
          aria-label="Dismiss alert"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );

  if (alert.href) {
    return (
      <Link href={alert.href} className="block">
        {body}
      </Link>
    );
  }
  return body;
}
