/**
 * Module: app/transfers/transfers-page.tsx
 * Purpose: Cross-Database Transfer wizard (path → tables → preflight → start)
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Loader2, Play, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformError } from "@/components/shared/platform-error";
import { useConnections, type Connection } from "@/lib/ConnectionContext";
import {
  ApiError,
  createTransfer,
  listTransfers,
  preflightTransfer,
  transferCatalogSchemas,
  transferCatalogTables,
  type TransferConstraintCatalogItem,
  type TransferJob,
  type TransferPath,
  type TransferPreflightResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const PATHS: Array<{ id: TransferPath; label: string; source: "sqlserver" | "postgres"; target: "sqlserver" | "postgres" }> = [
  { id: "mssql_to_pg", label: "SQL Server → PostgreSQL", source: "sqlserver", target: "postgres" },
  { id: "pg_to_mssql", label: "PostgreSQL → SQL Server", source: "postgres", target: "sqlserver" },
  { id: "pg_to_pg", label: "PostgreSQL → PostgreSQL", source: "postgres", target: "postgres" },
  { id: "mssql_to_mssql", label: "SQL Server → SQL Server", source: "sqlserver", target: "sqlserver" },
];

type WizardStep = "path" | "source" | "tables" | "target" | "preflight" | "constraints";

const STEPS: WizardStep[] = ["path", "source", "tables", "target", "preflight", "constraints"];

function kindLabel(kind: string): string {
  switch (kind) {
    case "foreign_key":
      return "Foreign key";
    case "check":
      return "Check";
    case "unique":
      return "Unique";
    case "primary_key":
    case "primary":
      return "Primary key";
    case "secondary":
    case "index":
      return "Index";
    case "trigger":
      return "Trigger";
    default:
      return kind;
  }
}

function engineOf(c: Connection): "sqlserver" | "postgres" {
  if (c.engine === "postgres" || c.engine === "sqlserver") return c.engine;
  return c.type === "target" ? "postgres" : "sqlserver";
}

function engineLabel(engine: "sqlserver" | "postgres"): string {
  return engine === "sqlserver" ? "SQL Server" : "PostgreSQL";
}

function statusVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "completed") return "default";
  if (status === "failed" || status === "stopped" || status === "restore_failed") return "destructive";
  if (status === "running" || status === "queued" || status === "preparing") return "secondary";
  return "outline";
}

export default function TransfersPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { connections } = useConnections();
  const [step, setStep] = useState<WizardStep>("path");
  const [path, setPath] = useState<TransferPath>("pg_to_pg");
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [sourceSchema, setSourceSchema] = useState("");
  const [targetSchema, setTargetSchema] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [chunkSize, setChunkSize] = useState(10000);
  const [createIfMissing, setCreateIfMissing] = useState(false);
  const [cloneObjects, setCloneObjects] = useState(false);
  const [preflight, setPreflight] = useState<TransferPreflightResponse | null>(null);
  const [reviewedConstraints, setReviewedConstraints] = useState(false);
  const [disabledKeys, setDisabledKeys] = useState<Set<string>>(new Set());
  const [onStop, setOnStop] = useState<"restore_now" | "leave_disabled">("restore_now");

  const spec = PATHS.find((p) => p.id === path)!;
  const sourceConns = connections.filter((c) => engineOf(c) === spec.source);
  const targetConns = connections.filter((c) => engineOf(c) === spec.target);

  const jobsQuery = useQuery({
    queryKey: ["transfers"],
    queryFn: listTransfers,
    refetchInterval: 5000,
  });

  const schemasQuery = useQuery({
    queryKey: ["transfer-schemas", sourceId],
    queryFn: () => transferCatalogSchemas(sourceId),
    enabled: Boolean(sourceId) && (step === "tables" || step === "source"),
  });

  const tablesQuery = useQuery({
    queryKey: ["transfer-tables", sourceId, sourceSchema],
    queryFn: () => transferCatalogTables(sourceId, sourceSchema),
    enabled: Boolean(sourceId && sourceSchema),
  });

  const targetSchemasQuery = useQuery({
    queryKey: ["transfer-target-schemas", targetId],
    queryFn: () => transferCatalogSchemas(targetId),
    enabled: Boolean(targetId) && (step === "target" || step === "preflight" || step === "constraints"),
  });

  const mappings = useMemo(() => {
    const tgtSchema = targetSchema || sourceSchema;
    return Array.from(selected).map((name) => ({
      source_schema: sourceSchema,
      source_table: name,
      target_schema: tgtSchema,
      target_table: name,
    }));
  }, [selected, sourceSchema, targetSchema]);

  const preflightMutation = useMutation({
    mutationFn: () =>
      preflightTransfer({
        path,
        source_connection_id: sourceId,
        target_connection_id: targetId,
        tables: mappings,
        create_if_missing: createIfMissing,
        clone_objects: cloneObjects,
      }),
    onSuccess: (data) => {
      setPreflight(data);
      setReviewedConstraints(false);
      setDisabledKeys(new Set());
      setStep("preflight");
    },
    onError: (err: Error) => toast.error(err instanceof ApiError ? err.message : err.message),
  });

  const catalog: TransferConstraintCatalogItem[] = useMemo(
    () => preflight?.target_constraints || [],
    [preflight],
  );

  const startMutation = useMutation({
    mutationFn: () =>
      createTransfer({
        path,
        source_connection_id: sourceId,
        target_connection_id: targetId,
        tables: mappings,
        create_if_missing: createIfMissing,
        clone_objects: cloneObjects,
        chunk_size: chunkSize,
        constraint_plan: {
          operator_reviewed: true,
          on_stop: onStop,
          items: catalog.map((item) => ({
            key: item.key,
            action: disabledKeys.has(item.key) ? "disable" : "keep",
          })),
        },
      }),
    onSuccess: (job) => {
      toast.success("Transfer queued");
      qc.invalidateQueries({ queryKey: ["transfers"] });
      router.push(`/transfers/${job.job_id}`);
    },
    onError: (err: Error) => toast.error(err instanceof ApiError ? err.message : err.message),
  });

  const canNextFromSource = Boolean(sourceId);
  const canNextFromTables = selected.size > 0 && Boolean(sourceSchema);
  const canNextFromTarget = Boolean(targetId) && targetId !== sourceId;

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Transfer"
        description="Bulk copy rows between two databases. The path you pick below sets the source and target engines (SQL Server vs PostgreSQL)."
      >
        <Button variant="outline" size="sm" onClick={() => jobsQuery.refetch()}>
          <RefreshCw className="h-4 w-4 mr-1" /> Refresh
        </Button>
      </PageHeader>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">New transfer</CardTitle>
          <CardDescription>
            Step {STEPS.indexOf(step) + 1} of {STEPS.length}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {step === "path" && (
            <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              {PATHS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setPath(p.id);
                    setSourceId("");
                    setTargetId("");
                    setSelected(new Set());
                    setPreflight(null);
                    setReviewedConstraints(false);
                    setDisabledKeys(new Set());
                    if (p.id !== "mssql_to_mssql") setCloneObjects(false);
                    if (p.id === "pg_to_mssql") setCreateIfMissing(false);
                  }}
                  className={cn(
                    "rounded-md border p-3 text-left text-sm",
                    path === p.id ? "border-primary bg-primary/5" : "border-input",
                  )}
                >
                  <div className="font-medium">{p.label}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    Source engine: {engineLabel(p.source)} · Target engine: {engineLabel(p.target)}
                  </div>
                </button>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              Pick the engine pair first. Transfer lists connections by Settings → Engine, not by the
              Migrations Source/Target role.
            </p>
            </div>
          )}

          {step === "source" && (
            <div className="space-y-3">
              <Label>Source connection ({engineLabel(spec.source)})</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
              >
                <option value="">Select source…</option>
                {sourceConns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} — {c.host}:{c.port}/{c.database}
                  </option>
                ))}
              </select>
              {sourceConns.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No {engineLabel(spec.source)} connections. In Settings, add a connection and set Engine to {engineLabel(spec.source)}. The Migrations Source/Target role is ignored here.
                </p>
              )}
            </div>
          )}

          {step === "tables" && (
            <div className="space-y-3">
              <Label>Source schema</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={sourceSchema}
                onChange={(e) => {
                  setSourceSchema(e.target.value);
                  setSelected(new Set());
                }}
              >
                <option value="">Select schema…</option>
                {(schemasQuery.data || []).map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              {tablesQuery.isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              <div className="max-h-64 overflow-auto rounded-md border divide-y">
                {(tablesQuery.data || []).map((t) => {
                  const checked = selected.has(t.table);
                  return (
                    <label key={t.table} className="flex items-center gap-2 px-3 py-2 text-sm">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          const next = new Set(selected);
                          if (checked) next.delete(t.table);
                          else next.add(t.table);
                          setSelected(next);
                        }}
                      />
                      <span className="font-mono">{t.table}</span>
                      <span className="text-muted-foreground ml-auto">{t.row_count_estimate.toLocaleString()} rows</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {step === "target" && (
            <div className="space-y-3">
              <Label>Target connection ({engineLabel(spec.target)})</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
              >
                <option value="">Select target…</option>
                {targetConns.map((c) => (
                  <option key={c.id} value={c.id} disabled={c.id === sourceId}>
                    {c.name} — {c.host}:{c.port}/{c.database}
                  </option>
                ))}
              </select>
              <Label>Target schema</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={targetSchema}
                onChange={(e) => setTargetSchema(e.target.value)}
              >
                <option value="">{sourceSchema || "Same as source"}</option>
                {(targetSchemasQuery.data || []).map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <Label>Chunk size</Label>
              <Input type="number" min={100} value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} />
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={createIfMissing}
                  disabled={path === "pg_to_mssql"}
                  onChange={(e) => setCreateIfMissing(e.target.checked)}
                />
                <span>
                  Create missing destination tables before copy
                  {path === "mssql_to_mssql" ? " (T-SQL CREATE TABLE as-is)" : path === "mssql_to_pg" ? " (mapped PostgreSQL types)" : path === "pg_to_pg" ? " (PostgreSQL CREATE TABLE)" : " (not available for PostgreSQL → SQL Server yet)"}
                </span>
              </label>
              {path === "mssql_to_mssql" && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={cloneObjects}
                    onChange={(e) => setCloneObjects(e.target.checked)}
                  />
                  <span>
                    Clone schema objects T-SQL as-is after the load (indexes, checks, foreign keys, triggers, views, functions, procedures)
                  </span>
                </label>
              )}
            </div>
          )}

          {step === "constraints" && preflight && (
            <div className="space-y-4">
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
                These objects are on the <strong>destination</strong> (
                {preflight.target.host}:{preflight.target.port}/{preflight.target.database}
                ). Nothing is disabled until you review this list and start the transfer.
              </div>
              {catalog.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No destination constraints, indexes, foreign keys, or triggers were found on the selected tables.
                </p>
              ) : (
                <div className="max-h-80 overflow-auto rounded-md border text-sm divide-y">
                  {catalog.map((item) => {
                    const keepOnly = !item.allowed_actions.includes("disable");
                    const checked = disabledKeys.has(item.key);
                    return (
                      <label key={item.key} className="flex items-start gap-2 px-3 py-2">
                        <input
                          type="checkbox"
                          className="mt-1"
                          disabled={keepOnly}
                          checked={checked}
                          onChange={() => {
                            const next = new Set(disabledKeys);
                            if (checked) next.delete(item.key);
                            else next.add(item.key);
                            setDisabledKeys(next);
                            setReviewedConstraints(false);
                          }}
                        />
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono">{item.schema}.{item.table}</span>
                            <Badge variant="outline">{kindLabel(item.kind)}</Badge>
                            <span className="font-mono text-xs">{item.object_id}</span>
                            {keepOnly && <Badge variant="secondary">Must keep</Badge>}
                            {!keepOnly && item.recommended_action === "disable" && (
                              <Badge variant="secondary">Recommended disable</Badge>
                            )}
                          </div>
                          <div className="text-muted-foreground">
                            {item.reason || (keepOnly ? "Primary keys stay enabled during load" : "Leave unchecked to keep this object enabled")}
                            {item.referenced ? ` · references ${item.referenced}` : ""}
                          </div>
                          {item.definition && (
                            <pre className="mt-1 whitespace-pre-wrap break-all text-xs text-muted-foreground">{item.definition}</pre>
                          )}
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={catalog.every((i) => !i.allowed_actions.includes("disable") || i.recommended_action !== "disable")}
                  onClick={() => {
                    setDisabledKeys(new Set(
                      catalog.filter((i) => i.allowed_actions.includes("disable") && i.recommended_action === "disable").map((i) => i.key),
                    ));
                    setReviewedConstraints(false);
                  }}
                >
                  Select recommended disables
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setDisabledKeys(new Set());
                    setReviewedConstraints(false);
                  }}
                >
                  Keep all enabled
                </Button>
              </div>
              <div className="space-y-2">
                <Label>If the transfer is stopped</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={onStop}
                  onChange={(e) => setOnStop(e.target.value as "restore_now" | "leave_disabled")}
                >
                  <option value="restore_now">Restore destination constraints immediately</option>
                  <option value="leave_disabled">Leave selected objects disabled (restore later)</option>
                </select>
              </div>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={reviewedConstraints}
                  onChange={(e) => setReviewedConstraints(e.target.checked)}
                />
                <span>
                  I have reviewed the destination constraints. Disable only the objects I checked;
                  keep everything else enabled during the load.
                </span>
              </label>
              {disabledKeys.size > 0 && (
                <p className="text-sm text-amber-700 dark:text-amber-400">
                  {disabledKeys.size} destination object(s) will be disabled for the load, then restored after copy
                  {onStop === "leave_disabled" ? " unless the job is stopped" : ""}.
                </p>
              )}
            </div>
          )}

          {step === "preflight" && preflight && (
            <div className="space-y-3">
              <div className="flex gap-2">
                <Badge variant={preflight.can_start ? "default" : "destructive"}>
                  {preflight.can_start ? "Ready" : "Blocked"}
                </Badge>
                {preflight.same_server && <Badge variant="secondary">Same server</Badge>}
                <span className="text-sm text-muted-foreground">
                  {preflight.summary.blockers} blockers · {preflight.summary.warnings} warnings
                </span>
              </div>
              {preflight.job_conflicts.map((c) => (
                <p key={c.job_id} className="text-sm text-destructive">{c.message}</p>
              ))}
              <div className="max-h-72 overflow-auto rounded-md border text-sm">
                {preflight.tables.map((t) => (
                  <div key={`${t.source.schema}.${t.source.table}`} className="border-b px-3 py-2">
                    <div className="font-mono">
                      {t.source.schema}.{t.source.table} → {t.target.schema}.{t.target.table}
                    </div>
                    <div className="text-muted-foreground">
                      {t.existence} · {t.row_count_source.toLocaleString()} source rows ·{" "}
                      {t.columns.type_mismatches.length} type issues · {t.foreign_keys.length} FKs
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">
                Next: review destination constraints. The engine will not disable anything until you confirm that list.
              </p>
            </div>
          )}

          <div className="flex justify-between pt-2">
            <Button
              variant="outline"
              disabled={step === "path"}
              onClick={() => {
                setStep(STEPS[Math.max(0, STEPS.indexOf(step) - 1)]);
              }}
            >
              Back
            </Button>
            {step === "constraints" ? (
              <Button
                disabled={!preflight?.can_start || !reviewedConstraints || startMutation.isPending}
                onClick={() => startMutation.mutate()}
              >
                {startMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
                Start transfer
              </Button>
            ) : (
              <Button
                disabled={
                  (step === "source" && !canNextFromSource) ||
                  (step === "tables" && !canNextFromTables) ||
                  (step === "target" && !canNextFromTarget) ||
                  (step === "preflight" && !preflight?.can_start) ||
                  preflightMutation.isPending
                }
                onClick={() => {
                  if (step === "path") setStep("source");
                  else if (step === "source") {
                    const first = schemasQuery.data?.[0];
                    if (first) setSourceSchema(first);
                    setStep("tables");
                  } else if (step === "tables") setStep("target");
                  else if (step === "preflight") setStep("constraints");
                  else preflightMutation.mutate();
                }}
              >
                {preflightMutation.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                {step === "target" ? "Run preflight" : step === "preflight" ? "Review destination constraints" : "Next"}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Jobs</CardTitle>
        </CardHeader>
        <CardContent>
          {jobsQuery.isError && <PlatformError error={jobsQuery.error} />}
          <div className="space-y-2">
            {(jobsQuery.data || []).map((job: TransferJob) => (
              <Link
                key={job.job_id}
                href={`/transfers/${job.job_id}`}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-sm hover:bg-muted/50"
              >
                <div className="flex items-center gap-2">
                  <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />
                  <span className="font-mono">{job.path}</span>
                  <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
                </div>
                <span className="text-muted-foreground">
                  {job.rows_copied.toLocaleString()} / {job.rows_total.toLocaleString()} rows · {job.overall_percentage}%
                </span>
              </Link>
            ))}
            {jobsQuery.data?.length === 0 && (
              <p className="text-sm text-muted-foreground">No transfer jobs yet.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
