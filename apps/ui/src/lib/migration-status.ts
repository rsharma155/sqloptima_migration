/**
 * Migration job status helpers for UI display (§11.6).
 */
export type MigrationStatus =
  | "pending"
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "partial"
  | "failed"
  | "stopped"
  | "cancelled";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  queued: "Queued",
  running: "Running",
  paused: "Paused",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  stopped: "Stopped",
  cancelled: "Cancelled",
};

const STATUS_VARIANT: Record<string, "default" | "success" | "warning" | "destructive"> = {
  pending: "default",
  running: "warning",
  paused: "warning",
  completed: "success",
  partial: "warning",
  failed: "destructive",
  stopped: "default",
  cancelled: "default",
};

export function formatMigrationStatus(status: string): string {
  return STATUS_LABELS[status.toLowerCase()] ?? status;
}

export function migrationStatusVariant(
  status: string,
): "default" | "success" | "warning" | "destructive" {
  return STATUS_VARIANT[status.toLowerCase()] ?? "default";
}

export function isActiveMigration(status: string): boolean {
  const s = status.toLowerCase();
  return s === "running" || s === "paused" || s === "pending" || s === "queued";
}

/** True while the detail page should poll for live updates (2s interval). */
export function isLiveMigrationDetail(status: string): boolean {
  const s = status.toLowerCase();
  return (
    s === "pending" ||
    s === "queued" ||
    s === "running" ||
    s === "paused" ||
    s === "resumed" ||
    s === "in_progress" ||
    s === "migrating"
  );
}

export function isTerminalMigration(status: string): boolean {
  const s = status.toLowerCase();
  return s === "completed" || s === "partial" || s === "failed" || s === "stopped" || s === "cancelled";
}
