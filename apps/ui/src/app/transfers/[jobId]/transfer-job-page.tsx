/**
 * Module: app/transfers/[jobId]/transfer-job-page.tsx
 * Purpose: Live Transfer metrics dashboard — per-table progress, errors, and logs
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Loader2,
  Pause,
  Play,
  Square,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformError } from "@/components/shared/platform-error";
import {
  ApiError,
  getTransfer,
  getTransferLogs,
  getTransferMetrics,
  patchTransferThreshold,
  pauseTransfer,
  resumeTransfer,
  stopTransfer,
} from "@/lib/api";

const ACTIVE = new Set(["queued", "running", "preparing", "paused", "restoring"]);

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "failed") return "destructive";
  if (status === "completed") return "default";
  if (status === "running" || status === "copying" || status === "loading") return "secondary";
  return "outline";
}

export default function TransferJobPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId;
  const qc = useQueryClient();
  const [chunkSize, setChunkSize] = useState<number | "">("");
  const [selectedTable, setSelectedTable] = useState<string | null>(null);

  const jobQuery = useQuery({
    queryKey: ["transfer", jobId],
    queryFn: () => getTransfer(jobId),
    refetchInterval: 3000,
  });
  const metricsQuery = useQuery({
    queryKey: ["transfer-metrics", jobId],
    queryFn: () => getTransferMetrics(jobId),
    refetchInterval: 2000,
  });
  const logsQuery = useQuery({
    queryKey: ["transfer-logs", jobId, selectedTable],
    queryFn: () => getTransferLogs(jobId, 0, selectedTable),
    refetchInterval: 3000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["transfer", jobId] });
    qc.invalidateQueries({ queryKey: ["transfer-metrics", jobId] });
    qc.invalidateQueries({ queryKey: ["transfer-logs", jobId] });
    qc.invalidateQueries({ queryKey: ["transfers"] });
  };

  const onError = (err: Error) => toast.error(err instanceof ApiError ? err.message : err.message);

  const pauseMut = useMutation({ mutationFn: () => pauseTransfer(jobId), onSuccess: invalidate, onError });
  const resumeMut = useMutation({ mutationFn: () => resumeTransfer(jobId), onSuccess: invalidate, onError });
  const stopMut = useMutation({ mutationFn: () => stopTransfer(jobId, true), onSuccess: invalidate, onError });
  const threshMut = useMutation({
    mutationFn: () => patchTransferThreshold(jobId, { chunk_size: Number(chunkSize) }),
    onSuccess: () => {
      toast.success("Threshold updated for the next chunk");
      invalidate();
    },
    onError,
  });

  const job = jobQuery.data;
  const metrics = metricsQuery.data;
  const tables = metrics?.tables ?? [];
  const selected = useMemo(
    () => tables.find((t) => t.table_key === selectedTable) ?? null,
    [tables, selectedTable],
  );
  const live = Boolean(job && ACTIVE.has(job.status));

  if (jobQuery.isError) {
    return (
      <div className="p-6">
        <PlatformError error={jobQuery.error} />
        <Link href="/transfers" className="text-sm underline">Back to transfers</Link>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading transfer…
      </div>
    );
  }

  const busy = pauseMut.isPending || resumeMut.isPending || stopMut.isPending;
  const overall = metrics?.overall_percentage ?? job.overall_percentage;
  const rowsCopied = metrics?.total_rows_copied ?? job.rows_copied;
  const rowsTotal = metrics?.total_rows_estimate ?? job.rows_total;

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title={`Transfer ${job.path}`}
        description={`${job.status} · ${job.phase} · ${overall}%`}
      >
        <Button variant="outline" size="sm" asChild>
          <Link href="/transfers"><ArrowLeft className="h-4 w-4 mr-1" /> All transfers</Link>
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-2">
        <Badge>{job.status}</Badge>
        <Badge variant="secondary">{job.phase}</Badge>
        {live && (
          <Badge variant="outline" className="gap-1">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            Live
          </Badge>
        )}
        {ACTIVE.has(job.status) && job.status !== "paused" && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => pauseMut.mutate()}>
            <Pause className="h-4 w-4 mr-1" /> Pause
          </Button>
        )}
        {job.status === "paused" && (
          <Button size="sm" disabled={busy} onClick={() => resumeMut.mutate()}>
            <Play className="h-4 w-4 mr-1" /> Resume
          </Button>
        )}
        {ACTIVE.has(job.status) && (
          <Button size="sm" variant="destructive" disabled={busy} onClick={() => stopMut.mutate()}>
            <Square className="h-4 w-4 mr-1" /> Stop
          </Button>
        )}
      </div>

      {job.error && <p className="text-sm text-destructive">{job.error}</p>}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Overall</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">{overall}%</p>
            <Progress value={overall} className="h-2 mt-2" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Rows copied</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">{rowsCopied.toLocaleString()}</p>
            <p className="text-xs text-muted-foreground mt-1">
              of {rowsTotal.toLocaleString()} estimated
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Tables</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">
              {metrics?.tables_completed ?? job.tables_done}/{metrics?.tables_total ?? job.tables_total}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {metrics?.tables_running ?? 0} running
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Table errors</CardTitle></CardHeader>
          <CardContent>
            <p className={`text-2xl font-semibold tabular-nums ${(metrics?.tables_failed ?? 0) > 0 ? "text-destructive" : ""}`}>
              {metrics?.tables_failed ?? 0}
            </p>
            <p className="text-xs text-muted-foreground mt-1">Select a row to inspect logs</p>
          </CardContent>
        </Card>
      </div>

      {Array.isArray((job.constraint_plan as { items?: Array<{ action?: string; object_id?: string; kind?: string }> } | null)?.items) && (
        <Card>
          <CardHeader><CardTitle className="text-base">Destination constraints</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            {((job.constraint_plan as { items: Array<{ action?: string; object_id?: string; kind?: string; schema?: string; table?: string }> }).items)
              .filter((item) => item.action === "disable")
              .map((item) => (
                <div key={`${item.schema}.${item.table}.${item.object_id}`} className="font-mono">
                  {item.schema}.{item.table} · {item.kind} · {item.object_id} — disable then restore
                </div>
              ))}
            {((job.constraint_plan as { items: Array<{ action?: string }> }).items).filter((item) => item.action === "disable").length === 0 && (
              <p className="text-muted-foreground">Operator kept all destination constraints enabled.</p>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Table migration dashboard</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Rows</TableHead>
                <TableHead className="w-[180px]">Progress</TableHead>
                <TableHead>Last error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tables.map((t) => (
                <TableRow
                  key={t.table_key}
                  data-state={selectedTable === t.table_key ? "selected" : undefined}
                  className="cursor-pointer"
                  onClick={() => setSelectedTable(selectedTable === t.table_key ? null : t.table_key)}
                >
                  <TableCell className="font-mono text-xs">
                    {t.source_schema}.{t.source_table}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {t.target_schema}.{t.target_table}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
                    {(t.error_count ?? 0) > 0 && (
                      <span className="ml-2 text-xs text-destructive">{t.error_count} error(s)</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-xs">
                    {t.rows_copied.toLocaleString()} / {t.row_count_estimate.toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Progress value={t.percent} className="h-2" />
                      <span className="w-10 text-right text-xs tabular-nums">{t.percent}%</span>
                    </div>
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-xs text-destructive" title={t.error || ""}>
                    {t.error || "—"}
                  </TableCell>
                </TableRow>
              ))}
              {tables.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">
                    No tables configured on this job.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {selected ? `Logs for ${selected.table_key}` : "Job logs"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {selected?.error && (
            <div className="flex items-start gap-2 rounded border border-destructive/40 bg-destructive/5 p-3 text-sm">
              <AlertTriangle className="h-4 w-4 mt-0.5 text-destructive" />
              <div>
                <p className="font-medium text-destructive">Table error</p>
                <p className="font-mono text-xs mt-1 whitespace-pre-wrap">{selected.error}</p>
                {selected.error_at && (
                  <p className="text-xs text-muted-foreground mt-1">{selected.error_at}</p>
                )}
              </div>
            </div>
          )}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {selected
                ? "Showing logs for the selected table. Click the row again to see the full job log."
                : "Click a table row to filter errors and logs to that table."}
            </span>
            {selected && (
              <Button variant="ghost" size="sm" onClick={() => setSelectedTable(null)}>
                Clear filter
              </Button>
            )}
          </div>
          <div className="max-h-80 overflow-auto font-mono text-xs space-y-1">
            {(logsQuery.data || []).map((line) => (
              <div key={line.id} className={line.level === "error" ? "text-destructive" : ""}>
                <span className="text-muted-foreground">{line.logged_at} [{line.level}]</span>
                {line.table_name ? ` ${line.table_name}` : ""} {line.message}
              </div>
            ))}
            {(logsQuery.data || []).length === 0 && (
              <p className="text-muted-foreground">
                {selected
                  ? "No log lines for this table yet."
                  : "No log lines yet. The Go transfer worker has not claimed this job."}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Row threshold</CardTitle></CardHeader>
        <CardContent className="flex items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor="chunk">Chunk size (applies to the next chunk)</Label>
            <Input
              id="chunk"
              type="number"
              min={100}
              value={chunkSize === "" ? job.threshold.chunk_size : chunkSize}
              onChange={(e) => setChunkSize(Number(e.target.value))}
            />
          </div>
          <Button
            disabled={threshMut.isPending || job.status === "completed"}
            onClick={() => threshMut.mutate()}
          >
            {threshMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            Apply
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
