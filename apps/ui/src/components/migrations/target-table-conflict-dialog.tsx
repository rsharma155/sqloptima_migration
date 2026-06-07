"use client";

import Link from "next/link";
import { AlertTriangle, PauseCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import type {
  MigrationPreflightResponse,
  TargetTablePolicy,
} from "@/lib/api";

const POLICY_LABELS: Record<TargetTablePolicy, string> = {
  use_existing: "Skip data load — table already migrated",
  drop_empty_recreate: "Drop empty table and recreate schema",
  truncate_reload: "Truncate and reload all data",
};

interface TargetTableConflictDialogProps {
  open: boolean;
  preflight: MigrationPreflightResponse | null;
  policies: Record<string, TargetTablePolicy>;
  onPolicyChange: (tableName: string, policy: TargetTablePolicy) => void;
  onCancel: () => void;
  onConfirm: () => void;
  confirming?: boolean;
}

export function TargetTableConflictDialog({
  open,
  preflight,
  policies,
  onPolicyChange,
  onCancel,
  onConfirm,
  confirming = false,
}: TargetTableConflictDialogProps) {
  if (!preflight) return null;

  const conflictTables = preflight.tables.filter((t) => t.requires_action);
  const hasPaused = preflight.paused_jobs.length > 0;
  const hasSchemaMismatch = conflictTables.some(
    (t) => (t as { schema_mismatch?: boolean }).schema_mismatch,
  );

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onCancel()}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            Target tables already exist
          </DialogTitle>
          <DialogDescription>
            Review existing PostgreSQL tables before starting migration. Paused jobs
            can resume from their last checkpoint without re-running completed chunks.
          </DialogDescription>
        </DialogHeader>

        {hasPaused && (
          <div className="rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-3 space-y-2 text-sm">
            <p className="font-medium text-blue-300 flex items-center gap-2">
              <PauseCircle className="h-4 w-4" />
              Paused migration(s) found
            </p>
            {preflight.paused_jobs.map((job) => (
              <div key={job.job_id} className="text-xs text-blue-200/90 space-y-1">
                <p>
                  Job{" "}
                  <span className="font-mono">{job.job_id.slice(0, 8)}…</span>
                  {" — "}
                  {job.rows_migrated.toLocaleString()} row(s) already migrated
                </p>
                <Button size="sm" variant="outline" className="h-7 text-xs" asChild>
                  <Link href={`/migrations/${job.job_id}`}>
                    Open and resume →
                  </Link>
                </Button>
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground">
              Resuming a paused job continues from pending chunks — no need to truncate
              unless you intentionally want a full reload.
            </p>
          </div>
        )}

        {conflictTables.length > 0 && (
          <div className="space-y-3">
            {conflictTables.map((table) => {
              const policy =
                policies[table.table_name] ??
                (table.suggested_policy as TargetTablePolicy | undefined) ??
                "use_existing";
              const isEmpty = table.row_count === 0;
              const schemaMismatch = Boolean(
                (table as { schema_mismatch?: boolean }).schema_mismatch,
              );
              return (
                <div
                  key={table.table_name}
                  className="rounded-md border border-border px-3 py-3 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm">{table.table_name}</span>
                    <Badge variant="outline" className="text-[10px]">
                      {table.row_count.toLocaleString()} rows
                    </Badge>
                  </div>
                  {schemaMismatch && (table as { found_in_schema?: string }).found_in_schema && (
                    <p className="text-xs text-amber-600 dark:text-amber-400">
                      Found in schema{" "}
                      <span className="font-mono">
                        {(table as { found_in_schema?: string }).found_in_schema}
                      </span>
                      {" — "}
                      update Target Schema in the setup step before migrating.
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">{table.message}</p>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Action</Label>
                    <select
                      value={policy}
                      onChange={(e) =>
                        onPolicyChange(
                          table.table_name,
                          e.target.value as TargetTablePolicy,
                        )
                      }
                      disabled={schemaMismatch}
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    >
                      {!isEmpty && (
                        <option value="use_existing">
                          {POLICY_LABELS.use_existing}
                        </option>
                      )}
                      {!isEmpty && (
                        <option value="truncate_reload">
                          {POLICY_LABELS.truncate_reload}
                        </option>
                      )}
                      {isEmpty && (
                        <option value="drop_empty_recreate">
                          {POLICY_LABELS.drop_empty_recreate}
                        </option>
                      )}
                      {isEmpty && (
                        <option value="use_existing">
                          {POLICY_LABELS.use_existing}
                        </option>
                      )}
                    </select>
                    {policy === "truncate_reload" && !isEmpty && (
                      <p className="text-[11px] text-amber-600 dark:text-amber-400">
                        This removes all {table.row_count.toLocaleString()} existing row(s)
                        on the target before reloading.
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={onCancel} disabled={confirming}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={confirming || hasSchemaMismatch}>
            {confirming ? "Starting…" : "Confirm and start migration"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
