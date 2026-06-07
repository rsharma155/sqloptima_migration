/**
 * Module: app/migrations/[jobId]/page.tsx
 * Purpose: Per-job detail page — real-time progress polling via TanStack Query,
 *          per-table status (table on desktop, cards on mobile), optimistic
 *          pause/resume/stop controls, and validation shortcut.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  RefreshCw,
  Pause,
  Play,
  StopCircle,
  Table2,
  ClipboardCheck,
  Loader2,
  XCircle,
  AlertTriangle,
  ScrollText,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { PhaseTimeline } from "./phase-timeline";
import { cn } from "@/lib/utils";
import {
  getMigration,
  getMigrationLogs,
  getMigrationProgress,
  pauseMigration,
  provisionMigrationTables,
  resumeMigration,
  stopMigration,
  type MigrationResponse,
  type ProgressResponse,
  type MigrationLogEntry,
} from "@/lib/api";
import { isLiveMigrationDetail, isTerminalMigration } from "@/lib/migration-status";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type ControlState = "idle" | "pausing" | "resuming" | "stopping";

function statusForDisplay(
  apiStatus: string,
  controlState: ControlState,
): string {
  if (controlState === "pausing") return "PAUSING…";
  if (controlState === "resuming") return "RESUMING…";
  if (controlState === "stopping") return "STOPPING…";
  return apiStatus.toUpperCase();
}

function StatusBadge({
  status,
  controlState = "idle",
}: {
  status: string;
  controlState?: ControlState;
}) {
  const display = statusForDisplay(status, controlState);
  if (display === "COMPLETED")
    return (
      <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
        {display}
      </Badge>
    );
  if (["FAILED", "STOPPED"].includes(display))
    return <Badge variant="destructive">{display}</Badge>;
  if (["RUNNING", "IN_PROGRESS", "QUEUED", "MIGRATING", "RESUMED"].includes(display))
    return (
      <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30">
        {display === "QUEUED" ? "QUEUED" : "RUNNING"}
      </Badge>
    );
  if (display === "PAUSED")
    return (
      <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30">
        PAUSED
      </Badge>
    );
  if (["PAUSING…", "RESUMING…", "STOPPING…"].includes(display))
    return (
      <Badge className="bg-muted text-muted-foreground gap-1">
        <Loader2 className="h-3 w-3 animate-spin" />
        {display}
      </Badge>
    );
  return <Badge variant="secondary">{display}</Badge>;
}

function formatRows(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatEta(seconds: number): string {
  if (seconds < 60) return `~${Math.round(seconds)}s remaining`;
  if (seconds < 3600) return `~${Math.round(seconds / 60)}m remaining`;
  return `~${(seconds / 3600).toFixed(1)}h remaining`;
}

type TableInfo = {
  rows_migrated?: number;
  status?: string;
  row_count?: number;
  percentage?: number;
  error?: string | null;
};

function tableProgressPct(info: TableInfo): number {
  if (typeof info.percentage === "number" && info.percentage > 0) {
    return Math.round(info.percentage);
  }
  const rows = info.rows_migrated ?? 0;
  const total = info.row_count ?? 0;
  if (total > 0) return Math.round((rows / total) * 100);
  if ((info.status ?? "").toLowerCase() === "completed" && rows > 0) return 100;
  return 0;
}

function tableProgressTotal(info: TableInfo): number {
  const rows = info.rows_migrated ?? 0;
  const total = info.row_count ?? 0;
  if (total > 0) return total;
  if ((info.status ?? "").toLowerCase() === "completed" && rows > 0) return rows;
  return 0;
}

function logLevelClass(level: string): string {
  switch (level) {
    case "error": return "text-red-400";
    case "warning": return "text-amber-400";
    case "success": return "text-emerald-400";
    default: return "text-muted-foreground";
  }
}

function MigrationLogsSection({
  logs,
  live = false,
}: {
  logs: MigrationLogEntry[];
  live?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length, logs[logs.length - 1]?.message]);

  if (logs.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <ScrollText className="h-4 w-4" /> Migration Log
          {live && (
            <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          ref={scrollRef}
          className="rounded-md border border-border bg-muted/20 max-h-72 overflow-y-auto font-mono text-xs divide-y divide-border"
        >
          {logs.map((entry, i) => (
            <div key={`${entry.timestamp}-${i}`} className="px-3 py-2 flex gap-3">
              <span className="text-muted-foreground/70 shrink-0 tabular-nums">
                {new Date(entry.timestamp).toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              <span className={cn("uppercase w-14 shrink-0", logLevelClass(entry.level))}>
                {entry.level}
              </span>
              <span className="text-foreground break-all">{entry.message}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function FailedTablesSection({
  tables,
}: {
  tables: NonNullable<MigrationResponse["tables"]>;
}) {
  const failed = tables.filter((t) => (t.status ?? "").toLowerCase() === "failed");
  if (failed.length === 0) return null;
  return (
    <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm space-y-2">
      <p className="font-semibold text-red-400">Failed tables</p>
      <ul className="space-y-1">
        {failed.map((t) => (
          <li key={t.table} className="font-mono text-xs text-red-300">
            {t.schema}.{t.table} → {t.target_schema}.{t.table}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Responsive table progress: table on ≥768px, stacked cards on mobile
// ---------------------------------------------------------------------------

function TableProgressSection({
  entries,
}: {
  entries: [string, TableInfo][];
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <Table2 className="h-4 w-4" /> Table Progress
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {/* Desktop table */}
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
                  Table
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
                  Status
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
                  Rows
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground w-40">
                  Progress
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([table, info]) => {
                const rows = info.rows_migrated ?? 0;
                const total = tableProgressTotal(info);
                const pct = tableProgressPct(info);
                const st = (info.status ?? "pending").toUpperCase();
                const isRunning = ["RUNNING", "IN_PROGRESS", "MIGRATING", "QUEUED"].includes(st);
                const showProgress = total > 0 || pct > 0;
                return (
                  <tr
                    key={table}
                    className="border-b border-border hover:bg-muted/20"
                  >
                    <td className="px-3 py-2 font-medium font-mono text-xs truncate max-w-[200px]">
                      {table}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={st} />
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground font-mono">
                      {formatRows(rows)}
                      {total > 0 && (
                        <span className="text-muted-foreground/60"> / {formatRows(total)}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {showProgress && (
                        <div className="flex items-center gap-2">
                          <Progress
                            value={pct}
                            aria-label={`${table} progress`}
                            className={cn(
                              "h-1.5 w-24 bg-muted",
                              isRunning
                                ? "[&>*]:bg-primary"
                                : st === "COMPLETED"
                                ? "[&>*]:bg-emerald-500"
                                : "[&>*]:bg-muted-foreground/40",
                            )}
                          />
                          <span className="text-xs text-muted-foreground tabular-nums">
                            {pct}%
                          </span>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="md:hidden divide-y divide-border">
          {entries.map(([table, info]) => {
            const rows = info.rows_migrated ?? 0;
            const total = tableProgressTotal(info);
            const pct = tableProgressPct(info);
            const st = (info.status ?? "pending").toUpperCase();
            const isRunning = ["RUNNING", "IN_PROGRESS", "MIGRATING", "QUEUED"].includes(st);
            const showProgress = total > 0 || pct > 0;
            return (
              <div key={table} className="px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium font-mono truncate max-w-[220px]">
                    {table}
                  </span>
                  <StatusBadge status={st} />
                </div>
                {showProgress && (
                  <>
                    <Progress
                      value={pct}
                      aria-label={`${table} progress`}
                      className={cn(
                        "h-1.5 mb-1.5 bg-muted",
                        isRunning
                          ? "[&>*]:bg-primary"
                          : st === "COMPLETED"
                          ? "[&>*]:bg-emerald-500"
                          : "[&>*]:bg-muted-foreground/40",
                      )}
                    />
                    <div className="flex justify-between text-xs text-muted-foreground font-mono">
                      <span>{formatRows(rows)} rows</span>
                      <span>
                        {pct}% of {formatRows(total)}
                      </span>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page skeleton
// ---------------------------------------------------------------------------

function PageSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-7 w-48" />
          <Skeleton className="h-4 w-64" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-8 w-20" />
        </div>
      </div>
      <Card>
        <CardContent className="pt-4 space-y-4">
          <div className="flex gap-3">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-8 w-20" />
          </div>
          <Skeleton className="h-2 w-full" />
          <div className="flex gap-4">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 w-28" />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <Skeleton className="h-5 w-36" />
        </CardHeader>
        <CardContent className="p-0">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-3 border-b">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-1.5 w-24" />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const LIVE_POLL_MS = 2_000;

export default function MigrationDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const qc = useQueryClient();
  const [controlState, setControlState] = useState<ControlState>("idle");
  const [provisioning, setProvisioning] = useState(false);

  const { data: job, isPending: jobPending, isFetching: jobFetching } = useQuery<MigrationResponse>({
    queryKey: ["migration", jobId],
    queryFn: () => getMigration(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = (query.state.data as MigrationResponse | undefined)?.status ?? "";
      return isLiveMigrationDetail(status) ? LIVE_POLL_MS : false;
    },
    refetchIntervalInBackground: true,
  });

  const { data: progress, isFetching: progressFetching } = useQuery<ProgressResponse>({
    queryKey: ["migration-progress", jobId],
    queryFn: () => getMigrationProgress(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const jobStatus = job?.status ?? "";
      const progressStatus = (query.state.data as ProgressResponse | undefined)?.status ?? "";
      const status = progressStatus || jobStatus;
      return isLiveMigrationDetail(status) ? LIVE_POLL_MS : false;
    },
    refetchIntervalInBackground: true,
  });

  const jobStatus = job?.status ?? "";
  const progressStatus = progress?.status ?? "";
  const effectiveStatus = isTerminalMigration(jobStatus)
    ? jobStatus
    : progressStatus || jobStatus;
  const live = isLiveMigrationDetail(effectiveStatus);
  const terminal = isTerminalMigration(effectiveStatus);

  const { data: logsData, isFetching: logsFetching } = useQuery({
    queryKey: ["migration-logs", jobId],
    queryFn: () => getMigrationLogs(jobId!),
    enabled: !!jobId,
    refetchInterval: live ? LIVE_POLL_MS : false,
    refetchIntervalInBackground: true,
  });

  const migrationLogs = logsData?.logs ?? [];

  const upper = effectiveStatus.toUpperCase();
  const displayStatus = upper;
  const isRunning =
    !terminal && ["RUNNING", "IN_PROGRESS", "QUEUED", "RESUMED"].includes(upper);
  const isPaused = !terminal && upper === "PAUSED";

  const control = async (action: "pause" | "resume" | "stop") => {
    if (!jobId) return;
    const nextState: ControlState =
      action === "pause" ? "pausing" : action === "resume" ? "resuming" : "stopping";
    setControlState(nextState);
    try {
      if (action === "pause") await pauseMigration(jobId);
      else if (action === "resume") await resumeMigration(jobId);
      else await stopMigration(jobId);
      toast.success(`Job ${action}d`);
      qc.invalidateQueries({ queryKey: ["migration", jobId] });
      qc.invalidateQueries({ queryKey: ["migration-progress", jobId] });
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : `${action} failed`);
    } finally {
      setControlState("idle");
    }
  };

  const tableProgressFromApi = (progress?.tables_progress ?? {}) as Record<string, TableInfo>;
  const tableProgressFromJob = Object.fromEntries(
    (job?.tables ?? []).map((t) => [
      t.table,
      {
        rows_migrated: t.rows_migrated,
        status: t.status,
        row_count: t.row_count_estimate,
        percentage: undefined,
      } satisfies TableInfo,
    ]),
  );
  // API progress wins over job snapshot for percentage / row_count.
  for (const [name, apiInfo] of Object.entries(tableProgressFromApi)) {
    const merged = tableProgressFromJob[name];
    if (merged) {
      tableProgressFromApi[name] = { ...merged, ...apiInfo };
    }
  }
  const mergedTableProgress = { ...tableProgressFromJob, ...tableProgressFromApi };
  const tableProgress = Object.entries(mergedTableProgress);

  if (jobPending) return <PageSkeleton />;

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Migration Detail"
        description={
          job
            ? `${job.table_count ?? job.tables?.length ?? 0} table${(job.table_count ?? job.tables?.length ?? 0) !== 1 ? "s" : ""} · started ${new Date(job.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}${job.updated_at ? ` · updated ${new Date(job.updated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}`
            : `Job ${jobId?.slice(0, 8)}…`
        }
      >
        <Button variant="outline" size="sm" asChild>
          <Link href="/migrations">
            <ArrowLeft className="h-4 w-4 mr-1" /> All Jobs
          </Link>
        </Button>
        {live && (
          <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            Live · updates every 2s
            {(jobFetching || progressFetching || logsFetching) && (
              <Loader2 className="h-3 w-3 animate-spin opacity-70" />
            )}
          </Badge>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            qc.invalidateQueries({ queryKey: ["migration", jobId] });
            qc.invalidateQueries({ queryKey: ["migration-progress", jobId] });
            qc.invalidateQueries({ queryKey: ["migration-logs", jobId] });
          }}
        >
          <RefreshCw className="h-4 w-4 mr-1" /> Refresh
        </Button>
      </PageHeader>

      {/* Phase timeline */}
      {job && progress && (
        <PhaseTimeline status={effectiveStatus} pct={progress.overall_percentage} />
      )}

      {/* Status + controls */}
      <Card>
        <CardContent className="pt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            {job && (
              <StatusBadge status={displayStatus} controlState={controlState} />
            )}
            {isRunning && controlState === "idle" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => control("pause")}
              >
                <Pause className="h-3.5 w-3.5 mr-1" /> Pause
              </Button>
            )}
            {isPaused && controlState === "idle" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => control("resume")}
              >
                <Play className="h-3.5 w-3.5 mr-1" /> Resume
              </Button>
            )}
            {(isRunning || isPaused) && controlState === "idle" && (
              <Button
                size="sm"
                variant="destructive"
                onClick={() => control("stop")}
              >
                <StopCircle className="h-3.5 w-3.5 mr-1" /> Stop
              </Button>
            )}
          </div>

          {/* Schema mapping */}
          {job?.source_schema && job?.target_schema && (
            <p className="text-xs text-muted-foreground font-mono">
              {job.source_schema} → {job.target_schema}
            </p>
          )}

          {/* Failure reason */}
          {upper === "FAILED" && (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm flex items-start gap-2">
              <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
              <div className="space-y-2 flex-1">
                <p className="font-semibold text-red-400 mb-0.5">Migration failed</p>
                {job?.error_message ? (
                  <p className="text-red-300 font-mono text-xs break-all whitespace-pre-wrap">{job.error_message}</p>
                ) : (
                  <p className="text-muted-foreground text-xs">
                    No error details were captured. Check the API server logs for more information.
                  </p>
                )}
                {job?.tables && <FailedTablesSection tables={job.tables} />}
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2"
                  disabled={provisioning}
                  onClick={async () => {
                    if (!jobId) return;
                    setProvisioning(true);
                    try {
                      const result = await provisionMigrationTables(jobId);
                      toast.success(result.message);
                      qc.invalidateQueries({ queryKey: ["migration", jobId] });
                    } catch (e: unknown) {
                      toast.error(e instanceof Error ? e.message : "Provision failed");
                    } finally {
                      setProvisioning(false);
                    }
                  }}
                >
                  {provisioning ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <Table2 className="h-3.5 w-3.5 mr-1" />
                  )}
                  Provision target tables
                </Button>
              </div>
            </div>
          )}

          {/* Completed summary */}
          {upper === "COMPLETED" && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm flex items-start gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-emerald-400">Migration completed successfully</p>
                {progress && (
                  <p className="text-emerald-300/90 text-xs mt-1 font-mono">
                    {formatRows(progress.total_rows_migrated)} rows migrated in{" "}
                    {Math.round(progress.elapsed_seconds)}s
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Stopped info */}
          {upper === "STOPPED" && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-amber-300 text-xs">Migration was stopped manually. You can start a new job from the Migrations page.</p>
            </div>
          )}

          {progress && (
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Overall progress</span>
                <span className="font-medium font-mono">
                  {formatRows(progress.total_rows_migrated)} /{" "}
                  {formatRows(progress.total_rows_estimate)} rows
                </span>
              </div>
              <Progress
                value={progress.overall_percentage}
                aria-label="Overall migration progress"
                className="h-2 bg-muted [&>*]:bg-primary"
              />
              <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                <span className="tabular-nums">
                  {progress.overall_percentage.toFixed(1)}% complete
                </span>
                {!terminal && progress.throughput_rows_per_sec > 0 && (
                  <span className="font-mono">
                    {formatRows(Math.round(progress.throughput_rows_per_sec))} rows/s
                  </span>
                )}
                {terminal && progress.throughput_rows_per_sec > 0 && (
                  <span className="font-mono">
                    avg {formatRows(Math.round(progress.throughput_rows_per_sec))} rows/s
                  </span>
                )}
                {progress.elapsed_seconds > 0 && (
                  <span>Elapsed: {Math.round(progress.elapsed_seconds)}s</span>
                )}
                {!terminal && progress.estimated_remaining_seconds > 0 && (
                  <span>{formatEta(progress.estimated_remaining_seconds)}</span>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Per-table breakdown */}
      {tableProgress.length > 0 && (
        <TableProgressSection entries={tableProgress} />
      )}

      {/* Migration event log */}
      {migrationLogs.length > 0 && (
        <MigrationLogsSection logs={migrationLogs} live={live} />
      )}

      {/* Validation shortcut */}
      {jobId && (
        <Card className="border-dashed">
          <CardContent className="pt-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium flex items-center gap-2">
                <ClipboardCheck className="h-4 w-4 text-primary" />
                Validate this migration
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                4 validation levels: L1 row counts · L2 column aggregates · L3 chunk hashes · L4 statistical sampling
              </p>
            </div>
            <Button size="sm" asChild>
              <Link href={`/validation/${jobId}`}>Open Validation →</Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
