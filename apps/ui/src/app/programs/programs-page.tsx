/**
 * Module: app/programs/programs-page.tsx
 * Purpose: Migration programs / waves Gantt skeleton (§13.1)
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarRange, Loader2, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformError } from "@/components/shared/platform-error";
import {
  getProjects,
  listPrograms,
  type MigrationProgram,
  type MigrationWave,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function waveWindowMs(wave: MigrationWave): { start: number; end: number } | null {
  if (!wave.cutover_window_start || !wave.cutover_window_end) return null;
  const start = Date.parse(wave.cutover_window_start);
  const end = Date.parse(wave.cutover_window_end);
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return null;
  return { start, end };
}

function statusVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "approved" || status === "completed") return "default";
  if (status === "failed") return "destructive";
  if (status === "running") return "secondary";
  return "outline";
}

function ProgramGantt({ program, range }: { program: MigrationProgram; range: { min: number; max: number } }) {
  const span = Math.max(range.max - range.min, 1);
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">{program.name}</CardTitle>
          <Badge variant={statusVariant(program.status)}>{program.status}</Badge>
        </div>
        <CardDescription>
          {program.owner ? `Owner: ${program.owner}` : "No owner"} · {program.waves.length} wave
          {program.waves.length === 1 ? "" : "s"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {program.waves.length === 0 ? (
          <p className="text-sm text-muted-foreground">No waves yet.</p>
        ) : (
          program.waves.map((wave) => {
            const win = waveWindowMs(wave);
            const left = win ? ((win.start - range.min) / span) * 100 : 0;
            const width = win ? ((win.end - win.start) / span) * 100 : 12;
            return (
              <div key={wave.id} className="grid gap-2 sm:grid-cols-[10rem_1fr] items-center">
                <div className="text-sm">
                  <div className="font-medium truncate">
                    W{wave.wave_number}: {wave.name}
                  </div>
                  <div className="text-xs text-muted-foreground truncate">
                    {wave.tables.length} table{wave.tables.length === 1 ? "" : "s"} · {wave.status}
                  </div>
                </div>
                <div
                  className="relative h-8 rounded-md bg-muted/60 overflow-hidden"
                  role="img"
                  aria-label={
                    win
                      ? `${wave.name} cutover from ${new Date(win.start).toLocaleString()} to ${new Date(win.end).toLocaleString()}`
                      : `${wave.name} has no cutover window scheduled`
                  }
                >
                  <div
                    className={cn(
                      "absolute top-1 bottom-1 rounded-sm",
                      win ? "bg-primary/80" : "bg-muted-foreground/30 border border-dashed border-muted-foreground/40",
                    )}
                    style={{
                      left: `${Math.max(0, Math.min(left, 88))}%`,
                      width: `${Math.max(win ? 4 : 12, Math.min(width, 100 - left))}%`,
                    }}
                    title={
                      win
                        ? `${new Date(win.start).toISOString()} → ${new Date(win.end).toISOString()}`
                        : "Schedule a cutover window"
                    }
                  />
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

export default function ProgramsPage() {
  const [projectId, setProjectId] = useState<string>("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    staleTime: 60_000,
  });

  const programsQuery = useQuery({
    queryKey: ["programs", projectId || "all"],
    queryFn: () => listPrograms(projectId || undefined),
  });

  const range = useMemo(() => {
    const programs = programsQuery.data ?? [];
    const times: number[] = [];
    for (const p of programs) {
      for (const w of p.waves) {
        const win = waveWindowMs(w);
        if (win) {
          times.push(win.start, win.end);
        }
      }
    }
    if (times.length === 0) {
      const now = Date.now();
      return { min: now, max: now + 7 * 24 * 60 * 60 * 1000 };
    }
    return { min: Math.min(...times), max: Math.max(...times) };
  }, [programsQuery.data]);

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Programs"
        description="Wave cutover schedule (Gantt) for multi-wave migration programs"
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => programsQuery.refetch()}
          disabled={programsQuery.isFetching}
        >
          {programsQuery.isFetching ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4 mr-1" />
          )}
          Refresh
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-muted-foreground" htmlFor="program-project">
          Project filter
        </label>
        <select
          id="program-project"
          className="h-9 rounded-md border bg-background px-3 text-sm"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        >
          <option value="">All projects</option>
          {(projectsQuery.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      {programsQuery.isError ? (
        <PlatformError
          error={programsQuery.error as Error}
          onRetry={() => programsQuery.refetch()}
        />
      ) : null}

      {programsQuery.isPending ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading programs…
        </div>
      ) : null}

      {!programsQuery.isPending && (programsQuery.data?.length ?? 0) === 0 ? (
        <Card>
          <CardContent className="py-10 text-center space-y-2">
            <CalendarRange className="h-10 w-10 mx-auto text-muted-foreground" />
            <p className="font-medium">No migration programs yet</p>
            <p className="text-sm text-muted-foreground">
              Create a program via the API, then schedule wave cutover windows to see them here.
            </p>
          </CardContent>
        </Card>
      ) : null}

      <div className="space-y-4">
        {(programsQuery.data ?? []).map((program) => (
          <ProgramGantt key={program.id} program={program} range={range} />
        ))}
      </div>
    </div>
  );
}
