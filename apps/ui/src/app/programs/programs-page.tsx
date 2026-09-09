/**
 * Module: app/programs/programs-page.tsx
 * Purpose: Migration programs / waves Gantt with create + schedule UX (§13.1)
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Loader2, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
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
  ApiError,
  createProgram,
  getAuthUsername,
  getProjects,
  listPrograms,
  scheduleProgramWave,
  signOffProgramWave,
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

function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function ProgramGantt({
  program,
  range,
  onScheduled,
}: {
  program: MigrationProgram;
  range: { min: number; max: number };
  onScheduled: () => void;
}) {
  const span = Math.max(range.max - range.min, 1);
  const [schedulingWaveId, setSchedulingWaveId] = useState<string | null>(null);
  const [startLocal, setStartLocal] = useState("");
  const [endLocal, setEndLocal] = useState("");

  const scheduleMutation = useMutation({
    mutationFn: () =>
      scheduleProgramWave(schedulingWaveId!, {
        cutover_window_start: new Date(startLocal).toISOString(),
        cutover_window_end: new Date(endLocal).toISOString(),
      }),
    onSuccess: () => {
      toast.success("Cutover window saved");
      setSchedulingWaveId(null);
      onScheduled();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Failed to schedule wave");
    },
  });

  const signOffMutation = useMutation({
    mutationFn: (waveId: string) =>
      signOffProgramWave(waveId, getAuthUsername() || "operator"),
    onSuccess: () => {
      toast.success("Wave signed off");
      onScheduled();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Sign-off failed");
    },
  });

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
          <p className="text-sm text-muted-foreground">
            No waves yet. Add waves via the API or a future wave builder.
          </p>
        ) : (
          program.waves.map((wave) => {
            const win = waveWindowMs(wave);
            const left = win ? ((win.start - range.min) / span) * 100 : 0;
            const width = win ? ((win.end - win.start) / span) * 100 : 12;
            const isScheduling = schedulingWaveId === wave.id;
            return (
              <div key={wave.id} className="space-y-2">
                <div className="grid gap-2 sm:grid-cols-[10rem_1fr_auto] items-center">
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
                        win
                          ? "bg-primary/80"
                          : "bg-muted-foreground/30 border border-dashed border-muted-foreground/40",
                      )}
                      style={{
                        left: `${Math.max(0, Math.min(left, 88))}%`,
                        width: `${Math.max(win ? 4 : 12, Math.min(width, 100 - left))}%`,
                      }}
                    />
                  </div>
                  <div className="flex gap-1 justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        const now = new Date();
                        const later = new Date(now.getTime() + 2 * 60 * 60 * 1000);
                        setSchedulingWaveId(wave.id);
                        setStartLocal(
                          wave.cutover_window_start
                            ? toLocalInputValue(new Date(wave.cutover_window_start))
                            : toLocalInputValue(now),
                        );
                        setEndLocal(
                          wave.cutover_window_end
                            ? toLocalInputValue(new Date(wave.cutover_window_end))
                            : toLocalInputValue(later),
                        );
                      }}
                    >
                      Schedule
                    </Button>
                    {wave.status !== "approved" ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        disabled={signOffMutation.isPending}
                        onClick={() => signOffMutation.mutate(wave.id)}
                      >
                        Sign off
                      </Button>
                    ) : null}
                  </div>
                </div>
                {isScheduling ? (
                  <div className="flex flex-wrap items-end gap-2 rounded-md border bg-muted/30 p-3">
                    <label className="text-xs space-y-1">
                      <span className="text-muted-foreground">Start</span>
                      <input
                        type="datetime-local"
                        className="block h-9 rounded-md border bg-background px-2 text-sm"
                        value={startLocal}
                        onChange={(e) => setStartLocal(e.target.value)}
                      />
                    </label>
                    <label className="text-xs space-y-1">
                      <span className="text-muted-foreground">End</span>
                      <input
                        type="datetime-local"
                        className="block h-9 rounded-md border bg-background px-2 text-sm"
                        value={endLocal}
                        onChange={(e) => setEndLocal(e.target.value)}
                      />
                    </label>
                    <Button
                      type="button"
                      size="sm"
                      disabled={
                        scheduleMutation.isPending || !startLocal || !endLocal
                      }
                      onClick={() => scheduleMutation.mutate()}
                    >
                      {scheduleMutation.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        "Save window"
                      )}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setSchedulingWaveId(null)}
                    >
                      Cancel
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

export default function ProgramsPage() {
  const qc = useQueryClient();
  const [projectId, setProjectId] = useState<string>("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [createProjectId, setCreateProjectId] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    staleTime: 60_000,
  });

  const programsQuery = useQuery({
    queryKey: ["programs", projectId || "all"],
    queryFn: () => listPrograms(projectId || undefined),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createProgram({
        project_id: createProjectId,
        name: newName.trim(),
        owner: getAuthUsername() || undefined,
      }),
    onSuccess: () => {
      toast.success("Program created");
      setShowCreate(false);
      setNewName("");
      qc.invalidateQueries({ queryKey: ["programs"] });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not create program");
    },
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

  const projects = projectsQuery.data ?? [];

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
        <Button
          size="sm"
          onClick={() => {
            setCreateProjectId(projectId || projects[0]?.id || "");
            setShowCreate(true);
          }}
          disabled={projects.length === 0}
        >
          <Plus className="h-4 w-4 mr-1" />
          New program
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
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      {showCreate ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Create migration program</CardTitle>
            <CardDescription>
              Programs group waves with cutover windows and sign-off.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3 items-end">
            <label className="text-sm space-y-1">
              <span className="text-muted-foreground">Project</span>
              <select
                className="block h-9 rounded-md border bg-background px-3 text-sm min-w-[12rem]"
                value={createProjectId}
                onChange={(e) => setCreateProjectId(e.target.value)}
              >
                <option value="">Select project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm space-y-1 grow">
              <span className="text-muted-foreground">Name</span>
              <input
                className="block h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Wave program name"
              />
            </label>
            <Button
              type="button"
              disabled={
                createMutation.isPending || !createProjectId || !newName.trim()
              }
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Create"
              )}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {programsQuery.isError ? (
        <PlatformError
          error={programsQuery.error as Error}
          onRetry={() => programsQuery.refetch()}
        />
      ) : null}

      {programsQuery.isPending ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading programs…
        </div>
      ) : null}

      {!programsQuery.isPending && (programsQuery.data?.length ?? 0) === 0 ? (
        <Card>
          <CardContent className="py-10 text-center space-y-3">
            <CalendarRange className="h-10 w-10 mx-auto text-muted-foreground" />
            <p className="font-medium">No migration programs yet</p>
            <p className="text-sm text-muted-foreground">
              Create a program, then schedule wave cutover windows on the Gantt.
            </p>
            <Button
              size="sm"
              onClick={() => {
                setCreateProjectId(projectId || projects[0]?.id || "");
                setShowCreate(true);
              }}
              disabled={projects.length === 0}
            >
              <Plus className="h-4 w-4 mr-1" />
              New program
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="space-y-4">
        {(programsQuery.data ?? []).map((program) => (
          <ProgramGantt
            key={program.id}
            program={program}
            range={range}
            onScheduled={() => qc.invalidateQueries({ queryKey: ["programs"] })}
          />
        ))}
      </div>
    </div>
  );
}
