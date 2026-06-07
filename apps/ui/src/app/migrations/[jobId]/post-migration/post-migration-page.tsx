/**
 * Module: post-migration-page.tsx
 * Purpose: Post-migration finalize dashboard — deferred schema inventory and apply controls.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  Loader2,
  Play,
  RefreshCw,
  AlertTriangle,
  XCircle,
  Database,
  Key,
  ListTree,
  Shield,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getPostMigrationStatus,
  runPostMigrationFinalize,
  type PostMigrationFinalizeOptions,
  type PostMigrationTableInventory,
  type PostMigrationTableStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function statusBadge(status: string) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "applied") {
    return <Badge className="bg-emerald-600/90">{status}</Badge>;
  }
  if (s === "partial" || s === "unsupported" || s === "skipped") {
    return <Badge variant="secondary">{status}</Badge>;
  }
  if (s === "failed") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  if (s === "in_progress") {
    return <Badge className="bg-blue-600/90">{status}</Badge>;
  }
  return <Badge variant="outline">{status}</Badge>;
}

function objectStatusIcon(status: string | undefined) {
  if (!status || status === "pending") return <Clock className="h-3.5 w-3.5 text-muted-foreground" />;
  if (status === "applied") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-3.5 w-3.5 text-destructive" />;
  if (status === "unsupported") return <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />;
  return <Clock className="h-3.5 w-3.5 text-muted-foreground" />;
}

function ObjectList({
  title,
  icon: Icon,
  items,
  category,
  applied,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  items: Array<string | { name: string; unsupported: string | null }>;
  category: string;
  applied: Record<string, Record<string, string>>;
}) {
  if (!items.length) return null;
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </p>
      <ul className="space-y-1 ml-5">
        {items.map((item) => {
          const name = typeof item === "string" ? item : item.name;
          const unsupported = typeof item === "object" ? item.unsupported : null;
          const st = applied[category]?.[name] ?? (unsupported ? "unsupported" : "pending");
          return (
            <li key={name} className="flex items-center gap-2 text-xs font-mono">
              {objectStatusIcon(st)}
              <span className="truncate">{name}</span>
              {unsupported && (
                <span className="text-[10px] text-amber-600 shrink-0">({unsupported})</span>
              )}
              <span className="text-[10px] text-muted-foreground ml-auto shrink-0">{st}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function emptyInventory(): PostMigrationTableInventory {
  return {
    identities: [],
    indexes: [],
    foreign_keys: [],
    check_constraints: [],
    defaults: [],
    triggers: [],
  };
}

function TableFinalizeCard({ table }: { table: PostMigrationTableStatus }) {
  const inv = { ...emptyInventory(), ...table.inventory };
  const applied = table.applied ?? {};
  const hasDeferred =
    inv.identities.length +
    inv.indexes.length +
    inv.foreign_keys.length +
    inv.check_constraints.length +
    inv.defaults.length +
    inv.triggers.length >
    0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-mono">
          {table.target_schema}.{table.table_name}
        </CardTitle>
        <CardDescription>
          Source: {table.source_schema}.{table.table_name}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!hasDeferred ? (
          <p className="text-sm text-muted-foreground">
            No deferred post-migration objects for this table.
          </p>
        ) : (
          <>
            <ObjectList title="Identity columns" icon={Key} items={inv.identities} category="identity" applied={applied} />
            <ObjectList title="Secondary indexes" icon={ListTree} items={inv.indexes} category="index" applied={applied} />
            <ObjectList title="Foreign keys" icon={Database} items={inv.foreign_keys} category="foreign_key" applied={applied} />
            <ObjectList title="Check constraints" icon={Shield} items={inv.check_constraints} category="check" applied={applied} />
            <ObjectList title="Column defaults" icon={Zap} items={inv.defaults} category="default" applied={applied} />
            <ObjectList title="Triggers" icon={Zap} items={inv.triggers} category="trigger" applied={applied} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function PostMigrationPage() {
  const params = useParams();
  const jobId = params.jobId as string;
  const qc = useQueryClient();

  const [options, setOptions] = useState<PostMigrationFinalizeOptions>({
    finalize_identities: true,
    finalize_indexes: true,
    finalize_foreign_keys: true,
    finalize_check_constraints: true,
    finalize_defaults: true,
    finalize_triggers: false,
    create_indexes_concurrently: false,
  });

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["post-migration", jobId],
    queryFn: () => getPostMigrationStatus(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (q) =>
      q.state.data?.finalize_status === "in_progress" ? 3000 : false,
  });

  const finalizeMutation = useMutation({
    mutationFn: () => runPostMigrationFinalize(jobId, options),
    onSuccess: (result) => {
      toast.success(`Post-migration finalize: ${result.status}`);
      qc.invalidateQueries({ queryKey: ["post-migration", jobId] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const canFinalize = ["completed", "partial"].includes(data?.migration_status?.toLowerCase() ?? "");
  const isRunning = finalizeMutation.isPending || data?.finalize_status === "in_progress";

  return (
    <div className="space-y-6 p-6 max-w-5xl mx-auto">
      <PageHeader
        title="Post-migration finalize"
        description="Apply identity columns, secondary indexes, constraints, and defaults after bulk data load."
      >
        <Button variant="outline" size="sm" asChild>
          <Link href={`/migrations/${jobId}`}>
            <ArrowLeft className="h-4 w-4 mr-1" />
            Job detail
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href="/migrations">All jobs</Link>
        </Button>
      </PageHeader>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : data ? (
        <>
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-lg">Finalize status</CardTitle>
                  <CardDescription className="mt-1">
                    Job {jobId.slice(0, 8)}… · migration {data.migration_status}
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  {statusBadge(data.finalize_status)}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetch()}
                    disabled={isFetching}
                  >
                    <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {data.last_error && (
                <p className="text-sm text-destructive flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  {data.last_error}
                </p>
              )}

              <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
                <p className="text-sm font-medium">Apply options</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {(
                    [
                      ["finalize_identities", "Identity columns + sequence sync"],
                      ["finalize_indexes", "Secondary indexes (non-PK)"],
                      ["finalize_foreign_keys", "Foreign keys (NOT VALID → validate)"],
                      ["finalize_check_constraints", "Check constraints"],
                      ["finalize_defaults", "Column defaults"],
                      ["finalize_triggers", "Triggers (manual review recommended)"],
                      ["create_indexes_concurrently", "CREATE INDEX CONCURRENTLY"],
                    ] as const
                  ).map(([key, label]) => (
                    <div key={key} className="flex items-center gap-2">
                      <input
                        id={key}
                        type="checkbox"
                        className="h-4 w-4 rounded border"
                        checked={Boolean(options[key])}
                        onChange={(e) =>
                          setOptions((o) => ({ ...o, [key]: e.target.checked }))
                        }
                      />
                      <Label htmlFor={key} className="text-xs font-normal cursor-pointer">
                        {label}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>

              <Button
                onClick={() => finalizeMutation.mutate()}
                disabled={!canFinalize || isRunning}
              >
                {isRunning ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Play className="h-4 w-4 mr-2" />
                )}
                Run post-migration finalize
              </Button>
              {!canFinalize && (
                <p className="text-xs text-muted-foreground">
                  Finalize is available after the migration job reaches completed status.
                </p>
              )}
            </CardContent>
          </Card>

          <div className="space-y-4">
            <h2 className="text-sm font-semibold">Deferred objects by table</h2>
            {data.tables.length === 0 ? (
              <p className="text-sm text-muted-foreground">No table plans found.</p>
            ) : (
              data.tables.map((t) => <TableFinalizeCard key={t.table_name} table={t} />)
            )}
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Job not found.</p>
      )}
    </div>
  );
}
