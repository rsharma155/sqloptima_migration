"use client";

/**
 * Module: app/migrations/migrations-list-page.tsx
 * Purpose: Migration job list with:
 *   - TanStack Query for polling
 *   - TanStack Virtual for 60fps scrolling when > 50 jobs
 *   - Framer Motion layout animations for status-change reordering (≤50 items)
 *   - @container queries so the job row adapts to sidebar width
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  Search,
  ArrowUpDown,
  ArrowRight,
  Database,
  Plus,
  Loader2,
  Play,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Server,
  Table2,
  RefreshCw,
  ClipboardCheck,
  Sparkles,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { toast } from "sonner";
import { useConnections, type Connection } from "@/lib/ConnectionContext";
import {
  connectionKey,
  fetchAndSyncConnections,
  loadConnections,
} from "@/lib/connection-store";
import {
  assessDatabase,
  discoverSchema,
  listSchemas,
  preflightMigration,
  startMigration,
  testConnection,
  getMigrations,
  getMigrationSettings,
  previewProceduralMigration,
  type TableAssessment,
  type RoutineAssessment,
  type DatabaseAssessment,
  type MigrationPreflightResponse,
  type TargetTablePolicy,
  type ProceduralPreviewItem,
} from "@/lib/api";
import { TargetTableConflictDialog } from "@/components/migrations/target-table-conflict-dialog";
import { ProceduralMigrationPanel } from "@/components/migrations/procedural-migration-panel";
import {
  canStartMigrationFromAssessment,
  summarizeProceduralPreview,
  proceduralPreviewGate,
  summarizeSelectedTables,
  summarizeSelectedRoutines,
  mergeAssessmentSummaries,
  type MigrationWizardStep,
} from "@/lib/migration-readiness";
import { MigrationAssessmentReview } from "@/components/migrations/migration-assessment-review";
import {
  probeConnection,
  formatUnreachableMessage,
  type ConnectionHealth,
} from "@/lib/connection-health";
import {
  getMigrationSnapshotWarning,
  loadMigrationEnvironment,
  MIGRATION_ENV_UPDATED_EVENT,
  type MigrationEnvironment,
} from "@/lib/migration-snapshot";
import { resolveTargetSchema, type DboSchemaStrategy } from "@/lib/schema-mapping";

interface DiscoveredObject {
  name: string;
  type: string;
  schema: string;
}

interface MigrationJob {
  job_id: string;
  status: string;
  created_at: string;
  updated_at?: string;
  table_count: number;
  message?: string;
}

function formatJobTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const ACTIVE_STATUSES = ["running", "in_progress", "paused", "starting", "pending"];
const HISTORY_STATUSES = ["completed", "partial", "failed", "stopped"];

function statusIcon(status: string) {
  switch (status.toLowerCase()) {
    case "completed": return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
    case "partial":   return <AlertTriangle className="h-4 w-4 text-amber-500" />;
    case "failed":    return <XCircle className="h-4 w-4 text-destructive" />;
    case "running":
    case "in_progress": return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
    default:          return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  }
}

function statusBadgeClass(status: string): string {
  switch (status.toLowerCase()) {
    case "completed":   return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
    case "partial":     return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    case "failed":      return "bg-destructive/10 text-destructive border-destructive/20";
    case "running":
    case "in_progress": return "bg-blue-500/10 text-blue-500 border-blue-500/20";
    case "paused":      return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    default:            return "";
  }
}

// ---------------------------------------------------------------------------
// Job row — container-query aware
// ---------------------------------------------------------------------------

function JobRow({ job }: { job: MigrationJob }) {
  const completed = job.status.toLowerCase() === "completed";
  return (
    <div className="flex items-center gap-2 px-4 py-3 hover:bg-muted/50 @container">
      <Link
        href={`/migrations/${job.job_id}`}
        className="flex flex-1 items-center gap-3 min-w-0"
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/5 shrink-0">
          {statusIcon(job.status)}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono truncate">{job.job_id}</p>
          <p className="text-xs text-muted-foreground">
            {job.table_count} table{job.table_count !== 1 ? "s" : ""}
            {" · "}
            <span title={job.created_at}>{formatJobTimestamp(job.created_at)}</span>
          </p>
        </div>
        <Badge
          variant="outline"
          className={`text-[10px] shrink-0 ${statusBadgeClass(job.status)}`}
        >
          {job.status}
        </Badge>
      </Link>
      {completed && (
        <Button size="sm" variant="outline" className="shrink-0 text-xs h-8" asChild>
          <Link href={`/migrations/${job.job_id}/post-migration`}>
            <Sparkles className="h-3.5 w-3.5 mr-1" />
            Finalize
          </Link>
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Virtualised list (used when > 50 rows)
// ---------------------------------------------------------------------------

const ROW_HEIGHT = 56;

function VirtualJobList({ jobs }: { jobs: MigrationJob[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: jobs.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  return (
    <div
      ref={parentRef}
      className="overflow-y-auto divide-y"
      style={{ height: Math.min(jobs.length * ROW_HEIGHT, 480) }}
    >
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((vItem) => (
          <div
            key={vItem.key}
            data-index={vItem.index}
            ref={virtualizer.measureElement}
            style={{ position: "absolute", top: vItem.start, left: 0, right: 0 }}
          >
            <JobRow job={jobs[vItem.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Animated list (used when ≤ 50 rows)
// ---------------------------------------------------------------------------

function AnimatedJobList({ jobs }: { jobs: MigrationJob[] }) {
  const prefersReduced = useReducedMotion();
  return (
    <div className="divide-y">
      <AnimatePresence mode="popLayout" initial={false}>
        {jobs.map((job) => (
          <motion.div
            key={job.job_id}
            layout={!prefersReduced}
            initial={prefersReduced ? false : { opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={prefersReduced ? undefined : { opacity: 0, y: 6 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
          >
            <JobRow job={job} />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connection endpoint display
// ---------------------------------------------------------------------------

function connectionEndpoint(conn: Connection): string {
  return `${conn.host}:${conn.port}/${conn.database}`;
}

function ConnectionHealthBadge({ health }: { health: ConnectionHealth }) {
  if (health.status === "checking") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Checking…
      </span>
    );
  }
  if (health.status === "reachable") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (health.status === "unreachable") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-destructive">
        <XCircle className="h-3 w-3" /> Unreachable
      </span>
    );
  }
  return null;
}

function ConnectionPanel({
  label,
  icon: Icon,
  conn,
  connections,
  health,
  onChange,
}: {
  label: string;
  icon: typeof Server;
  conn: Connection | null;
  connections: Connection[];
  health: ConnectionHealth;
  onChange: (c: Connection) => void;
}) {
  return (
    <div className="rounded-lg border bg-muted/20 p-4 space-y-3 min-h-[132px] flex flex-col">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </Label>
        <ConnectionHealthBadge health={health} />
      </div>
      <select
        value={conn?.id || ""}
        onChange={(e) => {
          const c = connections.find((item) => item.id === e.target.value);
          if (c) onChange(c);
        }}
        className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
      >
        {connections.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} ({c.database} on {c.host})
          </option>
        ))}
      </select>
      {conn && (
        <div className="mt-auto space-y-0.5 text-[11px] text-muted-foreground font-mono">
          <p className="truncate" title={connectionEndpoint(conn)}>
            {connectionEndpoint(conn)}
          </p>
          <p className="truncate text-[10px] opacity-80">User: {conn.username || "—"}</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MigrationsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showNewDialog, setShowNewDialog] = useState(false);
  const [sourceConn, setSourceConn] = useState<Connection | null>(null);
  const [targetConn, setTargetConn] = useState<Connection | null>(null);
  const [schema, setSchema] = useState("dbo");
  const [targetSchema, setTargetSchema] = useState("public");
  const [dboSchemaStrategy, setDboSchemaStrategy] = useState<DboSchemaStrategy>("map_to_public");
  const [availableSchemas, setAvailableSchemas] = useState<string[]>([]);
  const [discoveredTables, setDiscoveredTables] = useState<DiscoveredObject[]>([]);
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [discovering, setDiscovering] = useState(false);
  const [assessing, setAssessing] = useState(false);
  const [tableAssessments, setTableAssessments] = useState<Record<string, TableAssessment>>({});
  const [routineAssessments, setRoutineAssessments] = useState<Record<string, RoutineAssessment>>({});
  const [databaseAssessment, setDatabaseAssessment] = useState<DatabaseAssessment | null>(null);
  const [wizardStep, setWizardStep] = useState<MigrationWizardStep>("setup");
  const [expandedAssessment, setExpandedAssessment] = useState<string | null>(null);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [migrating, setMigrating] = useState(false);
  const [viewTab, setViewTab] = useState<"active" | "history">("active");
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const [sourceHealth, setSourceHealth] = useState<ConnectionHealth>({ status: "unknown", message: "" });
  const [targetHealth, setTargetHealth] = useState<ConnectionHealth>({ status: "unknown", message: "" });
  const [sourceConnError, setSourceConnError] = useState<string | null>(null);
  const [targetConnError, setTargetConnError] = useState<string | null>(null);
  const [schemasLoading, setSchemasLoading] = useState(false);
  const [preflight, setPreflight] = useState<MigrationPreflightResponse | null>(null);
  const [showConflictDialog, setShowConflictDialog] = useState(false);
  const [tablePolicies, setTablePolicies] = useState<Record<string, TargetTablePolicy>>({});
  const [preflighting, setPreflighting] = useState(false);
  const [columnTypeOverrides, setColumnTypeOverrides] = useState<Record<string, string>>({});
  const [discoveredProceduralObjects, setDiscoveredProceduralObjects] = useState<DiscoveredObject[]>([]);
  const [selectedProcedures, setSelectedProcedures] = useState<Set<string>>(new Set());
  const [selectedFunctions, setSelectedFunctions] = useState<Set<string>>(new Set());
  const [proceduralPreviewItems, setProceduralPreviewItems] = useState<ProceduralPreviewItem[]>([]);
  const [proceduralPreviewLoading, setProceduralPreviewLoading] = useState(false);
  const [proceduralPreviewError, setProceduralPreviewError] = useState<string | null>(null);
  const wizardScrollRef = useRef<HTMLDivElement>(null);

  const { sourceConnections, targetConnections, refreshConnections } = useConnections();
  const [migrationEnv, setMigrationEnv] = useState<MigrationEnvironment>("development");
  const snapshotWarning = getMigrationSnapshotWarning(migrationEnv);

  const { data: migrationSettings } = useQuery({
    queryKey: ["migration-settings"],
    queryFn: getMigrationSettings,
    staleTime: 60_000,
  });
  const maxTablesPerJob = migrationSettings?.max_tables_per_job ?? 25;

  useEffect(() => {
    setMigrationEnv(loadMigrationEnvironment());
    const refresh = () => setMigrationEnv(loadMigrationEnvironment());
    window.addEventListener(MIGRATION_ENV_UPDATED_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(MIGRATION_ENV_UPDATED_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  useEffect(() => {
    if (sourceConn && !sourceConnections.find((c) => c.id === sourceConn.id)) setSourceConn(null);
    if (targetConn && !targetConnections.find((c) => c.id === targetConn.id)) setTargetConn(null);
  }, [sourceConnections, targetConnections, sourceConn, targetConn]);

  // TanStack Query — replaces manual useEffect + getMigrations
  const { data: migrations = [], isPending } = useQuery({
    queryKey: ["migrations"],
    queryFn: getMigrations,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });

  const resolveSyncedConnection = useCallback(
    async (conn: Connection, type: "source" | "target"): Promise<Connection> => {
      const synced = await fetchAndSyncConnections().catch(() => loadConnections());
      refreshConnections();
      const match =
        synced.find((c) => c.id === conn.id) ??
        synced.find((c) => c.type === type && connectionKey(c) === connectionKey(conn));
      return match ?? conn;
    },
    [refreshConnections],
  );

  const runSourceHealthCheck = useCallback(
    async (conn: Connection, cancelled: () => boolean) => {
      setSourceHealth({
        status: "checking",
        message: "Checking source connection…",
        host: conn.host,
        database: conn.database,
      });
      setSourceConnError(null);
      setAvailableSchemas([]);
      setSchemasLoading(true);

      const resolved = await resolveSyncedConnection(conn, "source");
      if (cancelled()) return;
      if (resolved.id !== conn.id || resolved.password !== conn.password) {
        setSourceConn(resolved);
      }

      const health = await probeConnection(
        resolved.id,
        { host: resolved.host, database: resolved.database },
        resolved,
      );
      if (cancelled()) return;
      setSourceHealth(health);

      if (health.status !== "reachable") {
        setSourceConnError(formatUnreachableMessage(`Source "${resolved.name}"`, health));
        setSchemasLoading(false);
        return;
      }

      try {
        const schemas = await listSchemas(resolved.id, resolved);
        if (cancelled()) return;
        setAvailableSchemas(schemas);
        if (schemas.length > 0 && !schemas.includes(schema)) setSchema(schemas[0]);
      } catch (err) {
        if (!cancelled()) {
          setSourceConnError(err instanceof Error ? err.message : "Failed to list source schemas");
        }
      } finally {
        if (!cancelled()) setSchemasLoading(false);
      }
    },
    [resolveSyncedConnection, schema],
  );

  const runTargetHealthCheck = useCallback(
    async (conn: Connection, cancelled: () => boolean) => {
      setTargetHealth({
        status: "checking",
        message: "Checking target connection…",
        host: conn.host,
        database: conn.database,
      });
      setTargetConnError(null);

      const resolved = await resolveSyncedConnection(conn, "target");
      if (cancelled()) return;
      if (resolved.id !== conn.id || resolved.password !== conn.password) {
        setTargetConn(resolved);
      }

      const health = await probeConnection(
        resolved.id,
        { host: resolved.host, database: resolved.database },
        resolved,
      );
      if (cancelled()) return;
      setTargetHealth(health);
      if (health.status !== "reachable") {
        setTargetConnError(formatUnreachableMessage(`Target "${resolved.name}"`, health));
      }
    },
    [resolveSyncedConnection],
  );

  useEffect(() => {
    if (!showNewDialog || !sourceConn) {
      setAvailableSchemas([]);
      setSourceHealth({ status: "unknown", message: "" });
      setSourceConnError(null);
      setSchemasLoading(false);
      return;
    }

    let cancelled = false;
    void runSourceHealthCheck(sourceConn, () => cancelled);
    return () => { cancelled = true; };
  }, [showNewDialog, sourceConn, runSourceHealthCheck]);

  useEffect(() => {
    if (!showNewDialog || !targetConn) {
      setTargetHealth({ status: "unknown", message: "" });
      setTargetConnError(null);
      return;
    }

    let cancelled = false;
    void runTargetHealthCheck(targetConn, () => cancelled);
    return () => { cancelled = true; };
  }, [showNewDialog, targetConn, runTargetHealthCheck]);

  const retryConnectionChecks = useCallback(async () => {
    if (sourceConn) await runSourceHealthCheck(sourceConn, () => false);
    if (targetConn) await runTargetHealthCheck(targetConn, () => false);
  }, [sourceConn, targetConn, runSourceHealthCheck, runTargetHealthCheck]);

  useEffect(() => {
    if (!showNewDialog) {
      setDiscoveredTables([]);
      setSelectedTables(new Set());
      setTableAssessments({});
      setRoutineAssessments({});
      setDatabaseAssessment(null);
      setWizardStep("setup");
      setExpandedAssessment(null);
      setDiscoverError(null);
      setSourceConnError(null);
      setTargetConnError(null);
      setSourceHealth({ status: "unknown", message: "" });
      setTargetHealth({ status: "unknown", message: "" });
      setColumnTypeOverrides({});
      setDiscoveredProceduralObjects([]);
      setSelectedProcedures(new Set());
      setSelectedFunctions(new Set());
      setProceduralPreviewItems([]);
      setProceduralPreviewError(null);
      setProceduralPreviewLoading(false);
    }
  }, [showNewDialog]);

  // Review step shows readiness/blockers at the top — scroll up when entering it.
  useEffect(() => {
    if (showNewDialog && wizardStep === "review") {
      wizardScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [showNewDialog, wizardStep]);

  // Default target schema: dbo → public (or preserve dbo), other schemas keep the same name
  useEffect(() => {
    setTargetSchema(resolveTargetSchema(schema || "dbo", undefined, dboSchemaStrategy));
  }, [schema, dboSchemaStrategy]);

  const applyAssessmentResult = useCallback((assessment: DatabaseAssessment) => {
    const tableByName: Record<string, TableAssessment> = {};
    for (const row of assessment.tables) {
      tableByName[row.table_name.toLowerCase()] = row;
    }
    const routineByName: Record<string, RoutineAssessment> = {};
    for (const row of assessment.routines ?? []) {
      routineByName[row.routine_name.toLowerCase()] = row;
    }
    setTableAssessments(tableByName);
    setRoutineAssessments(routineByName);
    setDatabaseAssessment(assessment);
    return assessment.blocker_count + (assessment.routine_blocker_count ?? 0);
  }, []);

  const runMigrationAssessment = useCallback(
    async (options?: { selectedTables?: string[]; quiet?: boolean }) => {
      if (!sourceConn) return null;
      const resolvedTargetSchema = resolveTargetSchema(schema || "dbo", targetSchema, dboSchemaStrategy);
      const assessment = await assessDatabase({
        connection_id: sourceConn.id,
        database: sourceConn.database,
        schema: schema || "dbo",
        target_connection_id: targetConn?.id,
        target_schema: resolvedTargetSchema,
        selected_tables: options?.selectedTables,
      });
      const totalBlockers = applyAssessmentResult(assessment);
      if (!options?.quiet) {
        if (totalBlockers > 0) {
          toast.warning(
            `${totalBlockers} object(s) have blockers — review the assessment before migrating`,
          );
        } else {
          toast.success("Assessment complete — review results before starting migration");
        }
      }
      return assessment;
    },
    [sourceConn, targetConn, schema, targetSchema, dboSchemaStrategy, applyAssessmentResult],
  );

  const handleDiscover = useCallback(async () => {
    if (!sourceConn) { toast.error("Select a source connection first"); return; }
    if (sourceHealth.status === "unreachable") {
      toast.error(sourceConnError ?? "Source database is not reachable");
      return;
    }
    setDiscovering(true);
    setAssessing(false);
    setDiscoverError(null);
    setDiscoveredTables([]);
    setSelectedTables(new Set());
    setDiscoveredProceduralObjects([]);
    setSelectedProcedures(new Set());
    setSelectedFunctions(new Set());
    setTableAssessments({});
    setRoutineAssessments({});
    setDatabaseAssessment(null);
    setWizardStep("setup");
    try {
      const result = await discoverSchema(sourceConn.id, schema || "dbo");
      const allItems = result.items as DiscoveredObject[];
      const tables = allItems.filter((o) => o.type.toLowerCase() === "table");
      const procedural = allItems.filter((o) => {
        const t = o.type.toLowerCase();
        return t === "procedure" || t === "function" || t.includes("function");
      });
      setDiscoveredTables(tables);
      setDiscoveredProceduralObjects(procedural);
      setSelectedProcedures(new Set());
      setSelectedFunctions(new Set());
      if (tables.length === 0 && procedural.length === 0) {
        setDiscoverError(
          `No tables, procedures, or functions found in schema "${schema || "dbo"}". Try a different schema name.`,
        );
      } else {
        const parts: string[] = [];
        if (tables.length > 0) parts.push(`${tables.length} table(s)`);
        if (procedural.length > 0) {
          parts.push(`${procedural.length} routine(s)`);
        }
        toast.success(`Discovered ${parts.join(" and ")} — running migration assessment…`);
        setAssessing(true);
        try {
          await runMigrationAssessment();
        } catch (assessErr) {
          toast.error(
            assessErr instanceof Error
              ? assessErr.message
              : "Assessment failed — objects listed without readiness scores",
          );
        } finally {
          setAssessing(false);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Discovery failed";
      setDiscoverError(msg);
      toast.error(msg);
    } finally {
      setDiscovering(false);
    }
  }, [sourceConn, schema, sourceHealth, sourceConnError, runMigrationAssessment]);

  const toggleTable = (name: string) => {
    setSelectedTables((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
        return next;
      }
      if (next.size >= maxTablesPerJob) {
        toast.error(
          `You can select at most ${maxTablesPerJob} tables per job. Increase the limit in Settings → Migration.`,
        );
        return prev;
      }
      next.add(name);
      return next;
    });
  };

  const handleSelectAllTables = () => {
    const names = discoveredTables.map((t) => t.name);
    if (names.length <= maxTablesPerJob) {
      setSelectedTables(new Set(names));
      return;
    }
    setSelectedTables(new Set(names.slice(0, maxTablesPerJob)));
    toast.message(
      `Selected first ${maxTablesPerJob} tables (platform limit). Adjust in Settings → Migration.`,
    );
  };

  const assessmentComplete =
    (discoveredTables.length === 0 || Object.keys(tableAssessments).length > 0) &&
    (discoveredProceduralObjects.length === 0 || Object.keys(routineAssessments).length > 0);
  const selectedRoutineCount = selectedProcedures.size + selectedFunctions.size;
  const hasMigrationSelection = selectedTables.size > 0 || selectedRoutineCount > 0;
  const discoveryComplete =
    discoveredTables.length > 0 || discoveredProceduralObjects.length > 0;

  const handleEnterReview = useCallback(async () => {
    if (selectedRoutineCount > 0 && targetConn) {
      setAssessing(true);
      try {
        await runMigrationAssessment({
          selectedTables: Array.from(selectedTables),
          quiet: true,
        });
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Routine dependency assessment failed",
        );
      } finally {
        setAssessing(false);
      }
    }
    setWizardStep("review");
  }, [selectedRoutineCount, targetConn, selectedTables, runMigrationAssessment]);

  const proceduralPreviewSummary = useMemo(
    () =>
      proceduralPreviewItems.length > 0
        ? summarizeProceduralPreview(proceduralPreviewItems)
        : null,
    [proceduralPreviewItems],
  );

  const fetchProceduralPreview = useCallback(async () => {
    if (!sourceConn || selectedRoutineCount === 0) {
      setProceduralPreviewItems([]);
      setProceduralPreviewError(null);
      return;
    }
    setProceduralPreviewLoading(true);
    setProceduralPreviewError(null);
    try {
      const resolvedTargetSchema = resolveTargetSchema(schema || "dbo", targetSchema, dboSchemaStrategy);
      const previewObjects = [
        ...Array.from(selectedProcedures).map((name) => ({
          name,
          object_type: "procedure" as const,
        })),
        ...Array.from(selectedFunctions).map((name) => ({
          name,
          object_type: "function" as const,
        })),
      ];
      const result = await previewProceduralMigration({
        source_connection_id: sourceConn.id,
        schema: schema || "dbo",
        target_schema: resolvedTargetSchema,
        objects: previewObjects,
      });
      setProceduralPreviewItems(result.items);
    } catch (err) {
      setProceduralPreviewItems([]);
      setProceduralPreviewError(err instanceof Error ? err.message : "Conversion preview failed");
    } finally {
      setProceduralPreviewLoading(false);
    }
  }, [
    sourceConn,
    schema,
    targetSchema,
    selectedRoutineCount,
    selectedProcedures,
    selectedFunctions,
  ]);

  useEffect(() => {
    if (wizardStep !== "review" || selectedRoutineCount === 0) {
      return;
    }
    void fetchProceduralPreview();
  }, [wizardStep, selectedRoutineCount, fetchProceduralPreview]);

  const selectionSummary = useMemo(() => {
    const tables = summarizeSelectedTables(selectedTables, tableAssessments, columnTypeOverrides);
    const routines = summarizeSelectedRoutines(
      selectedProcedures,
      selectedFunctions,
      routineAssessments,
    );
    return mergeAssessmentSummaries(tables, routines);
  }, [
    selectedTables,
    tableAssessments,
    columnTypeOverrides,
    selectedProcedures,
    selectedFunctions,
    routineAssessments,
  ]);

  const migrationGate = useMemo(() => {
    if (selectedTables.size > maxTablesPerJob) {
      return {
        allowed: false,
        reason: `Select at most ${maxTablesPerJob} tables per job (Settings → Migration).`,
      };
    }
    const tableGate = canStartMigrationFromAssessment(selectionSummary, {
      assessmentComplete,
      selectedTableCount: selectedTables.size,
      selectedRoutineCount,
      columnTypeOverrides,
    });
    if (!tableGate.allowed) {
      return tableGate;
    }
    return proceduralPreviewGate({
      selectedTableCount: selectedTables.size,
      selectedRoutineCount,
      loading: proceduralPreviewLoading,
      error: proceduralPreviewError,
      summary: proceduralPreviewSummary,
    });
  }, [
    selectionSummary,
    assessmentComplete,
    selectedTables.size,
    selectedRoutineCount,
    columnTypeOverrides,
    maxTablesPerJob,
    proceduralPreviewLoading,
    proceduralPreviewError,
    proceduralPreviewSummary,
  ]);

  const runMigration = useCallback(async (policies: Record<string, TargetTablePolicy>) => {
    if (!sourceConn || !targetConn) return;
    setMigrating(true);
    const resolvedTargetSchema = resolveTargetSchema(schema || "dbo", targetSchema, dboSchemaStrategy);
    try {
      const result = await startMigration({
        source_connection_id: sourceConn.id,
        target_connection_id: targetConn.id,
        tables: Array.from(selectedTables),
        schema: schema || "dbo",
        target_schema: resolvedTargetSchema,
        strategy: "chunked",
        chunk_size: 10000,
        parallel_workers: 4,
        validate_after: selectedTables.size > 0,
        require_target_snapshot:
          selectedTables.size > 0 && snapshotWarning.requireTargetSnapshot,
        table_policies: policies,
        column_type_overrides:
          Object.keys(columnTypeOverrides).length > 0 ? columnTypeOverrides : undefined,
        procedures: selectedProcedures.size > 0 ? Array.from(selectedProcedures) : undefined,
        functions: selectedFunctions.size > 0 ? Array.from(selectedFunctions) : undefined,
        migrate_procedural_after_tables: true,
      });
      toast.success(`Migration started: ${result.message}`);
      setShowConflictDialog(false);
      setShowNewDialog(false);
      setPreflight(null);
      qc.invalidateQueries({ queryKey: ["migrations"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Migration failed to start");
    } finally {
      setMigrating(false);
    }
  }, [sourceConn, targetConn, selectedTables, schema, targetSchema, snapshotWarning.requireTargetSnapshot, qc, columnTypeOverrides, selectedProcedures, selectedFunctions]);

  const handleStartMigration = useCallback(async () => {
    if (!sourceConn || !targetConn) { toast.error("Select both source and target connections"); return; }
    if (!migrationGate.allowed) {
      toast.error(migrationGate.reason ?? "Migration cannot start");
      return;
    }

    if (selectedTables.size === 0) {
      await runMigration({});
      return;
    }

    setPreflighting(true);
    const resolvedTargetSchema = resolveTargetSchema(schema || "dbo", targetSchema, dboSchemaStrategy);
    try {
      const result = await preflightMigration({
        source_connection_id: sourceConn.id,
        target_connection_id: targetConn.id,
        tables: Array.from(selectedTables),
        schema: schema || "dbo",
        target_schema: resolvedTargetSchema,
      });

      if (result.can_start_without_prompt) {
        await runMigration({});
        return;
      }

      const initialPolicies: Record<string, TargetTablePolicy> = {};
      for (const table of result.tables) {
        if (table.requires_action && table.suggested_policy) {
          initialPolicies[table.table_name] = table.suggested_policy;
        }
      }
      setTablePolicies(initialPolicies);
      setPreflight(result);
      setShowConflictDialog(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Preflight check failed");
    } finally {
      setPreflighting(false);
    }
  }, [sourceConn, targetConn, migrationGate, selectedTables, schema, targetSchema, runMigration]);

  const handleConfirmConflict = useCallback(async () => {
    await runMigration(tablePolicies);
  }, [runMigration, tablePolicies]);

  const handleTestConnections = useCallback(async () => {
    if (!sourceConn || !targetConn) { toast.error("Select both connections first"); return; }
    toast.loading("Testing connections...");
    try {
      const src = await testConnection(sourceConn.id);
      const tgt = await testConnection(targetConn.id);
      toast.dismiss();
      if (src.status === "connected" && tgt.status === "connected") {
        toast.success("Both connections are valid");
      } else {
        toast.error(`Source: ${src.message || src.status}, Target: ${tgt.message || tgt.status}`);
      }
    } catch {
      toast.dismiss();
      toast.error("Could not test connections");
    }
  }, [sourceConn, targetConn]);

  const filteredMigrations = (migrations as MigrationJob[])
    .filter((m) => {
      const statusLower = m.status.toLowerCase();
      const tabMatch = viewTab === "active"
        ? ACTIVE_STATUSES.includes(statusLower)
        : HISTORY_STATUSES.includes(statusLower);
      const searchMatch =
        !search ||
        m.job_id.toLowerCase().includes(search.toLowerCase()) ||
        m.status.toLowerCase().includes(search.toLowerCase());
      return tabMatch && searchMatch;
    })
    .sort((a, b) => {
      const ta = new Date(a.created_at).getTime();
      const tb = new Date(b.created_at).getTime();
      return sortOrder === "newest" ? tb - ta : ta - tb;
    });

  const activeCount = (migrations as MigrationJob[]).filter((m) =>
    ACTIVE_STATUSES.includes(m.status.toLowerCase()),
  ).length;
  const historyCount = (migrations as MigrationJob[]).filter((m) =>
    HISTORY_STATUSES.includes(m.status.toLowerCase()),
  ).length;

  const useVirtual = filteredMigrations.length > 50;

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Migrations</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage and monitor table, stored procedure, and function migrations
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => qc.invalidateQueries({ queryKey: ["migrations"] })}
          >
            <RefreshCw className="h-4 w-4 mr-1" /> Refresh
          </Button>
          <Button
            onClick={async () => {
              if (sourceConnections.length === 0 || targetConnections.length === 0) {
                toast.info("Configure both source and target connections in Settings first");
                return;
              }
              const synced = await fetchAndSyncConnections().catch(() => loadConnections());
              refreshConnections();
              const sources = synced.filter((c) => c.type === "source");
              const targets = synced.filter((c) => c.type === "target");
              if (!sourceConn) setSourceConn(sources[0] ?? sourceConnections[0]);
              if (!targetConn) setTargetConn(targets[0] ?? targetConnections[0]);
              setShowNewDialog(true);
            }}
          >
            <Plus className="h-4 w-4 mr-2" />
            New Migration
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by job ID or status…"
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setSortOrder((o) => (o === "newest" ? "oldest" : "newest"))}
        >
          <ArrowUpDown className="h-4 w-4 mr-2" />
          {sortOrder === "newest" ? "Newest first" : "Oldest first"}
        </Button>
      </div>

      {/* Empty state */}
      {!isPending && (migrations as MigrationJob[]).length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Database className="h-16 w-16 text-muted-foreground/30 mb-4" />
            <h2 className="text-xl font-semibold text-muted-foreground mb-2">No Migrations Yet</h2>
            <p className="text-sm text-muted-foreground/70 text-center max-w-md">
              {sourceConnections.length > 0 && targetConnections.length > 0
                ? "Click \"New Migration\" above to discover tables and start your first migration job."
                : "Add source (SQL Server) and target (PostgreSQL) connections in Settings, then return here to start a migration."}
            </p>
            {(sourceConnections.length === 0 || targetConnections.length === 0) && (
              <Button variant="default" className="mt-6" asChild>
                <a href="/settings">Configure Connections</a>
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* Initial skeleton while query loads */}
      {isPending && (
        <Card>
          <div className="divide-y">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-3">
                <Skeleton className="h-8 w-8 rounded-md" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3 w-48" />
                  <Skeleton className="h-3 w-24" />
                </div>
                <Skeleton className="h-5 w-16" />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Job list */}
      {!isPending && (migrations as MigrationJob[]).length > 0 && (
        <Card>
          <div className="px-4 pt-4 pb-2">
            <Tabs
              value={viewTab}
              onValueChange={(v) => setViewTab(v as "active" | "history")}
            >
              <TabsList className="h-8">
                <TabsTrigger value="active" className="h-7 text-xs">
                  Active ({activeCount})
                </TabsTrigger>
                <TabsTrigger value="history" className="h-7 text-xs">
                  History ({historyCount})
                </TabsTrigger>
              </TabsList>
            </Tabs>
            {viewTab === "active" && filteredMigrations.length > 0 && (
              <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
                Click a job row to open its detail page — progress, logs, validation, and post-migration steps are there.
              </p>
            )}
          </div>

          {filteredMigrations.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              {viewTab === "active" ? "No active migrations." : "No completed migrations yet."}
            </div>
          ) : useVirtual ? (
            /* TanStack Virtual — for 50+ rows: no layout animation, constant 60fps */
            <VirtualJobList jobs={filteredMigrations} />
          ) : (
            /* Framer Motion — for ≤50 rows: smooth reorder on status change */
            <AnimatedJobList jobs={filteredMigrations} />
          )}
        </Card>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* New Migration Dialog                                                */}
      {/* ------------------------------------------------------------------ */}
      <Dialog open={showNewDialog} onOpenChange={setShowNewDialog}>
        <DialogContent className="w-[min(1080px,calc(100vw-2rem))] h-[min(820px,calc(100vh-3rem))] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-4 border-b shrink-0 bg-muted/20">
            <DialogTitle>New Migration</DialogTitle>
            <DialogDescription>
              {wizardStep === "setup"
                ? "Select databases, discover tables, and choose what to migrate."
                : selectedTables.size === 0 && selectedRoutineCount > 0
                ? "Review converted PL/pgSQL and any parse errors, then start migration when ready."
                : "Review the readiness assessment, then start migration when ready."}
            </DialogDescription>
            <div className="flex items-center gap-2 pt-2">
              <Badge
                variant={wizardStep === "setup" ? "default" : "outline"}
                className="text-[10px] h-6"
              >
                1. Setup
              </Badge>
              <span className="text-muted-foreground text-xs">→</span>
              <Badge
                variant={wizardStep === "review" ? "default" : "outline"}
                className="text-[10px] h-6"
              >
                2. Assessment review
              </Badge>
            </div>
          </DialogHeader>

          <div
            ref={wizardScrollRef}
            className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-5"
          >
            {wizardStep === "review" ? (
              <MigrationAssessmentReview
                summary={selectionSummary}
                databaseAssessment={databaseAssessment}
                selectedTables={selectedTables}
                tableAssessments={tableAssessments}
                routineAssessments={routineAssessments}
                selectedProcedures={selectedProcedures}
                selectedFunctions={selectedFunctions}
                sourceSchema={schema || "dbo"}
                targetSchema={targetSchema || "public"}
                migrationBlockedReason={migrationGate.allowed ? null : migrationGate.reason}
                columnTypeOverrides={columnTypeOverrides}
                onColumnTypeOverridesChange={setColumnTypeOverrides}
                selectedRoutineCount={selectedRoutineCount}
                proceduralPreview={
                  selectedRoutineCount > 0
                    ? {
                        summary: proceduralPreviewSummary,
                        items: proceduralPreviewItems,
                        loading: proceduralPreviewLoading,
                        error: proceduralPreviewError,
                        onRetry: fetchProceduralPreview,
                      }
                    : undefined
                }
              />
            ) : (
              <>
            {(sourceConnError || targetConnError) && (
              <div className="space-y-2">
                {sourceConnError && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-start gap-2">
                    <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold">Source SQL Server unreachable</p>
                      <p>{sourceConnError}</p>
                      {sourceConn && (
                        <p className="text-xs mt-1 opacity-80 font-mono">
                          {connectionEndpoint(sourceConn)}
                        </p>
                      )}
                    </div>
                  </div>
                )}
                {targetConnError && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-start gap-2">
                    <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold">Target PostgreSQL unreachable</p>
                      <p>{targetConnError}</p>
                      {targetConn && (
                        <p className="text-xs mt-1 opacity-80 font-mono">
                          {connectionEndpoint(targetConn)}
                        </p>
                      )}
                    </div>
                  </div>
                )}
                <p className="text-xs text-muted-foreground space-y-1">
                  <span>
                    Connections are tested from the <strong>migration API server</strong> (not your browser).
                    If you use <code className="text-[10px]">localhost</code>, that means the host where the API runs
                    — start SQL Server/PostgreSQL there (e.g. <code className="text-[10px]">docker-compose up</code>).
                  </span>
                  <span className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={() => void retryConnectionChecks()}
                      disabled={
                        sourceHealth.status === "checking" || targetHealth.status === "checking"
                      }
                    >
                      <RefreshCw className="h-3 w-3 mr-1" />
                      Retry connection check
                    </Button>
                    <a href="/settings" className="underline">Update connections in Settings</a>
                  </span>
                </p>
              </div>
            )}

            {(sourceHealth.status === "checking" || targetHealth.status === "checking" || schemasLoading) &&
              !sourceConnError && !targetConnError && (
              <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Verifying database connections…
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-4 items-stretch">
              {sourceConn && (
                <ConnectionPanel
                  label="Source (SQL Server)"
                  icon={Server}
                  conn={sourceConn}
                  connections={sourceConnections}
                  health={sourceHealth}
                  onChange={(c) => {
                    setSourceConn(c);
                    setDiscoveredTables([]);
                    setDiscoverError(null);
                  }}
                />
              )}
              <div className="hidden md:flex items-center justify-center text-muted-foreground/60">
                <ArrowRight className="h-5 w-5" />
              </div>
              {targetConn && (
                <ConnectionPanel
                  label="Target (PostgreSQL)"
                  icon={Database}
                  conn={targetConn}
                  connections={targetConnections}
                  health={targetHealth}
                  onChange={setTargetConn}
                />
              )}
            </div>

            <div
              className={`rounded-lg border px-4 py-3 text-sm flex items-start gap-3 ${
                snapshotWarning.environment === "production"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-100"
                  : "border-blue-500/30 bg-blue-500/5 text-blue-900 dark:text-blue-100"
              }`}
            >
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 opacity-80" />
              <div className="space-y-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold">{snapshotWarning.title}</p>
                  <Badge
                    variant="outline"
                    className={`text-[10px] h-5 ${
                      snapshotWarning.environment === "production"
                        ? "border-amber-500/40 text-amber-700 dark:text-amber-300"
                        : "border-blue-500/40 text-blue-700 dark:text-blue-300"
                    }`}
                  >
                    {snapshotWarning.environment === "production" ? "Production" : "Development"}
                  </Badge>
                </div>
                <p className="text-xs leading-relaxed opacity-90">{snapshotWarning.message}</p>
                <p className="text-xs opacity-80">
                  Change in <a href="/settings" className="underline">Settings → API Configuration → Migration environment</a>.
                </p>
              </div>
            </div>

            <div className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-4 items-end">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Source Schema</Label>
                  {availableSchemas.length > 0 ? (
                    <select
                      value={schema}
                      onChange={(e) => setSchema(e.target.value)}
                      disabled={schemasLoading || sourceHealth.status !== "reachable"}
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    >
                      {availableSchemas.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  ) : (
                    <Input
                      value={schema}
                      onChange={(e) => setSchema(e.target.value)}
                      placeholder="dbo"
                      disabled={sourceHealth.status !== "reachable"}
                      className="h-9"
                    />
                  )}
                </div>
                <ArrowRight className="hidden md:block h-4 w-4 text-muted-foreground shrink-0 mb-2.5" />
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Target Schema</Label>
                  <Input
                    value={targetSchema}
                    onChange={(e) => setTargetSchema(e.target.value)}
                    placeholder="public"
                    disabled={targetHealth.status !== "reachable"}
                    className="h-9"
                  />
                </div>
              </div>
              {(schema || "dbo").toLowerCase() === "dbo" && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] text-muted-foreground">dbo handling:</span>
                  <Button
                    type="button"
                    variant={dboSchemaStrategy === "map_to_public" ? "default" : "outline"}
                    size="sm"
                    className="h-7 text-[10px]"
                    onClick={() => setDboSchemaStrategy("map_to_public")}
                  >
                    Map to public
                  </Button>
                  <Button
                    type="button"
                    variant={dboSchemaStrategy === "preserve_dbo" ? "default" : "outline"}
                    size="sm"
                    className="h-7 text-[10px]"
                    onClick={() => setDboSchemaStrategy("preserve_dbo")}
                  >
                    Keep dbo schema
                  </Button>
                </div>
              )}
              <p className="text-[10px] text-muted-foreground leading-tight">
                Target schemas are created automatically on PostgreSQL when missing (except{" "}
                <code className="text-[10px]">public</code>, which already exists). For{" "}
                <code className="text-[10px]">dbo</code>, choose map to{" "}
                <code className="text-[10px]">public</code> or keep{" "}
                <code className="text-[10px]">dbo</code> so schema-qualified SP references resolve.
                Other source schemas (e.g. Sales, Person) keep the same name.
              </p>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleDiscover}
                  disabled={discovering || !sourceConn || sourceHealth.status !== "reachable"}
                  className="h-9"
                >
                  {discovering
                    ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    : <RefreshCw className="h-4 w-4 mr-2" />}
                  {discovering ? "Discovering…" : "Discover Table, SP and FN"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleTestConnections}
                  disabled={!sourceConn || !targetConn}
                  className="h-9"
                >
                  Test Connections
                </Button>
              </div>
            </div>

            <div className="flex flex-col min-h-[280px] flex-1 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <Label className="text-sm">
                  {discovering
                    ? "Discovering tables…"
                    : discoveredTables.length > 0
                    ? `${discoveredTables.length} tables found — ${selectedTables.size}/${maxTablesPerJob} selected`
                    : discoverError
                    ? "Discovery failed"
                    : "Tables to migrate"}
                </Label>
                {discoveredTables.length > 0 && (
                  <div className="flex gap-2 shrink-0">
                    <Button
                      variant="ghost" size="sm" className="h-7 text-xs"
                      onClick={handleSelectAllTables}
                      disabled={discoveredTables.length === 0}
                    >
                      Select All
                    </Button>
                    <Button
                      variant="ghost" size="sm" className="h-7 text-xs"
                      onClick={() => setSelectedTables(new Set())}
                    >
                      Clear
                    </Button>
                  </div>
                )}
              </div>

              <div className="flex-1 border rounded-lg overflow-hidden bg-muted/10 min-h-[280px]">
                {(discovering || assessing) && (
                  <div className="flex flex-col items-center justify-center h-full min-h-[280px] gap-3 text-muted-foreground">
                    <Loader2 className="h-8 w-8 animate-spin" />
                    <p className="text-sm">
                      {discovering ? "Connecting and discovering tables…" : "Running migration readiness assessment…"}
                    </p>
                  </div>
                )}
                {!discovering && discoverError && (
                  <div className="flex flex-col items-center justify-center h-full min-h-[280px] gap-2 text-muted-foreground px-6 text-center">
                    <XCircle className="h-8 w-8 text-destructive/60" />
                    <p className="text-sm text-destructive">{discoverError}</p>
                    <Button variant="outline" size="sm" onClick={handleDiscover} className="mt-2">
                      <RefreshCw className="h-3.5 w-3.5 mr-1" /> Retry
                    </Button>
                  </div>
                )}
                {!discovering && !assessing && !discoverError && discoveredTables.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full min-h-[280px] gap-2 text-muted-foreground px-6 text-center">
                    <Server className="h-8 w-8 opacity-30" />
                    <p className="text-sm">
                      {sourceHealth.status !== "reachable"
                        ? "Fix the source connection above, then discover tables."
                        : <>Click <strong>Discover Table, SP and FN</strong> to load objects from the source database.</>}
                    </p>
                  </div>
                )}
                {!discovering && !assessing && discoveredTables.length > 0 && (
                  <div className="divide-y h-full max-h-[360px] overflow-y-auto">
                    {discoveredTables.map((t) => {
                      const assess = tableAssessments[t.name.toLowerCase()];
                      const tier = assess?.migration_tier;
                      const tierClass =
                        tier === "BLOCKER"
                          ? "bg-destructive/15 text-destructive border-destructive/30"
                          : tier === "WARNING"
                          ? "bg-amber-500/15 text-amber-500 border-amber-500/30"
                          : tier === "SAFE"
                          ? "bg-emerald-500/15 text-emerald-500 border-emerald-500/30"
                          : "bg-muted text-muted-foreground";
                      const isExpanded = expandedAssessment === t.name;
                      const isSelected = selectedTables.has(t.name);
                      const atSelectionLimit =
                        !isSelected && selectedTables.size >= maxTablesPerJob;
                      return (
                        <div key={t.name}>
                          <label
                            className={`flex items-center gap-3 px-4 py-2.5 hover:bg-muted/50 ${
                              atSelectionLimit ? "cursor-not-allowed opacity-60" : "cursor-pointer"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={isSelected}
                              disabled={atSelectionLimit}
                              onChange={() => toggleTable(t.name)}
                              className="h-4 w-4 rounded"
                            />
                            <Table2 className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="font-mono text-xs flex-1 truncate">{t.schema}.{t.name}</span>
                            {tier && (
                              <Badge variant="outline" className={`text-[10px] h-5 ${tierClass}`}>
                                {tier}
                              </Badge>
                            )}
                            {assess && (
                              <button
                                type="button"
                                className="text-[10px] text-blue-400 underline shrink-0"
                                onClick={(e) => {
                                  e.preventDefault();
                                  setExpandedAssessment(isExpanded ? null : t.name);
                                }}
                              >
                                {isExpanded ? "Hide" : "Details"}
                              </button>
                            )}
                          </label>
                          {isExpanded && assess && (
                            <div className="px-4 pb-3 text-[11px] text-muted-foreground space-y-1 bg-muted/20">
                              <p>~{Math.round(assess.estimated_minutes)} min · complexity {assess.complexity_score}/100 · ~{assess.row_count_estimate.toLocaleString()} rows</p>
                              {assess.blockers.length > 0 && (
                                <p className="text-red-400"><strong>Blockers:</strong> {assess.blockers.join("; ")}</p>
                              )}
                              {assess.warnings.length > 0 && (
                                <p className="text-amber-400"><strong>Warnings:</strong> {assess.warnings.join("; ")}</p>
                              )}
                              {assess.lob_columns.length > 0 && (
                                <p><strong>LOB columns:</strong> {assess.lob_columns.join(", ")}</p>
                              )}
                              {assess.prerequisites.length > 0 && (
                                <p><strong>Prerequisites:</strong> {assess.prerequisites.join("; ")}</p>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {discoveredTables.length > 0 && (
              <ProceduralMigrationPanel
                sourceConnectionId={sourceConn?.id ?? null}
                sourceSchema={schema || "dbo"}
                targetSchema={targetSchema || "public"}
                objects={discoveredProceduralObjects}
                selectedProcedures={selectedProcedures}
                selectedFunctions={selectedFunctions}
                onToggleProcedure={(name) => {
                  setSelectedProcedures((prev) => {
                    const next = new Set(prev);
                    next.has(name) ? next.delete(name) : next.add(name);
                    return next;
                  });
                }}
                onToggleFunction={(name) => {
                  setSelectedFunctions((prev) => {
                    const next = new Set(prev);
                    next.has(name) ? next.delete(name) : next.add(name);
                    return next;
                  });
                }}
                onSelectAllProcedures={() =>
                  setSelectedProcedures(
                    new Set(
                      discoveredProceduralObjects
                        .filter((o) => o.type.toLowerCase() === "procedure")
                        .map((o) => o.name),
                    ),
                  )
                }
                onClearProcedures={() => setSelectedProcedures(new Set())}
                onSelectAllFunctions={() =>
                  setSelectedFunctions(
                    new Set(
                      discoveredProceduralObjects
                        .filter((o) => o.type.toLowerCase().includes("function"))
                        .map((o) => o.name),
                    ),
                  )
                }
                onClearFunctions={() => setSelectedFunctions(new Set())}
                disabled={discovering || assessing || sourceHealth.status !== "reachable"}
              />
            )}
              </>
            )}
          </div>

          <DialogFooter className="px-6 py-4 border-t shrink-0 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-muted/20">
            <p className="text-xs text-muted-foreground min-w-0">
              {wizardStep === "review" ? (
                migrationGate.allowed
                  ? selectedTables.size > 0
                    ? `${selectedTables.size} table${selectedTables.size !== 1 ? "s" : ""} ready${
                        selectedRoutineCount > 0
                          ? ` · ${selectedRoutineCount} routine(s)`
                          : ""
                      }`
                    : `${selectedRoutineCount} routine${selectedRoutineCount !== 1 ? "s" : ""} ready (procedural-only)`
                  : migrationGate.reason
              ) : hasMigrationSelection ? (
                selectedTables.size > 0
                  ? `${selectedTables.size} table${selectedTables.size !== 1 ? "s" : ""} selected${
                      selectedRoutineCount > 0
                        ? ` · ${selectedRoutineCount} routine(s)`
                        : ""
                    }`
                  : `${selectedRoutineCount} routine${selectedRoutineCount !== 1 ? "s" : ""} selected`
              ) : discoveryComplete ? (
                "Select tables and/or routines to migrate"
              ) : (
                "Discover objects, then select tables and/or routines"
              )}
              {sourceConn && targetConn && wizardStep === "setup" && (
                <span className="hidden lg:inline">
                  {" · "}{connectionEndpoint(sourceConn)} → {connectionEndpoint(targetConn)}
                </span>
              )}
            </p>
            <div className="flex gap-2 shrink-0 justify-end">
              <Button variant="outline" onClick={() => setShowNewDialog(false)}>Cancel</Button>
              {wizardStep === "setup" ? (
                <Button
                  onClick={() => void handleEnterReview()}
                  disabled={
                    !hasMigrationSelection ||
                    (selectedTables.size > 0 && !assessmentComplete) ||
                    !discoveryComplete ||
                    discovering ||
                    assessing
                  }
                >
                  <ClipboardCheck className="h-4 w-4 mr-2" />
                  Review Assessment
                </Button>
              ) : (
                <>
                  <Button variant="outline" onClick={() => setWizardStep("setup")}>
                    Back
                  </Button>
                  <Button
                    onClick={handleStartMigration}
                    disabled={
                      migrating ||
                      preflighting ||
                      !migrationGate.allowed ||
                      sourceHealth.status !== "reachable" ||
                      targetHealth.status !== "reachable"
                    }
                    title={migrationGate.reason ?? undefined}
                  >
                    {(migrating || preflighting)
                      ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      : <Play className="h-4 w-4 mr-2" />}
                    {preflighting
                      ? "Checking target…"
                      : migrating
                      ? "Starting…"
                      : `Run Migration (${
                          selectedTables.size + selectedRoutineCount
                        })`}
                  </Button>
                </>
              )}
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <TargetTableConflictDialog
        open={showConflictDialog}
        preflight={preflight}
        policies={tablePolicies}
        onPolicyChange={(tableName, policy) =>
          setTablePolicies((prev) => ({ ...prev, [tableName]: policy }))
        }
        onCancel={() => {
          setShowConflictDialog(false);
          setPreflight(null);
        }}
        onConfirm={handleConfirmConflict}
        confirming={migrating}
      />
    </div>
  );
}
