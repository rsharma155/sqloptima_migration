"use client";

/**
 * Module: app/reports/page.tsx
 * Purpose: Reports hub — lists completed migration jobs and allows downloading
 *          migration summary and validation summary reports in JSON or HTML.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback } from "react";
import {
  FileText,
  Download,
  Loader2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getMigrations,
  getMigrationReport,
  getValidationSummaryReport,
  type MigrationResponse,
  type MigrationSummaryReport,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const upper = status.toUpperCase();
  if (upper === "COMPLETED")
    return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">{upper}</Badge>;
  if (upper === "FAILED" || upper === "STOPPED")
    return <Badge variant="destructive">{upper}</Badge>;
  if (upper === "RUNNING")
    return <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30">{upper}</Badge>;
  return <Badge variant="secondary">{upper}</Badge>;
}

// ---------------------------------------------------------------------------
// Download helper
// ---------------------------------------------------------------------------

function downloadText(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Job report row
// ---------------------------------------------------------------------------

function JobReportRow({ job }: { job: MigrationResponse }) {
  const [downloading, setDownloading] = useState<string | null>(null);
  const [summary, setSummary] = useState<MigrationSummaryReport | null>(null);
  const [expanded, setExpanded] = useState(false);

  const loadSummary = async () => {
    if (summary) { setExpanded(!expanded); return; }
    try {
      const data = await getMigrationReport(job.job_id);
      setSummary(data);
      setExpanded(true);
    } catch {
      toast.error("Failed to load report");
    }
  };

  const downloadMigration = async (fmt: "json" | "html") => {
    setDownloading(`migration-${fmt}`);
    try {
      if (fmt === "json") {
        const data = await getMigrationReport(job.job_id);
        downloadText(JSON.stringify(data, null, 2), `migration_${job.job_id.slice(0, 8)}.json`, "application/json");
      } else {
        const { downloadMigrationReportHtml } = await import("@/lib/api");
        const html = await downloadMigrationReportHtml(job.job_id);
        downloadText(html, `migration_${job.job_id.slice(0, 8)}.html`, "text/html");
      }
      toast.success("Downloaded");
    } catch {
      toast.error("Download failed");
    } finally {
      setDownloading(null);
    }
  };

  const downloadValidation = async () => {
    setDownloading("validation");
    try {
      const data = await getValidationSummaryReport(job.job_id);
      downloadText(JSON.stringify(data, null, 2), `validation_${job.job_id.slice(0, 8)}.json`, "application/json");
      toast.success("Validation report downloaded");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No validation runs found");
    } finally {
      setDownloading(null);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-sm font-mono">{job.job_id.slice(0, 16)}…</CardTitle>
            <CardDescription className="text-xs mt-0.5 flex items-center gap-2">
              <StatusBadge status={job.status} />
              <span>{job.table_count ?? 0} tables</span>
              <span>·</span>
              <span>{new Date(job.created_at).toLocaleDateString()}</span>
            </CardDescription>
          </div>
          <Button size="sm" variant="ghost" className="text-xs h-7" onClick={loadSummary}>
            {expanded ? "Hide" : "Details"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Summary preview when expanded */}
        {expanded && summary && (
          <div className="grid grid-cols-2 gap-2 text-xs bg-muted/30 rounded p-3">
            <div>
              <p className="text-muted-foreground">Rows migrated</p>
              <p className="font-semibold">{(summary.rows_migrated ?? 0).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Tables done</p>
              <p className="font-semibold">{summary.tables_done} / {summary.tables_total}</p>
            </div>
            {summary.duration_seconds != null && (
              <div>
                <p className="text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" /> Duration
                </p>
                <p className="font-semibold">
                  {summary.duration_seconds < 60
                    ? `${summary.duration_seconds.toFixed(1)}s`
                    : `${(summary.duration_seconds / 60).toFixed(1)}m`}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Download buttons */}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            className="text-xs h-7"
            onClick={() => downloadMigration("json")}
            disabled={!!downloading}
          >
            {downloading === "migration-json" ? (
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            ) : (
              <Download className="h-3 w-3 mr-1" />
            )}
            Migration JSON
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="text-xs h-7"
            onClick={() => downloadMigration("html")}
            disabled={!!downloading}
          >
            {downloading === "migration-html" ? (
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            ) : (
              <Download className="h-3 w-3 mr-1" />
            )}
            Migration HTML
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="text-xs h-7"
            onClick={downloadValidation}
            disabled={!!downloading}
          >
            {downloading === "validation" ? (
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            ) : (
              <Download className="h-3 w-3 mr-1" />
            )}
            Validation JSON
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-xs h-7"
            asChild
          >
            <a href={`/validation/${job.job_id}`}>View Validation →</a>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const [jobs, setJobs] = useState<MigrationResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getMigrations();
      setJobs(data);
    } catch {
      toast.error("Failed to load migration jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const completed = jobs.filter((j) =>
    ["COMPLETED", "FAILED", "STOPPED"].includes(j.status.toUpperCase()),
  );

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Reports"
        description="Download migration summaries and validation reports for completed jobs"
      >
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </PageHeader>

      {loading ? (
        <div className="flex justify-center py-16" role="status" aria-label="Loading">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : completed.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No completed jobs"
          description="Reports are available once a migration job has completed, failed, or been stopped."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {completed.map((job) => (
            <JobReportRow key={job.job_id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}
