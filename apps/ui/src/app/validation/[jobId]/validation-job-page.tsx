"use client";

/**
 * Module: app/validation/[jobId]/page.tsx
 * Purpose: Per-job validation page — shows L1–L3 validation run results with
 *          prominent pass/fail hero icons, a Download dropdown per run card,
 *          and skeleton loaders on initial load.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Download,
  ClipboardCheck,
  ArrowLeft,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getValidationRuns,
  getValidationRunReport,
  getValidationRunReportJson,
  getMigration,
  runValidationLevels,
  compareRowSamples,
  type ValidationRunSummary,
  type ValidationReportJson,
  type MigrationResponse,
  type RowSampleResponse,
} from "@/lib/api";
import Link from "next/link";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SUPPORTED_LEVELS = [1, 2, 3] as const;

function isSupportedValidationLevel(level: number): level is (typeof SUPPORTED_LEVELS)[number] {
  return (SUPPORTED_LEVELS as readonly number[]).includes(level);
}

const LEVEL_LABELS: Record<number, string> = {
  1: "L1 — Row Count",
  2: "L2 — Aggregates",
  3: "L3 — Chunk Hashes",
};

const LEVEL_DESC: Record<number, string> = {
  1: "Compares total row count source vs target",
  2: "Compares MIN/MAX/SUM/AVG per numeric column",
  3: "Per-chunk count and aggregate pushdown",
};

function normalizeAggMap(raw?: Record<string, unknown>): Record<string, unknown> {
  if (!raw) return {};
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    out[key.toLowerCase()] = value;
  }
  return out;
}

function formatAggCell(
  source?: Record<string, unknown>,
  target?: Record<string, unknown>,
  key?: string,
): string {
  if (!key) return "—";
  const src = normalizeAggMap(source);
  const tgt = normalizeAggMap(target);
  const s = src[key];
  const t = tgt[key];
  if (s == null && t == null) return "—";
  return `${s ?? "—"} → ${t ?? "—"}`;
}

// ---------------------------------------------------------------------------
// Run card
// ---------------------------------------------------------------------------

function RunCard({
  run,
  report,
  reportLoading,
  onDownload,
  downloading,
}: {
  run: ValidationRunSummary;
  report?: ValidationReportJson;
  reportLoading?: boolean;
  onDownload: (runId: string, fmt: "json" | "csv" | "html") => void;
  downloading: string | null;
}) {
  const total = run.pass_count + run.fail_count;
  const isPassed = run.status === "COMPLETED" && run.fail_count === 0;
  const isFailed = run.fail_count > 0 || run.status === "FAILED";
  const isRunning = run.status === "RUNNING" || run.status === "PENDING";
  const isDownloading = downloading?.startsWith(run.run_id);

  return (
    <Card
      className={
        isFailed
          ? "border-red-500/30"
          : isPassed
          ? "border-emerald-500/30"
          : ""
      }
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-sm">
              {LEVEL_LABELS[run.level] ?? `Level ${run.level}`}
            </CardTitle>
            <CardDescription className="text-xs mt-0.5">
              {LEVEL_DESC[run.level] ?? ""}
            </CardDescription>
          </div>
          <Badge
            variant={isFailed ? "destructive" : isPassed ? "default" : "secondary"}
            className={
              isPassed
                ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs"
                : "text-xs"
            }
          >
            {run.status}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Hero pass/fail indicator */}
        {!isRunning && (
          <div className="flex flex-col items-center py-2">
            {isPassed ? (
              <CheckCircle2 className="h-12 w-12 text-emerald-500" />
            ) : isFailed ? (
              <XCircle className="h-12 w-12 text-destructive" />
            ) : (
              <ClipboardCheck className="h-12 w-12 text-muted-foreground/40" />
            )}
            <p className="text-base font-semibold mt-2">
              {isPassed
                ? "All Passed"
                : isFailed
                ? `${run.fail_count} Failed`
                : "Pending"}
            </p>
            {total > 0 && (
              <p className="text-xs text-muted-foreground">
                {run.pass_count} of {total} checks passed
              </p>
            )}
          </div>
        )}

        {isRunning && (
          <div className="flex flex-col items-center py-4 gap-2">
            <Loader2 className="h-10 w-10 text-primary animate-spin" />
            <p className="text-sm text-muted-foreground">Running…</p>
          </div>
        )}

        {/* Timestamps */}
        <div className="text-xs text-muted-foreground space-y-0.5">
          {run.started_at && (
            <p>Started: {new Date(run.started_at).toLocaleString()}</p>
          )}
          {run.completed_at && (
            <p>Completed: {new Date(run.completed_at).toLocaleString()}</p>
          )}
        </div>

        {/* Inline report summary */}
        {(run.status === "COMPLETED" || run.status === "FAILED") && (
          <div className="rounded-md border bg-muted/20 overflow-hidden">
            {reportLoading && !report && (
              <div className="px-3 py-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading details…
              </div>
            )}
            {report && report.results.length > 0 && (
              <div className="max-h-72 overflow-y-auto">
                {run.level === 2 && (
                  <p className="px-2 py-1.5 text-[10px] text-muted-foreground border-b bg-muted/10">
                    Functions: MIN, MAX, SUM, AVG per numeric column
                  </p>
                )}
                {run.level === 2 ? (
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                      <tr className="border-b">
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">Table</th>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">Column</th>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">Status</th>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">MIN</th>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">MAX</th>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">SUM</th>
                        <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">AVG</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.results.flatMap((row) => {
                        const cols = (row.details?.column_results as Array<{
                          column: string;
                          status: string;
                          source?: Record<string, unknown>;
                          target?: Record<string, unknown>;
                        }> | undefined) ?? [];
                        if (cols.length === 0) {
                          return [
                            <tr key={row.validation_id} className="border-b border-border/50">
                              <td className="px-2 py-1.5 font-mono truncate max-w-[100px]" title={row.object_name}>
                                {row.object_name}
                              </td>
                              <td colSpan={6} className="px-2 py-1.5 text-muted-foreground">
                                {row.status}
                                {row.details?.skip_reason === "no_numeric_columns"
                                  ? " — no numeric columns"
                                  : ""}
                              </td>
                            </tr>,
                          ];
                        }
                        return cols.map((col, idx) => (
                          <tr
                            key={`${row.validation_id}-${col.column}`}
                            className="border-b border-border/50"
                          >
                            <td className="px-2 py-1.5 font-mono truncate max-w-[100px]" title={row.object_name}>
                              {idx === 0 ? row.object_name : ""}
                            </td>
                            <td className="px-2 py-1.5 font-mono">{col.column}</td>
                            <td className="px-2 py-1.5">
                              <span
                                className={
                                  col.status === "passed"
                                    ? "text-emerald-400"
                                    : col.status === "failed" || col.status === "error"
                                    ? "text-red-400"
                                    : "text-amber-400"
                                }
                              >
                                {col.status}
                              </span>
                            </td>
                            <td className="px-2 py-1.5 font-mono tabular-nums text-[10px]">
                              {formatAggCell(col.source, col.target, "min")}
                            </td>
                            <td className="px-2 py-1.5 font-mono tabular-nums text-[10px]">
                              {formatAggCell(col.source, col.target, "max")}
                            </td>
                            <td className="px-2 py-1.5 font-mono tabular-nums text-[10px]">
                              {formatAggCell(col.source, col.target, "sum")}
                            </td>
                            <td className="px-2 py-1.5 font-mono tabular-nums text-[10px]">
                              {formatAggCell(col.source, col.target, "avg")}
                            </td>
                          </tr>
                        ));
                      })}
                    </tbody>
                  </table>
                ) : (
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                    <tr className="border-b">
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">
                        {run.level === 3 ? "Chunk" : "Object"}
                      </th>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">Status</th>
                      <th className="px-2 py-1.5 text-right font-medium text-muted-foreground">Source</th>
                      <th className="px-2 py-1.5 text-right font-medium text-muted-foreground">Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.results.map((row) => (
                      <tr key={row.validation_id} className="border-b border-border/50">
                        <td className="px-2 py-1.5 font-mono truncate max-w-[140px]" title={row.object_name}>
                          {row.object_name}
                        </td>
                        <td className="px-2 py-1.5">
                          <span
                            className={
                              row.status === "passed"
                                ? "text-emerald-400"
                                : row.status === "failed"
                                ? "text-red-400"
                                : "text-amber-400"
                            }
                          >
                            {row.status}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                          {row.source_count ?? "—"}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                          {row.target_count ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                )}
              </div>
            )}
            {report && report.results.some(
              (r) =>
                (r.status === "failed" || r.status === "error") &&
                (r.issues?.some((issue) => issue.severity === "error") ?? false),
            ) && (
              <div className="px-2 py-2 border-t text-[11px] space-y-1.5 max-h-32 overflow-y-auto">
                <p className="font-semibold text-red-400/90">Failure summary</p>
                {report.results
                  .filter((r) => r.status === "failed" || r.status === "error")
                  .flatMap((r) =>
                    (r.issues ?? [])
                      .filter((issue) => issue.severity === "error")
                      .map((issue, idx) => (
                      <p key={`${r.validation_id}-${idx}`} className="text-muted-foreground">
                        <span className="font-mono text-foreground/80">{r.object_name}:</span>{" "}
                        {issue.message}
                      </p>
                    )),
                  )}
              </div>
            )}
          </div>
        )}

        {/* Download dropdown */}
        {(run.status === "COMPLETED" || run.status === "FAILED") && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs h-8"
                disabled={!!isDownloading}
              >
                {isDownloading ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5 mr-1.5" />
                )}
                Download Report
                <ChevronDown className="h-3.5 w-3.5 ml-auto opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuLabel className="text-[10px]">Format</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => onDownload(run.run_id, "json")}>
                JSON
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onDownload(run.run_id, "csv")}>
                CSV
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onDownload(run.run_id, "html")}>
                HTML Report
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Skeleton cards
// ---------------------------------------------------------------------------

function RunCardSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="space-y-1.5">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-48" />
          </div>
          <Skeleton className="h-5 w-20" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col items-center py-2 gap-2">
          <Skeleton className="h-12 w-12 rounded-full" />
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-3 w-32" />
        </div>
        <Skeleton className="h-8 w-full" />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ValidationPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [runs, setRuns] = useState<ValidationRunSummary[]>([]);
  const [reports, setReports] = useState<Record<string, ValidationReportJson>>({});
  const [reportsLoading, setReportsLoading] = useState(false);
  const [jobInfo, setJobInfo] = useState<MigrationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [selectedLevels, setSelectedLevels] = useState<Set<number>>(new Set([1, 2, 3]));
  const [autoRunAttempted, setAutoRunAttempted] = useState(false);
  const [rowSamples, setRowSamples] = useState<RowSampleResponse | null>(null);
  const [rowSamplesLoading, setRowSamplesLoading] = useState(false);

  const loadReports = useCallback(async (runList: ValidationRunSummary[]) => {
    const finished = runList.filter(
      (r) =>
        isSupportedValidationLevel(r.level) &&
        (r.status === "COMPLETED" || r.status === "FAILED"),
    );
    if (finished.length === 0) {
      setReports({});
      return;
    }
    setReportsLoading(true);
    try {
      const entries = await Promise.allSettled(
        finished.map(async (r) => {
          const report = await getValidationRunReportJson(r.run_id);
          return [r.run_id, report] as const;
        }),
      );
      const next: Record<string, ValidationReportJson> = {};
      for (const entry of entries) {
        if (entry.status === "fulfilled") {
          const [runId, report] = entry.value;
          next[runId] = report;
        }
      }
      setReports(next);
    } finally {
      setReportsLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    if (!jobId) return;
    setLoading(true);
    try {
      const [data, info] = await Promise.allSettled([
        getValidationRuns(jobId),
        getMigration(jobId),
      ]);
      if (data.status === "fulfilled") {
        setRuns(data.value);
        void loadReports(data.value);
      }
      if (info.status === "fulfilled") setJobInfo(info.value);
      if (data.status === "rejected") toast.error("Failed to load validation runs");
    } finally {
      setLoading(false);
    }
  }, [jobId, loadReports]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRunValidation = useCallback(async () => {
    if (!jobId || !jobInfo) { toast.error("Migration info not loaded yet"); return; }
    const srcId = (jobInfo as unknown as { source_connection_id?: string }).source_connection_id;
    const tgtId = (jobInfo as unknown as { target_connection_id?: string }).target_connection_id;
    const tables = (jobInfo as unknown as {
      tables?: Array<{ table: string; strategy?: string }>;
      source_schema?: string;
      target_schema?: string;
    }).tables ?? [];
    const sourceSchema = (jobInfo as unknown as { source_schema?: string }).source_schema ?? "dbo";
    const targetSchema = (jobInfo as unknown as { target_schema?: string }).target_schema ?? "public";
    if (!srcId || !tgtId) {
      toast.error("Migration is missing source or target connection info");
      return;
    }
    setRunning(true);
    try {
      const newRuns = await runValidationLevels(jobId, {
        source_connection_id: srcId,
        target_connection_id: tgtId,
        tables: tables.map((t) => ({
          name: t.table,
          schema: sourceSchema,
          target_schema: targetSchema,
        })),
        levels: Array.from(selectedLevels).sort(),
      });
      toast.success(`Validation completed: ${newRuns.length} level(s) run`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Validation failed to start");
    } finally {
      setRunning(false);
    }
  }, [jobId, jobInfo, selectedLevels, load]);

  useEffect(() => {
    const hasSupportedRuns = runs.some((r) => isSupportedValidationLevel(r.level));
    if (!loading && !hasSupportedRuns && jobInfo && !autoRunAttempted && !running) {
      setAutoRunAttempted(true);
      void handleRunValidation();
    }
  }, [loading, runs, jobInfo, autoRunAttempted, running, handleRunValidation]);

  const handleLoadRowSamples = async () => {
    if (!jobId || !jobInfo) return;
    const srcId = (jobInfo as unknown as { source_connection_id?: string }).source_connection_id;
    const tgtId = (jobInfo as unknown as { target_connection_id?: string }).target_connection_id;
    const tables = (jobInfo as unknown as { tables?: Array<{ table: string }> }).tables ?? [];
    if (!srcId || !tgtId || tables.length === 0) return;
    setRowSamplesLoading(true);
    try {
      const sample = await compareRowSamples(jobId, {
        source_connection_id: srcId,
        target_connection_id: tgtId,
        table_name: tables[0].table,
        source_schema: (jobInfo as unknown as { source_schema?: string }).source_schema ?? "dbo",
        target_schema: (jobInfo as unknown as { target_schema?: string }).target_schema ?? "public",
        limit: 10,
      });
      setRowSamples(sample);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load row samples");
    } finally {
      setRowSamplesLoading(false);
    }
  };

  const handleDownload = async (runId: string, fmt: "json" | "csv" | "html") => {
    setDownloading(`${runId}-${fmt}`);
    try {
      const content = await getValidationRunReport(runId, fmt);
      const mime =
        fmt === "html" ? "text/html" : fmt === "csv" ? "text/csv" : "application/json";
      const blob = new Blob([content], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `validation_${runId}_L${runs.find((r) => r.run_id === runId)?.level ?? ""}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Report downloaded as ${fmt.toUpperCase()}`);
    } catch {
      toast.error("Download failed");
    } finally {
      setDownloading(null);
    }
  };

  const visibleRuns = runs.filter((r) => isSupportedValidationLevel(r.level));

  const passedRuns = visibleRuns.filter(
    (r) => r.status === "COMPLETED" && r.fail_count === 0,
  ).length;
  const failedRuns = visibleRuns.filter(
    (r) => r.fail_count > 0 || r.status === "FAILED",
  ).length;

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Validation Results"
        description={
          jobInfo
            ? `${jobInfo.table_count ?? 0} table${(jobInfo.table_count ?? 0) !== 1 ? "s" : ""} · ${jobInfo.status ?? "unknown"}`
            : `Job ${jobId?.slice(0, 8)}…`
        }
      >
        <Button variant="outline" size="sm" asChild>
          <Link href="/migrations">
            <ArrowLeft className="h-4 w-4 mr-1" /> Back
          </Link>
        </Button>
        <Button size="sm" onClick={load} disabled={loading} variant="outline">
          <RefreshCw
            className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
        <Button size="sm" onClick={handleRunValidation} disabled={running || loading || !jobInfo}>
          {running ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <ClipboardCheck className="h-4 w-4 mr-1" />
          )}
          Run Validation
        </Button>
      </PageHeader>

      {/* Level selector */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground">Run levels:</span>
        {[1, 2, 3].map((lvl) => (
          <button
            key={lvl}
            onClick={() =>
              setSelectedLevels((prev) => {
                const next = new Set(prev);
                next.has(lvl) ? next.delete(lvl) : next.add(lvl);
                return next;
              })
            }
            className={`px-2.5 py-0.5 rounded-full text-xs border transition-colors ${
              selectedLevels.has(lvl)
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background text-muted-foreground border-border hover:border-primary/50"
            }`}
          >
            L{lvl}
          </button>
        ))}
        <span className="text-xs text-muted-foreground ml-1">
          L1 row count · L2 MIN/MAX/SUM/AVG · L3 chunk hashes — use row samples below for spot checks
        </span>
      </div>

      {/* Summary badges */}
      {visibleRuns.length > 0 && !loading && (
        <div className="flex gap-4 text-sm">
          <Badge
            variant="outline"
            className="gap-1.5 text-emerald-400 border-emerald-500/30"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {passedRuns} passed
          </Badge>
          <Badge
            variant="outline"
            className="gap-1.5 text-red-400 border-red-500/30"
          >
            <XCircle className="h-3.5 w-3.5" />
            {failedRuns} failed
          </Badge>
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <RunCardSkeleton key={i} />
          ))}
        </div>
      ) : visibleRuns.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title="No validation runs yet"
          description="Run L1–L3 validation using the button above, or start from the Migrations page."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleRuns
            .sort((a, b) => a.level - b.level)
            .map((run) => (
              <RunCard
                key={run.run_id}
                run={run}
                report={reports[run.run_id]}
                reportLoading={reportsLoading}
                onDownload={handleDownload}
                downloading={downloading}
              />
            ))}
        </div>
      )}

      {jobInfo && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm">Top 10 Row Comparison</CardTitle>
                <CardDescription className="text-xs">
                  Side-by-side preview sorted by primary key (or first column)
                </CardDescription>
              </div>
              <Button size="sm" variant="outline" onClick={handleLoadRowSamples} disabled={rowSamplesLoading}>
                {rowSamplesLoading ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}
                Load samples
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {!rowSamples && !rowSamplesLoading && (
              <p className="text-xs text-muted-foreground">Click Load samples to compare the first 10 rows.</p>
            )}
            {rowSamples && (
              <div className="space-y-2">
                <p className="text-[10px] text-muted-foreground font-mono">
                  {rowSamples.table_name} · sorted by {rowSamples.sort_column} ({rowSamples.sort_column_type})
                </p>
                <div className="grid grid-cols-2 gap-0 border rounded-md overflow-hidden text-[10px]">
                  <div className="border-r">
                    <div className="px-2 py-1.5 bg-muted/40 font-semibold">
                      Source ({rowSamples.source_count} rows)
                    </div>
                    <pre className="p-2 overflow-auto max-h-64 font-mono whitespace-pre-wrap">
                      {JSON.stringify(rowSamples.source_rows, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="px-2 py-1.5 bg-muted/40 font-semibold">
                      Target ({rowSamples.target_count} rows)
                    </div>
                    <pre className="p-2 overflow-auto max-h-64 font-mono whitespace-pre-wrap">
                      {JSON.stringify(rowSamples.target_rows, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
