"use client";

/**
 * Module: procedural-migration-section.tsx
 * Purpose: Job detail section for stored procedure / function migration status and controls.
 */

import { Loader2, Play, RefreshCw, Code2, CheckCircle2, XCircle, AlertTriangle, Clock } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import {
  getProceduralMigrationStatus,
  runProceduralMigration,
  type ProceduralMigrationStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function statusBadge(status: string) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "applied") {
    return <Badge className="bg-emerald-600/90">{status}</Badge>;
  }
  if (s === "partial" || s === "in_progress") {
    return <Badge className="bg-blue-600/90">{status}</Badge>;
  }
  if (s === "failed") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  if (s === "skipped") {
    return <Badge variant="secondary">{status}</Badge>;
  }
  return <Badge variant="outline">{status}</Badge>;
}

function objectIcon(status: string | undefined) {
  const s = (status ?? "pending").toLowerCase();
  if (s === "applied") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
  if (s === "failed") return <XCircle className="h-3.5 w-3.5 text-destructive" />;
  if (s === "in_progress") return <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />;
  return <Clock className="h-3.5 w-3.5 text-muted-foreground" />;
}

export function ProceduralMigrationSection({
  jobId,
  migrationStatus,
  initialData,
}: {
  jobId: string;
  migrationStatus: string;
  initialData?: ProceduralMigrationStatus | null;
}) {
  const qc = useQueryClient();
  const terminal = ["completed", "failed", "stopped"].includes(migrationStatus.toLowerCase());

  const { data, isPending, refetch, isFetching } = useQuery({
    queryKey: ["procedural-migration", jobId],
    queryFn: () => getProceduralMigrationStatus(jobId),
    initialData: initialData ?? undefined,
    enabled: Boolean(initialData?.has_selection),
    refetchInterval: (query) => {
      const st = query.state.data?.status?.toLowerCase();
      if (st === "in_progress") return 3000;
      return false;
    },
  });

  const migrateMutation = useMutation({
    mutationFn: () => runProceduralMigration(jobId),
    onSuccess: (result) => {
      qc.setQueryData(["procedural-migration", jobId], result);
      if (result.last_error) {
        toast.error(result.last_error);
      } else {
        toast.success(`Procedural migration ${result.status}`);
      }
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Procedural migration failed");
    },
  });

  if (!data?.has_selection && !initialData?.has_selection) {
    return null;
  }

  const objects = Object.entries(data?.objects ?? {});
  const canRun =
    terminal &&
    data &&
    !["in_progress", "completed"].includes(data.status.toLowerCase());

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Code2 className="h-4 w-4" />
              Stored Procedures &amp; Functions
            </CardTitle>
            <CardDescription>
              T-SQL routines converted to PL/pgSQL on{" "}
              <code className="text-[10px]">{data?.target_schema ?? "public"}</code>
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {data && statusBadge(data.status)}
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            </Button>
            {canRun && (
              <Button
                size="sm"
                className="h-8"
                onClick={() => migrateMutation.mutate()}
                disabled={migrateMutation.isPending}
              >
                {migrateMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5 mr-1.5" />
                )}
                Migrate routines
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isPending && !data ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading procedural migration status…
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {data?.selected_procedures.length ?? 0} procedure(s),{" "}
              {data?.selected_functions.length ?? 0} function(s) selected
              {data?.auto_migrate_after_tables
                ? " · runs automatically after table migration when enabled at start"
                : ""}
            </p>
            {data?.last_error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {data.last_error}
              </div>
            )}
            {objects.length > 0 ? (
              <ul className="space-y-2">
                {objects.map(([key, obj]) => (
                  <li
                    key={key}
                    className="border rounded px-2 py-2 space-y-1.5"
                  >
                    <div className="flex items-center gap-2 text-xs font-mono">
                      {objectIcon(obj.status)}
                      <span className="truncate flex-1">{key}</span>
                      <Badge variant="outline" className="text-[10px] h-5 shrink-0">
                        {obj.object_type}
                      </Badge>
                      <span className="text-[10px] text-muted-foreground shrink-0">{obj.status}</span>
                      {obj.target_validated && (
                        <Badge variant="outline" className="text-[10px] h-5 shrink-0 text-emerald-600">
                          validated
                        </Badge>
                      )}
                      {obj.runtime_smoke_passed && (
                        <Badge variant="outline" className="text-[10px] h-5 shrink-0 text-emerald-600">
                          smoke ok
                        </Badge>
                      )}
                      {obj.manual_review_required && (
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                      )}
                    </div>
                    {obj.errors.length > 0 && (
                      <ul className="text-[11px] text-destructive space-y-0.5 pl-5 list-disc">
                        {obj.errors.map((err) => (
                          <li key={err}>{err}</li>
                        ))}
                      </ul>
                    )}
                    {obj.warnings.length > 0 && (
                      <ul className="text-[11px] text-amber-700 dark:text-amber-400 space-y-0.5 pl-5 list-disc">
                        {obj.warnings.slice(0, 4).map((warn) => (
                          <li key={warn}>{warn}</li>
                        ))}
                        {obj.warnings.length > 4 && (
                          <li className="text-muted-foreground italic">
                            +{obj.warnings.length - 4} more warning(s)
                          </li>
                        )}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground italic">
                Pending — routines migrate after table data completes (or use Migrate routines).
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
