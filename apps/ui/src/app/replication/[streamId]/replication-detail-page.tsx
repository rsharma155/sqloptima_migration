"use client";

/**
 * Module: replication-detail-page.tsx
 * Purpose: Live replication stream detail — capture/apply metrics, errors, checkpoints
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useCallback, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Database,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Server,
  Square,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { cn } from "@/lib/utils";
import {
  getReplicationStreamDetails,
  pauseReplicationStream,
  refreshReplicationStreamConcerns,
  resumeReplicationStream,
  startReplicationStream,
  stopReplicationStream,
  type ReplicationStreamDetails,
} from "@/lib/api";

const LIVE_STATUSES = new Set(["CDC_STREAMING", "STARTING", "CDC_CATCHUP", "PAUSED"]);

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function StatusBadge({ details }: { details: ReplicationStreamDetails }) {
  const { status, is_running, is_paused } = details;
  if (is_paused || status === "PAUSED") {
    return (
      <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30">
        PAUSED
      </Badge>
    );
  }
  if (is_running || LIVE_STATUSES.has(status)) {
    return (
      <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
        {status === "CDC_STREAMING" ? "STREAMING" : status}
      </Badge>
    );
  }
  if (status === "COMPLETED" || status === "IDLE") {
    return <Badge variant="outline">{status}</Badge>;
  }
  if (status === "FAILED") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  return <Badge variant="secondary">{status}</Badge>;
}

function MetricCard({
  title,
  value,
  hint,
  accent,
}: {
  title: string;
  value: string | number;
  hint: string;
  accent?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={cn("text-2xl font-bold font-mono", accent)}>{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{hint}</p>
      </CardContent>
    </Card>
  );
}

export default function ReplicationDetailPage() {
  const params = useParams();
  const streamId = String(params.streamId ?? "");
  const queryClient = useQueryClient();
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const { data: details, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["replication-stream", streamId],
    queryFn: () => getReplicationStreamDetails(streamId),
    enabled: Boolean(streamId),
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!d) return false;
      return d.is_active || LIVE_STATUSES.has(d.status) ? 3000 : false;
    },
  });

  const runAction = useCallback(
    async (action: "pause" | "resume" | "stop" | "start") => {
      setActionLoading(action);
      try {
        if (action === "pause") await pauseReplicationStream(streamId);
        else if (action === "resume") await resumeReplicationStream(streamId);
        else if (action === "start") await startReplicationStream(streamId);
        else await stopReplicationStream(streamId);
        toast.success(
          action === "stop"
            ? "Stream stopped"
            : action === "start"
            ? "Replication started"
            : `Stream ${action}d`,
        );
        await queryClient.invalidateQueries({ queryKey: ["replication-stream", streamId] });
        await queryClient.invalidateQueries({ queryKey: ["replication-summary"] });
      } catch (err) {
        toast.error(err instanceof Error ? err.message : `Failed to ${action} stream`);
      } finally {
        setActionLoading(null);
      }
    },
    [streamId, queryClient],
  );

  const handleRefreshConcerns = useCallback(async () => {
    setActionLoading("refresh");
    try {
      await refreshReplicationStreamConcerns(streamId);
      toast.success("Target table check refreshed");
      await queryClient.invalidateQueries({ queryKey: ["replication-stream", streamId] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to refresh concerns");
    } finally {
      setActionLoading(null);
    }
  }, [streamId, queryClient]);

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-48" />
      </div>
    );
  }

  if (isError || !details) {
    return (
      <div className="p-6">
        <Button variant="ghost" size="sm" asChild className="mb-4">
          <Link href="/replication">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Replication
          </Link>
        </Button>
        <Card className="border-destructive/40">
          <CardContent className="pt-6 text-destructive">
            Replication stream not found or could not be loaded.
          </CardContent>
        </Card>
      </div>
    );
  }

  const tableName = details.tables[0]?.name ?? details.name;
  const targetTable = details.target_tables[0];
  const isLive = details.runtime_active ?? (details.is_active || LIVE_STATUSES.has(details.status));
  const hasBlockers = details.concerns.some((c) => c.level === "blocker");
  const targetDisplaySchema = targetTable?.found_in_schema ?? details.target_schema;
  const targetDisplayTable = targetTable?.target_table_name ?? tableName.toLowerCase();

  return (
    <div className="p-6 space-y-6">
      <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-amber-950 dark:text-amber-100 text-xs leading-relaxed">
          <span className="font-medium">Preview feature.</span>{" "}
          Replication is still in progress and may not work as expected. Full functionality is
          planned for a future release.
        </p>
      </div>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-2">
          <Button variant="ghost" size="sm" asChild className="-ml-2 h-8">
            <Link href="/replication">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Replication
            </Link>
          </Button>
          <PageHeader
            title={details.name}
            description={`${details.source_schema}.${tableName} → ${details.target_schema}.${tableName.toLowerCase()}`}
          />
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge details={details} />
            {isLive && (
              <Badge variant="outline" className="text-[10px] gap-1">
                {isFetching ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                )}
                Live
              </Badge>
            )}
            <Badge variant="outline" className="text-[10px] uppercase">
              {details.mode}
            </Badge>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn("h-4 w-4 mr-1", isFetching && "animate-spin")} />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshConcerns}
            disabled={actionLoading !== null}
          >
            Re-check target
          </Button>
          {details.can_start && (
            <Button
              size="sm"
              onClick={() => runAction("start")}
              disabled={actionLoading !== null}
            >
              <Play className="h-4 w-4 mr-1" />
              Start replication
            </Button>
          )}
          {details.status === "CDC_STREAMING" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => runAction("pause")}
              disabled={actionLoading !== null}
            >
              <Pause className="h-4 w-4 mr-1" />
              Pause
            </Button>
          )}
          {details.status === "PAUSED" && (
            <Button
              size="sm"
              onClick={() => runAction("resume")}
              disabled={actionLoading !== null}
            >
              <Play className="h-4 w-4 mr-1" />
              Resume
            </Button>
          )}
          {["CDC_STREAMING", "PAUSED", "IDLE"].includes(details.status) && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => runAction("stop")}
              disabled={actionLoading !== null}
            >
              <Square className="h-4 w-4 mr-1" />
              Stop
            </Button>
          )}
        </div>
      </div>

      {!isLive && ["CDC_STREAMING", "PAUSED", "STARTING"].includes(details.status) && (
        <Card className="border-amber-500/40 bg-amber-500/10">
          <CardContent className="pt-6 text-sm flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Replication is not actively running</p>
              <p className="text-muted-foreground mt-1">
                The API process lost this stream (e.g. after restart). Metrics stay at zero until
                you click <span className="font-medium">Start replication</span>.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {details.status === "IDLE" && !isLive && (
        <Card className="border-blue-500/30 bg-blue-500/10">
          <CardContent className="pt-6 text-sm">
            <p className="font-medium">Stream is idle</p>
            <p className="text-muted-foreground mt-1">
              {hasBlockers
                ? "Resolve blockers below, then start replication. Metrics populate only while CDC capture is running."
                : "Click Start replication to begin capturing SQL Server changes. Make a test INSERT/UPDATE on the source table to verify counters increment."}
            </p>
          </CardContent>
        </Card>
      )}

      {targetTable?.ready && hasBlockers && (
        <Card className="border-emerald-500/30 bg-emerald-500/10">
          <CardContent className="pt-6 text-sm flex items-start gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
            <p>
              Target table verified: <span className="font-mono">{targetDisplaySchema}.{targetDisplayTable}</span>
              {" "}({formatNumber(targetTable.row_count)} rows). Click <span className="font-medium">Re-check target</span> to clear stale concerns.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Connection route */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Source → Target</CardTitle>
          <CardDescription>Servers participating in this replication stream</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col md:flex-row md:items-center gap-4 text-sm">
          <div className="flex-1 rounded-md border p-3 space-y-1">
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <Server className="h-3.5 w-3.5" />
              SQL Server source
            </div>
            <p className="font-medium">{details.source_connection?.name ?? "—"}</p>
            <p className="font-mono text-xs text-muted-foreground">
              {details.source_connection
                ? `${details.source_connection.host}:${details.source_connection.port}/${details.source_connection.database}`
                : details.source_connection_id}
            </p>
            <p className="text-xs">
              Table: <span className="font-mono">{details.source_schema}.{tableName}</span>
            </p>
          </div>
          <ArrowRight className="h-5 w-5 text-muted-foreground hidden md:block" />
          <div className="flex-1 rounded-md border p-3 space-y-1">
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <Database className="h-3.5 w-3.5" />
              PostgreSQL target
            </div>
            <p className="font-medium">{details.target_connection?.name ?? "—"}</p>
            <p className="font-mono text-xs text-muted-foreground">
              {details.target_connection
                ? `${details.target_connection.host}:${details.target_connection.port}/${details.target_connection.database}`
                : details.target_connection_id}
            </p>
            <p className="text-xs">
              Table:{" "}
              <span className="font-mono">
                {targetDisplaySchema}.{targetDisplayTable}
              </span>
              {targetTable?.exists && (
                <span className="text-muted-foreground ml-2">
                  ({formatNumber(targetTable.row_count)} rows)
                  {targetTable.schema_mismatch && " · schema mismatch"}
                </span>
              )}
              {targetTable && !targetTable.exists && (
                <span className="text-destructive ml-2">not found on target</span>
              )}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* KPI metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Commands Captured"
          value={formatNumber(details.events_captured)}
          hint="CDC change events read from SQL Server"
        />
        <MetricCard
          title="Commands Applied"
          value={formatNumber(details.events_applied)}
          hint="INSERT/UPDATE/DELETE executed on PostgreSQL"
          accent="text-emerald-500"
        />
        <MetricCard
          title="Pending Lag"
          value={formatNumber(details.pending_lag ?? 0)}
          hint="Captured minus applied (queue + in-flight)"
          accent={(details.pending_lag ?? 0) > 0 ? "text-amber-500" : undefined}
        />
        <MetricCard
          title="Queue Depth"
          value={formatNumber(details.queue_depth ?? 0)}
          hint="Events waiting in the in-memory bus"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="CDC Chunks"
          value={formatNumber(details.batches_with_changes)}
          hint={`${formatNumber(details.batches_polled)} polls · batch size ${details.batch_size}`}
        />
        <MetricCard
          title="Inserts"
          value={formatNumber(details.operations.insert)}
          hint="Applied INSERT operations"
        />
        <MetricCard
          title="Updates"
          value={formatNumber(details.operations.update)}
          hint="Applied UPDATE operations"
        />
        <MetricCard
          title="Deletes"
          value={formatNumber(details.operations.delete)}
          hint="Applied DELETE operations"
        />
      </div>

      {/* Runtime status */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Runtime Status</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
          <div>
            <p className="text-muted-foreground text-xs">Replication running</p>
            <p className="font-medium flex items-center gap-1.5 mt-0.5">
              {details.is_running ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  Yes — polling every {details.poll_interval_ms}ms
                </>
              ) : (
                <>
                  <XCircle className="h-4 w-4 text-muted-foreground" />
                  No
                </>
              )}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Duplicates skipped</p>
            <p className="font-medium font-mono mt-0.5">
              {formatNumber(details.duplicates_skipped)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Apply failures</p>
            <p className={cn("font-medium font-mono mt-0.5", details.apply_failures > 0 && "text-destructive")}>
              {formatNumber(details.apply_failures)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Started / Stopped</p>
            <p className="font-mono text-xs mt-0.5">
              {details.started_at ? new Date(details.started_at).toLocaleString() : "—"}
              {details.stopped_at && (
                <span className="block text-muted-foreground">
                  → {new Date(details.stopped_at).toLocaleString()}
                </span>
              )}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Per-table capture progress */}
      {details.table_progress.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Capture Progress</CardTitle>
            <CardDescription>Per-table CDC polling and chunk statistics</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              {details.table_progress.map((row) => (
                <div key={`${row.table_schema}.${row.table_name}`} className="px-6 py-3 grid gap-2 sm:grid-cols-4 text-sm">
                  <div>
                    <p className="font-mono font-medium">{row.table_schema}.{row.table_name}</p>
                    <p className="text-xs text-muted-foreground">
                      Last chunk: {row.last_batch_size} event(s)
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Events captured</p>
                    <p className="font-mono">{formatNumber(row.events_captured)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">CDC chunks</p>
                    <p className="font-mono">
                      {formatNumber(row.batches_with_changes)} / {formatNumber(row.batches_polled)} polls
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Last LSN / captured at</p>
                    <p className="font-mono text-xs truncate">
                      {row.last_position ?? "—"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {row.last_captured_at
                        ? new Date(row.last_captured_at).toLocaleString()
                        : "—"}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Checkpoints */}
      {details.checkpoints.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Target Checkpoints</CardTitle>
            <CardDescription>Last applied LSN persisted on PostgreSQL</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              {details.checkpoints.map((cp) => (
                <div key={`${cp.table_schema}.${cp.table_name}`} className="px-6 py-3 flex flex-wrap gap-4 text-sm">
                  <span className="font-mono">{cp.table_schema}.{cp.table_name}</span>
                  <span className="text-muted-foreground">LSN: {cp.last_checkpoint_lsn}</span>
                  <span className="text-muted-foreground">
                    Updated: {cp.updated_at ? new Date(cp.updated_at).toLocaleString() : "—"}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Concerns */}
      {details.concerns.length > 0 && (
        <Card className="border-amber-500/30">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Concerns
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {details.concerns.map((c, i) => (
              <div
                key={i}
                className="rounded-md border px-3 py-2 text-sm flex items-start gap-2"
              >
                <Badge
                  variant={c.level === "blocker" ? "destructive" : "outline"}
                  className="text-[10px] shrink-0"
                >
                  {c.level}
                </Badge>
                <span>{c.message}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Errors */}
      {details.all_errors.length > 0 && (
        <Card className="border-destructive/30">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2 text-destructive">
              <XCircle className="h-4 w-4" />
              Errors ({details.all_errors.length})
            </CardTitle>
            <CardDescription>Capture, apply, and runtime failures</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 max-h-64 overflow-y-auto">
            {details.all_errors.map((err, i) => (
              <p key={i} className="text-sm font-mono text-destructive/90 break-all">
                {err}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {isLive && details.events_captured === 0 && details.is_running && (
        <Card className="border-dashed">
          <CardContent className="pt-6 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">Capture is running — waiting for changes</p>
            <p className="mt-1">
              Counters stay at zero until SQL Server CDC records a change. Try an INSERT or UPDATE
              on <span className="font-mono">{details.source_schema}.{tableName}</span> and refresh.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
