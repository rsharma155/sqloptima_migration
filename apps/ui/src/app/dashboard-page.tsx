"use client";

/**
 * Module: app/page.tsx
 * Purpose: Live dashboard — migration job status, per-job progress polling,
 *          recent projects, and system health. Uses TanStack Query for
 *          declarative refetch (no setInterval, window-focus revalidation).
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useEffect, useState } from "react";
import {
  Database,
  CheckCircle2,
  ArrowRight,
  Loader2,
  FolderOpen,
  ShieldCheck,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Play,
  LogIn,
  Activity,
} from "lucide-react";
import { StatsCard } from "@/components/dashboard/stats-card";
import { AlertsPanel } from "@/components/dashboard/alerts-panel";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import {
  healthCheck,
  getMigrations,
  getProjects,
  getToken,
  type MigrationResponse,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const upper = status.toUpperCase();
  if (upper === "COMPLETED")
    return (
      <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs">
        {upper}
      </Badge>
    );
  if (["FAILED", "STOPPED"].includes(upper))
    return (
      <Badge variant="destructive" className="text-xs">
        {upper}
      </Badge>
    );
  if (["RUNNING", "IN_PROGRESS"].includes(upper))
    return (
      <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30 text-xs">
        RUNNING
      </Badge>
    );
  if (upper === "PAUSED")
    return (
      <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30 text-xs">
        PAUSED
      </Badge>
    );
  return (
    <Badge variant="secondary" className="text-xs">
      {upper}
    </Badge>
  );
}

function MigrationCard({ job }: { job: MigrationResponse }) {
  const isRunning = ["RUNNING", "IN_PROGRESS"].includes(job.status.toUpperCase());
  const pct = (job as unknown as Record<string, number>).overall_percentage ?? 0;

  return (
    <a
      href={`/migrations/${job.job_id}`}
      className="flex items-center justify-between py-3 border-b border-border last:border-0 hover:bg-muted/30 px-1 -mx-1 rounded transition-colors cursor-pointer"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground truncate max-w-[200px]">
            {new Date(job.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            {" · "}
            {new Date(job.created_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}
          </span>
          <StatusBadge status={job.status} />
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          {job.table_count ?? 0} table{(job.table_count ?? 0) !== 1 ? "s" : ""}
          {" · "}
          <span className="font-mono">{job.job_id.slice(0, 8)}…</span>
        </p>
        {(isRunning || job.status.toUpperCase() === "COMPLETED") && (
          <Progress
            value={isRunning ? pct : 100}
            aria-label="Migration progress"
            className={`h-1 mt-1.5 w-40 bg-muted ${
              job.status.toUpperCase() === "COMPLETED" ? "[&>*]:bg-emerald-500" : "[&>*]:bg-primary"
            }`}
          />
        )}
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="text-xs h-7 ml-3 shrink-0 pointer-events-none"
        tabIndex={-1}
      >
        View →
      </Button>
    </a>
  );
}

function StatsSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 w-4 rounded" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-8 w-10 mb-1" />
            <Skeleton className="h-3 w-32" />
          </CardContent>
        </Card>
      ))}
    </>
  );
}

function RecentJobsSkeleton() {
  return (
    <div className="space-y-3 py-1">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 py-3 border-b border-border last:border-0">
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-48" />
            <Skeleton className="h-3 w-32" />
          </div>
          <Skeleton className="h-6 w-12" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const qc = useQueryClient();
  const [isAuthed, setIsAuthed] = useState(false);
  useEffect(() => { setIsAuthed(!!getToken()); }, []);

  const { data: healthData, isError: healthError } = useQuery({
    queryKey: ["health"],
    queryFn: healthCheck,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
  const healthy = !healthError && !!healthData;

  const { data: migrations = [], isPending: migsPending } = useQuery({
    queryKey: ["migrations"],
    queryFn: getMigrations,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    enabled: isAuthed,
  });

  const { data: projects = [] } = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    enabled: isAuthed,
  });

  const lastSyncRef = useRef("—");
  useEffect(() => {
    if (healthData) lastSyncRef.current = new Date().toLocaleTimeString();
  }, [healthData]);

  const handleManualRefresh = () => {
    qc.invalidateQueries({ queryKey: ["migrations"] });
    qc.invalidateQueries({ queryKey: ["projects"] });
    qc.invalidateQueries({ queryKey: ["health"] });
    toast.info("Refreshing…");
  };

  const running = migrations.filter((m) =>
    ["RUNNING", "IN_PROGRESS"].includes(m.status.toUpperCase()),
  );

  // Rolling 10-point history for the "Active Migrations" sparkline
  const runningHistory = useRef<number[]>([]);
  useEffect(() => {
    runningHistory.current = [...runningHistory.current.slice(-9), running.length];
  }, [running.length]);
  const completed = migrations.filter(
    (m) => m.status.toUpperCase() === "COMPLETED",
  );
  const failed = migrations.filter((m) =>
    ["FAILED", "STOPPED"].includes(m.status.toUpperCase()),
  );
  const recent = [...migrations]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
    .slice(0, 5);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Live overview — auto-refreshes every 10 s
          </p>
        </div>
        <Button size="sm" onClick={handleManualRefresh}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {/* API health banner */}
      {healthError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <XCircle className="h-4 w-4" />
          API is unreachable — check that the backend is running on port 8508
        </div>
      )}

      {/* Stats row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {migsPending ? (
          <StatsSkeleton />
        ) : (
          <>
            <StatsCard
              title="Active Migrations"
              value={running.length > 0 ? String(running.length) : "0"}
              description={running.length > 0 ? "Currently running" : "No active jobs"}
              icon={Play}
              iconColor={running.length > 0 ? "text-primary" : "text-muted-foreground"}
              sparklineData={runningHistory.current}
              href="/migrations?status=running"
            />
            <StatsCard
              title="Completed"
              value={String(completed.length)}
              description="Successful migrations"
              icon={CheckCircle2}
              iconColor="text-emerald-500"
              href="/migrations?status=completed"
            />
            <StatsCard
              title="Failed / Stopped"
              value={String(failed.length)}
              description={failed.length > 0 ? "Need attention" : "No failures"}
              icon={failed.length > 0 ? AlertTriangle : CheckCircle2}
              iconColor={failed.length > 0 ? "text-destructive" : "text-muted-foreground"}
              href="/migrations?status=failed"
            />
            <StatsCard
              title="Projects"
              value={String(projects.length)}
              description={projects.length > 0 ? "Configured" : "None yet"}
              icon={FolderOpen}
              iconColor="text-muted-foreground"
              href="/projects"
            />
          </>
        )}
      </div>

      {/* Main content grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent migrations */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="pb-2 flex-row items-center justify-between">
              <div>
                <CardTitle className="text-base">Recent Jobs</CardTitle>
                <CardDescription>Last 5 migration jobs</CardDescription>
              </div>
              <Button size="sm" variant="outline" asChild>
                <a href="/migrations">All jobs</a>
              </Button>
            </CardHeader>
            <CardContent>
              {!isAuthed ? (
                <div className="flex flex-col items-center justify-center py-10 gap-3">
                  <LogIn className="h-10 w-10 text-muted-foreground/30" />
                  <p className="text-sm font-medium text-muted-foreground">
                    Sign in to view migration jobs
                  </p>
                </div>
              ) : migsPending ? (
                <RecentJobsSkeleton />
              ) : recent.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 gap-3">
                  <Database className="h-10 w-10 text-muted-foreground/30" />
                  <p className="text-sm font-medium text-muted-foreground">No migrations yet</p>
                  <Button size="sm" variant="outline" asChild>
                    <a href="/migrations">Start your first migration</a>
                  </Button>
                </div>
              ) : (
                recent.map((job) => <MigrationCard key={job.job_id} job={job} />)
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <AlertsPanel />

          {/* Projects */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <FolderOpen className="h-4 w-4" /> Projects
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {projects.slice(0, 4).map((p) => (
                <div key={p.id} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[160px]">{p.name}</span>
                  <Button size="sm" variant="ghost" className="text-xs h-6 shrink-0" asChild>
                    <a href={`/assessment?connectionId=${p.source_connection_id ?? ""}`}>
                      Assess
                    </a>
                  </Button>
                </div>
              ))}
              {projects.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No projects — create one to begin.
                </p>
              )}
              <Button size="sm" variant="outline" className="w-full mt-2" asChild>
                <a href="/projects">Manage Projects</a>
              </Button>
            </CardContent>
          </Card>

          {/* System Status */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Activity className="h-4 w-4" /> System Status
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">API</span>
                <Badge className={healthy
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs"
                  : "bg-destructive/15 text-destructive border-destructive/30 text-xs"}>
                  {healthy ? "Online" : "Offline"}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Last sync</span>
                <span className="font-mono text-xs text-foreground">{lastSyncRef.current}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Active jobs</span>
                <span className="font-mono text-xs text-foreground">{running.length}</span>
              </div>
              <div className="border-t pt-3 space-y-1.5">
                {[
                  { href: "/assessment", label: "Run Assessment", icon: ShieldCheck },
                  { href: "/migrations", label: "Start Migration", icon: ArrowRight },
                ].map(({ href, label, icon: Icon }) => (
                  <Button key={href} size="sm" variant="outline" className="w-full justify-start text-xs" asChild>
                    <a href={href}><Icon className="h-3.5 w-3.5 mr-2" />{label}</a>
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
