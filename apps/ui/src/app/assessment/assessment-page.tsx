"use client";

/**
 * Module: app/assessment/page.tsx
 * Purpose: Database migration readiness assessment page — shows SAFE/WARNING/BLOCKER
 *          tier per table and stored procedure/function, complexity scores, estimated
 *          migration time, LOB columns, CI collation issues, and global prerequisites.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  ShieldCheck,
  AlertTriangle,
  XCircle,
  Clock,
  Database,
  Loader2,
  Search,
  ChevronDown,
  ChevronUp,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { TierBadge } from "@/components/shared/tier-badge";
import { EmptyState } from "@/components/shared/empty-state";
import {
  assessDatabase,
  getConnections,
  listSchemas,
  type DatabaseAssessment,
  type TableAssessment,
  type RoutineAssessment,
  type ConnectionResponse,
} from "@/lib/api";
import { CONNECTIONS_UPDATED_EVENT } from "@/lib/connection-store";

// ---------------------------------------------------------------------------
// Tier stats bar
// ---------------------------------------------------------------------------

function assessmentObjectTotals(assessment: DatabaseAssessment) {
  const tableSafe = assessment.safe_count ?? 0;
  const tableWarning = assessment.warning_count ?? 0;
  const tableBlocker = assessment.blocker_count ?? 0;
  const routineSafe = assessment.routine_safe_count ?? 0;
  const routineWarning = assessment.routine_warning_count ?? 0;
  const routineBlocker = assessment.routine_blocker_count ?? 0;
  return {
    totalObjects: (assessment.total_tables ?? 0) + (assessment.total_routines ?? 0),
    safe: tableSafe + routineSafe,
    warning: tableWarning + routineWarning,
    blocker: tableBlocker + routineBlocker,
  };
}

function TierHealthBar({ assessment }: { assessment: DatabaseAssessment }) {
  const totals = assessmentObjectTotals(assessment);
  const total = totals.totalObjects || 1;
  const safeW = (totals.safe / total) * 100;
  const warnW = (totals.warning / total) * 100;
  const blockW = (totals.blocker / total) * 100;
  return (
    <div className="space-y-2">
      <div className="h-3 w-full rounded-full overflow-hidden flex">
        <div
          style={{ width: `${safeW}%` }}
          className="bg-emerald-500 transition-all duration-700"
          title={`Safe: ${totals.safe}`}
        />
        <div
          style={{ width: `${warnW}%` }}
          className="bg-amber-500 transition-all duration-700"
          title={`Warning: ${totals.warning}`}
        />
        <div
          style={{ width: `${blockW}%` }}
          className="bg-destructive transition-all duration-700"
          title={`Blocker: ${totals.blocker}`}
        />
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500 inline-block" />
          {totals.safe} safe
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-amber-500 inline-block" />
          {totals.warning} warning
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-destructive inline-block" />
          {totals.blocker} blocker
        </span>
        <span className="ml-auto">
          {assessment.total_tables} tables · {assessment.total_routines ?? 0} routines
        </span>
      </div>
    </div>
  );
}

function TierStats({ assessment }: { assessment: DatabaseAssessment }) {
  const totals = assessmentObjectTotals(assessment);
  const total = totals.totalObjects || 1;
  return (
    <div className="space-y-4">
      <TierHealthBar assessment={assessment} />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-3xl font-bold">{totals.totalObjects}</div>
            <div className="text-sm text-muted-foreground mt-1">Total Objects</div>
            <p className="text-[10px] text-muted-foreground mt-1">
              {assessment.total_tables} tables · {assessment.total_routines ?? 0} routines
            </p>
          </CardContent>
        </Card>
        <Card className="border-emerald-500/30">
          <CardContent className="pt-4">
            <div className="text-3xl font-bold text-emerald-400">{totals.safe}</div>
            <div className="text-sm text-muted-foreground mt-1 flex items-center gap-1">
              <ShieldCheck className="h-3.5 w-3.5" /> Safe
            </div>
            <Progress value={(totals.safe / total) * 100} className="h-1.5 mt-2 bg-muted [&>*]:bg-emerald-500" />
          </CardContent>
        </Card>
        <Card className="border-amber-500/30">
          <CardContent className="pt-4">
            <div className="text-3xl font-bold text-amber-400">{totals.warning}</div>
            <div className="text-sm text-muted-foreground mt-1 flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" /> Warning
            </div>
            <Progress value={(totals.warning / total) * 100} className="h-1.5 mt-2 bg-muted [&>*]:bg-amber-500" />
          </CardContent>
        </Card>
        <Card className="border-red-500/30">
          <CardContent className="pt-4">
            <div className="text-3xl font-bold text-red-400">{totals.blocker}</div>
            <div className="text-sm text-muted-foreground mt-1 flex items-center gap-1">
              <XCircle className="h-3.5 w-3.5" /> Blocker
            </div>
            <Progress value={(totals.blocker / total) * 100} className="h-1.5 mt-2 bg-muted [&>*]:bg-red-500" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Guidance lookup — maps known warning/blocker patterns to actionable steps
// ---------------------------------------------------------------------------

interface Guidance {
  title: string;
  steps: string[];
}

function getGuidance(text: string): Guidance | null {
  const t = text.toLowerCase();

  if (t.includes("hierarchyid")) {
    return {
      title: "How to handle hierarchyid",
      steps: [
        "hierarchyid is a SQL Server-native tree-path type with no built-in PostgreSQL equivalent.",
        "Option A — ltree (recommended): Run `CREATE EXTENSION ltree;` in PostgreSQL. Convert stored paths to dot-notation strings (e.g. '/1/2/3/' → '1.2.3') using a migration script, then change the column type to ltree. ltree supports path queries: @>, <@, ~, ?.",
        "Option B — varchar/text (simple): Cast to varchar first in SQL Server: CAST(col AS varchar(900)). You lose hierarchyid methods (GetLevel, IsDescendantOf, etc.) but the data is portable.",
        "Action required: Write a migration script to transform the stored bytes before this table can be migrated. This table must be excluded from the automated migration run.",
      ],
    };
  }

  if (t.includes("geography") || t.includes("geometry")) {
    return {
      title: "How to handle geography / geometry (spatial types)",
      steps: [
        "geography and geometry are SQL Server spatial types. PostgreSQL requires the PostGIS extension for equivalent functionality.",
        "Step 1: Install PostGIS on the target: `CREATE EXTENSION postgis;`",
        "Step 2: Map column types — GEOGRAPHY(Point) → geography(POINT, 4326), GEOMETRY(Polygon) → geometry(POLYGON, <SRID>). The exact subtype depends on your data.",
        "Step 3: Export from SQL Server using STAsText() (WKT format), import into PostgreSQL using ST_GeomFromText('…', srid).",
        "Step 4: Re-create spatial indexes: `CREATE INDEX … USING GIST(column);`",
        "Action required: Exclude this table from automated migration. Run PostGIS conversion scripts manually after the main migration.",
      ],
    };
  }

  if (t.includes("no primary key") || t.includes("primary key on")) {
    return {
      title: "How to fix a missing primary key",
      steps: [
        "The migration engine chunks data using the table's PRIMARY KEY constraint (sys.indexes.is_primary_key = 1). Tables without a PK cannot be migrated.",
        "Add a primary key on SQL Server before migrating, for example:",
        "`ALTER TABLE dbo.YourTable ADD CONSTRAINT PK_YourTable PRIMARY KEY (YourIdColumn);`",
        "If the table has no natural key, add a surrogate key: `ALTER TABLE dbo.YourTable ADD RowId BIGINT IDENTITY(1,1) NOT NULL;` then `ALTER TABLE … ADD CONSTRAINT PK_… PRIMARY KEY (RowId);`",
        "Re-run Discover / Assessment after adding the constraint — the table should move from BLOCKER to SAFE or WARNING.",
      ],
    };
  }

  if (t.includes("offset") || t.includes("identity column") || t.includes("chunk planning")) {
    return {
      title: "Why OFFSET/FETCH is slower and what to do",
      steps: [
        "Keyset pagination (fast): SELECT … WHERE id > :last_id ORDER BY id — O(1) per chunk via index seek. Requires a primary-key column.",
        "OFFSET/FETCH (slow): SELECT … ORDER BY (SELECT NULL) OFFSET :n ROWS FETCH NEXT :chunk — re-scans the table from row 1 on every chunk. Cost is O(N²) for N rows.",
        "Example impact: a 5 million-row table takes ~2 min with keyset pagination but can take 30+ min with OFFSET/FETCH.",
        "Fix A (best): Add a surrogate key to the SQL Server table — `ALTER TABLE t ADD _row_id BIGINT IDENTITY(1,1);` — run the migration, then drop the column.",
        "Fix B: If the table has a date/timestamp column (e.g. CreatedAt), configure it as the chunk key in migration settings.",
        "Fix C: Accept slower performance for small tables (<100 K rows) — OFFSET/FETCH is acceptable at that scale.",
      ],
    };
  }

  if (t.includes("computed")) {
    return {
      title: "How to handle computed columns",
      steps: [
        "SQL Server computed columns (e.g. `Salary AS BasePay * 1.1`) are not automatically portable to PostgreSQL.",
        "Option A — GENERATED ALWAYS AS … STORED (PostgreSQL 12+): Supported if the expression uses PG-compatible functions. Arithmetic (+, -, *, /) works as-is. Replace SQL Server functions: GETDATE() → NOW(), ISNULL() → COALESCE(), LEN() → LENGTH().",
        "Option B — Regular column + trigger: If the expression is complex, materialise the value as a plain column and keep it in sync with a BEFORE INSERT/UPDATE trigger.",
        "Option C — View: Expose the computed value via a view rather than storing it.",
        "Action required: Review the expression, verify it produces the same result in PostgreSQL, and update the CREATE TABLE DDL before migrating this table.",
      ],
    };
  }

  if (t.includes("case-insensitive") || t.includes("collation") || t.includes("citext")) {
    return {
      title: "How to handle case-insensitive collation",
      steps: [
        "SQL Server CI (case-insensitive) collation allows WHERE email = 'USER@EXAMPLE.COM' to match 'user@example.com'. PostgreSQL text comparisons are case-sensitive by default.",
        "Option A — citext extension (simplest): `CREATE EXTENSION citext;` then `ALTER TABLE t ALTER COLUMN email TYPE CITEXT;`. All comparisons on that column become case-insensitive automatically.",
        "Option B — lower() functional index: Keep the column as TEXT. Create `CREATE INDEX idx ON t (lower(email));` and always query with `WHERE lower(email) = lower(:input)`.",
        "Option C — ICU deterministic=false collation (PostgreSQL 12+): `CREATE COLLATION ci (provider='icu', locale='und-u-ks-level2', deterministic=false);` then `ALTER TABLE t ALTER COLUMN c TYPE TEXT COLLATE ci;`. Also makes ORDER BY case-insensitive.",
        "Recommendation: use citext for email/username columns; use lower() indexes for columns where you need case-insensitive search but want standard TEXT semantics elsewhere.",
      ],
    };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Guidance panel — expandable "What should I do?" inline below each item
// ---------------------------------------------------------------------------

function GuidancePanel({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const guidance = getGuidance(text);
  if (!guidance) return null;
  return (
    <div className="ml-4 mt-1.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[10px] text-blue-400 hover:text-blue-300 underline underline-offset-2 flex items-center gap-0.5"
      >
        <Info className="h-2.5 w-2.5" />
        {open ? "Hide guidance" : "What should I do?"}
      </button>
      {open && (
        <div className="mt-1.5 rounded-md border border-blue-500/20 bg-blue-500/5 px-3 py-2.5 space-y-1.5">
          <p className="text-[11px] font-semibold text-blue-300">{guidance.title}</p>
          {guidance.steps.map((step, i) => (
            <p key={i} className="text-[11px] text-muted-foreground leading-relaxed">
              {step}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table row with expandable details
// ---------------------------------------------------------------------------

function TableRow({ table }: { table: TableAssessment }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails =
    table.blockers.length > 0 ||
    table.warnings.length > 0 ||
    table.prerequisites.length > 0 ||
    table.lob_columns.length > 0;

  return (
    <>
      <tr className="border-b border-border hover:bg-muted/30 transition-colors">
        <td className="px-3 py-2 text-sm font-mono text-muted-foreground">
          {table.schema_name}
        </td>
        <td className="px-3 py-2 text-sm font-medium">{table.table_name}</td>
        <td className="px-3 py-2">
          <TierBadge tier={table.migration_tier} />
        </td>
        <td className="px-3 py-2 text-sm">
          <div className="flex items-center gap-2">
            <Progress
              value={table.complexity_score}
              className="h-1.5 w-16 bg-muted [&>*]:bg-primary"
            />
            <span className="text-muted-foreground">{table.complexity_score}</span>
          </div>
        </td>
        <td className="px-3 py-2 text-sm text-muted-foreground">
          {table.row_count_estimate.toLocaleString()}
        </td>
        <td className="px-3 py-2 text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {table.estimated_minutes < 1
              ? `${Math.round(table.estimated_minutes * 60)}s`
              : `${table.estimated_minutes.toFixed(1)}m`}
          </span>
        </td>
        <td className="px-3 py-2">
          {hasDetails && (
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
        </td>
      </tr>
      <tr className="border-b border-border bg-muted/10">
        <td colSpan={7} className="p-0">
          <div
            className="overflow-hidden transition-all duration-200 ease-in-out"
            style={{ maxHeight: expanded ? "800px" : "0px", opacity: expanded ? 1 : 0 }}
          >
          <div className="px-4 py-3">
            <div className="grid gap-3 text-xs">
              {table.blockers.length > 0 && (
                <div>
                  <p className="font-semibold text-red-400 mb-1">Blockers</p>
                  <ul className="space-y-1.5 text-muted-foreground">
                    {table.blockers.map((b, i) => (
                      <li key={i}>
                        <div className="flex items-start gap-1.5">
                          <XCircle className="h-3 w-3 mt-0.5 text-red-400 shrink-0" />
                          <span>{b}</span>
                        </div>
                        <GuidancePanel text={b} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {table.warnings.length > 0 && (
                <div>
                  <p className="font-semibold text-amber-400 mb-1">Warnings</p>
                  <ul className="space-y-1.5 text-muted-foreground">
                    {table.warnings.map((w, i) => (
                      <li key={i}>
                        <div className="flex items-start gap-1.5">
                          <AlertTriangle className="h-3 w-3 mt-0.5 text-amber-400 shrink-0" />
                          <span>{w}</span>
                        </div>
                        <GuidancePanel text={w} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {table.prerequisites.length > 0 && (
                <div>
                  <p className="font-semibold text-blue-400 mb-1">Prerequisites</p>
                  <ul className="space-y-0.5 text-muted-foreground">
                    {table.prerequisites.map((p, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <Info className="h-3 w-3 mt-0.5 text-blue-400 shrink-0" />
                        {p}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {table.lob_columns.length > 0 && (
                <p className="text-muted-foreground">
                  LOB columns: <span className="font-mono text-foreground">{table.lob_columns.join(", ")}</span>
                </p>
              )}
            </div>
          </div>
          </div>
        </td>
      </tr>
    </>
  );
}

function routineTypeLabel(objectType: string): string {
  return objectType === "function" ? "Function" : "Procedure";
}

function RoutineRow({ routine }: { routine: RoutineAssessment }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails =
    routine.blockers.length > 0 ||
    routine.warnings.length > 0 ||
    routine.prerequisites.length > 0 ||
    routine.detected_patterns.length > 0 ||
    (routine.table_dependencies?.length ?? 0) > 0;

  return (
    <>
      <tr className="border-b border-border hover:bg-muted/30 transition-colors">
        <td className="px-3 py-2 text-sm font-mono text-muted-foreground">
          {routine.schema_name}
        </td>
        <td className="px-3 py-2 text-sm font-medium">{routine.routine_name}</td>
        <td className="px-3 py-2">
          <Badge variant="outline" className="text-[10px] font-normal">
            {routineTypeLabel(routine.object_type)}
          </Badge>
        </td>
        <td className="px-3 py-2">
          <TierBadge tier={routine.migration_tier} />
        </td>
        <td className="px-3 py-2 text-sm">
          <div className="flex items-center gap-2">
            <Progress
              value={routine.complexity_score}
              className="h-1.5 w-16 bg-muted [&>*]:bg-primary"
            />
            <span className="text-muted-foreground">{routine.complexity_score}</span>
          </div>
        </td>
        <td className="px-3 py-2 text-sm text-muted-foreground capitalize">
          {routine.conversion_difficulty}
        </td>
        <td className="px-3 py-2 text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {routine.estimated_minutes < 1
              ? `${Math.round(routine.estimated_minutes * 60)}s`
              : `${routine.estimated_minutes.toFixed(1)}m`}
          </span>
        </td>
        <td className="px-3 py-2">
          {hasDetails && (
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
        </td>
      </tr>
      <tr className="border-b border-border bg-muted/10">
        <td colSpan={8} className="p-0">
          <div
            className="overflow-hidden transition-all duration-200 ease-in-out"
            style={{ maxHeight: expanded ? "800px" : "0px", opacity: expanded ? 1 : 0 }}
          >
            <div className="px-4 py-3">
              <div className="grid gap-3 text-xs">
                {routine.detected_patterns.length > 0 && (
                  <p className="text-muted-foreground">
                    T-SQL patterns:{" "}
                    <span className="font-mono text-foreground">
                      {routine.detected_patterns.join(", ")}
                    </span>
                  </p>
                )}
                {routine.blockers.length > 0 && (
                  <div>
                    <p className="font-semibold text-red-400 mb-1">Blockers</p>
                    <ul className="space-y-1.5 text-muted-foreground">
                      {routine.blockers.map((b, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <XCircle className="h-3 w-3 mt-0.5 text-red-400 shrink-0" />
                          <span>{b}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {routine.warnings.length > 0 && (
                  <div>
                    <p className="font-semibold text-amber-400 mb-1">Warnings</p>
                    <ul className="space-y-1.5 text-muted-foreground">
                      {routine.warnings.map((w, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <AlertTriangle className="h-3 w-3 mt-0.5 text-amber-400 shrink-0" />
                          <span>{w}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(routine.table_dependencies?.length ?? 0) > 0 && (
                  <div>
                    <p className="font-semibold text-muted-foreground mb-1">Table dependencies</p>
                    <ul className="space-y-0.5 text-muted-foreground font-mono">
                      {routine.table_dependencies!.map((dep) => (
                        <li key={`${dep.source_schema}.${dep.object_name}`}>
                          {dep.source_schema}.{dep.object_name} → {dep.target_schema}.
                          {dep.target_object}
                          {dep.status === "missing" && (
                            <span className="text-red-400"> (missing on target)</span>
                          )}
                          {dep.status === "included_in_job" && (
                            <span className="text-emerald-400"> (included in job)</span>
                          )}
                          {dep.status === "on_target" && (
                            <span className="text-emerald-400"> (on target)</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {routine.prerequisites.length > 0 && (
                  <div>
                    <p className="font-semibold text-blue-400 mb-1">Prerequisites</p>
                    <ul className="space-y-0.5 text-muted-foreground">
                      {routine.prerequisites.map((p, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <Info className="h-3 w-3 mt-0.5 text-blue-400 shrink-0" />
                          {p}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>
        </td>
      </tr>
    </>
  );
}

// ---------------------------------------------------------------------------
// Inner page (needs useSearchParams → Suspense boundary)
// ---------------------------------------------------------------------------

function AssessmentContent() {
  const searchParams = useSearchParams();
  const initConnId = searchParams.get("connectionId") ?? "";

  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [connId, setConnId] = useState(initConnId);
  const [database, setDatabase] = useState("");
  const [schema, setSchema] = useState("dbo");
  const [availableSchemas, setAvailableSchemas] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [assessment, setAssessment] = useState<DatabaseAssessment | null>(null);
  const [filter, setFilter] = useState("");
  const [tierFilter, setTierFilter] = useState<string>("ALL");
  const [objectView, setObjectView] = useState<"tables" | "routines">("tables");

  useEffect(() => {
    const loadConnections = () => {
      getConnections()
        .then((cs) => setConnections(cs.filter((c) => c.type === "source")))
        .catch(() => {});
    };
    loadConnections();
    window.addEventListener(CONNECTIONS_UPDATED_EVENT, loadConnections);
    return () => window.removeEventListener(CONNECTIONS_UPDATED_EVENT, loadConnections);
  }, []);

  useEffect(() => {
    if (connId && !connections.some((c) => c.id === connId)) {
      setConnId("");
      setAssessment(null);
    }
  }, [connections, connId]);

  useEffect(() => {
    if (!connId) { setAvailableSchemas([]); return; }
    const conn = connections.find((c) => c.id === connId);
    if (conn?.database) setDatabase(conn.database);
    listSchemas(connId)
      .then((schemas) => { setAvailableSchemas(schemas); if (schemas.length > 0 && !schemas.includes(schema)) setSchema(schemas[0]); })
      .catch(() => setAvailableSchemas([]));
  }, [connId, connections]);

  const runAssessment = async () => {
    if (!connId) { toast.error("Select a source connection"); return; }
    setLoading(true);
    setAssessment(null);
    try {
      const result = await assessDatabase({
        connection_id: connId,
        database: database || undefined,
        schema: schema || "dbo",
      });
      setAssessment(result);
      if (result.total_tables === 0 && (result.total_routines ?? 0) > 0) {
        setObjectView("routines");
      } else {
        setObjectView("tables");
      }
      const routineCount = result.total_routines ?? result.routines?.length ?? 0;
      toast.success(
        `Assessment complete — ${result.total_tables} tables, ${routineCount} routines, overall: ${result.overall_tier}`,
      );
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Assessment failed");
    } finally {
      setLoading(false);
    }
  };

  const filteredTables = assessment?.tables.filter((t) => {
    const matchesTier = tierFilter === "ALL" || t.migration_tier === tierFilter;
    const search = filter.toLowerCase();
    const matchesText =
      !search ||
      t.table_name.toLowerCase().includes(search) ||
      t.schema_name.toLowerCase().includes(search);
    return matchesTier && matchesText;
  }) ?? [];

  const filteredRoutines = assessment?.routines?.filter((r) => {
    const matchesTier = tierFilter === "ALL" || r.migration_tier === tierFilter;
    const search = filter.toLowerCase();
    const matchesText =
      !search ||
      r.routine_name.toLowerCase().includes(search) ||
      r.schema_name.toLowerCase().includes(search) ||
      r.object_type.toLowerCase().includes(search);
    return matchesTier && matchesText;
  }) ?? [];

  const totalMins = assessment?.estimated_total_minutes ?? 0;
  const estTime =
    totalMins < 60
      ? `${totalMins.toFixed(1)} min`
      : `${(totalMins / 60).toFixed(1)} hr`;

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Migration Assessment"
        description="Rate tables and stored procedures/functions SAFE / WARNING / BLOCKER and estimate migration effort"
      />

      {/* Tier explanation */}
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 space-y-1">
          <p className="text-sm font-semibold text-emerald-400 flex items-center gap-1.5">
            <ShieldCheck className="h-4 w-4" /> SAFE
          </p>
          <p className="text-xs text-muted-foreground">
            Object can be migrated directly. Tables map cleanly to PostgreSQL; routines convert with simple T-SQL patterns.
          </p>
        </div>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 space-y-1">
          <p className="text-sm font-semibold text-amber-400 flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4" /> WARNING
          </p>
          <p className="text-xs text-muted-foreground">
            Migration can proceed with review. Tables may need collation or LOB handling; routines may use patterns that need conversion review.
          </p>
        </div>
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 space-y-1">
          <p className="text-sm font-semibold text-red-400 flex items-center gap-1.5">
            <XCircle className="h-4 w-4" /> BLOCKER
          </p>
          <p className="text-xs text-muted-foreground">
            Cannot migrate automatically. Tables may have unsupported types; routines may use sp_executesql, CLR, or other extreme T-SQL constructs.
          </p>
        </div>
      </div>

      {/* Config panel */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Run Assessment</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4">
            <div className="space-y-1 md:col-span-2">
              <label className="text-xs text-muted-foreground">Source Connection</label>
              <select
                value={connId}
                onChange={(e) => setConnId(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">— select —</option>
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.host}/{c.database})
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Database (optional)</label>
              <Input
                value={database}
                onChange={(e) => setDatabase(e.target.value)}
                placeholder="uses connection default"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Schema</label>
              {availableSchemas.length > 0 ? (
                <select
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {availableSchemas.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              ) : (
                <Input
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                  placeholder="dbo"
                />
              )}
            </div>
          </div>
          <Button className="mt-3" onClick={runAssessment} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Database className="h-4 w-4 mr-1" />
            )}
            {loading ? "Assessing…" : "Run Assessment"}
          </Button>
        </CardContent>
      </Card>

      {/* Loading skeleton while assessment runs */}
      {loading && (
        <div className="space-y-4">
          <div className="space-y-2">
            <Skeleton className="h-3 w-full rounded-full" />
            <div className="flex gap-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-20" />
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Card key={i}>
                <CardContent className="pt-4 space-y-2">
                  <Skeleton className="h-9 w-16" />
                  <Skeleton className="h-4 w-20" />
                  <Skeleton className="h-1.5 w-full" />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardContent className="p-0">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-3 border-b">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-1.5 w-16" />
                  <Skeleton className="h-4 w-20" />
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Results */}
      {assessment && !loading && (
        <>
          {/* Summary stats */}
          <TierStats assessment={assessment} />

          {/* Global info */}
          <div className="flex flex-wrap gap-3 text-sm">
            <Badge variant="outline" className="gap-1 text-primary border-primary/30 bg-primary/5 font-medium">
              <Clock className="h-3 w-3" /> Est. migration time: {estTime}
            </Badge>
            <Badge variant={assessment.cdc_enabled_db ? "outline" : "destructive"} className="gap-1">
              CDC: {assessment.cdc_enabled_db ? "Enabled" : "Not enabled"}
            </Badge>
            {assessment.overall_tier !== "SAFE" && (
              <TierBadge tier={assessment.overall_tier} />
            )}
          </div>

          {/* Global prerequisites */}
          {assessment.global_prerequisites.length > 0 && (
            <Card className="border-amber-500/30 bg-amber-500/5">
              <CardHeader className="pb-1">
                <CardTitle className="text-sm text-amber-400 flex items-center gap-1">
                  <AlertTriangle className="h-4 w-4" /> Global Prerequisites
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {assessment.global_prerequisites.map((p, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <Info className="h-3 w-3 mt-0.5 text-amber-400 shrink-0" />
                      {p}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* Object list */}
          <Card>
            <CardHeader className="pb-2 space-y-3">
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={objectView === "tables" ? "default" : "outline"}
                  className="text-xs"
                  onClick={() => setObjectView("tables")}
                >
                  Tables ({assessment.total_tables})
                </Button>
                <Button
                  size="sm"
                  variant={objectView === "routines" ? "default" : "outline"}
                  className="text-xs"
                  onClick={() => setObjectView("routines")}
                >
                  Procedures &amp; Functions ({assessment.total_routines ?? assessment.routines?.length ?? 0})
                </Button>
              </div>
              <div className="flex flex-col md:flex-row gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder={
                      objectView === "tables"
                        ? "Filter tables…"
                        : "Filter procedures & functions…"
                    }
                    className="pl-8"
                  />
                </div>
                <div className="flex gap-1">
                  {["ALL", "SAFE", "WARNING", "BLOCKER"].map((tier) => (
                    <Button
                      key={tier}
                      size="sm"
                      variant={tierFilter === tier ? "default" : "outline"}
                      className="text-xs"
                      onClick={() => setTierFilter(tier)}
                    >
                      {tier}
                    </Button>
                  ))}
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                {objectView === "tables" ? (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border bg-muted/30">
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Schema</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Table</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Tier</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Score</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Rows</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Est. Time</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTables.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground text-sm">
                            No tables match your filter
                          </td>
                        </tr>
                      ) : (
                        filteredTables.map((t) => (
                          <TableRow key={`${t.schema_name}.${t.table_name}`} table={t} />
                        ))
                      )}
                    </tbody>
                  </table>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border bg-muted/30">
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Schema</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Name</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Type</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Tier</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Score</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Difficulty</th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Est. Time</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {filteredRoutines.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="px-3 py-8 text-center text-muted-foreground text-sm">
                            {(assessment.routines?.length ?? 0) === 0
                              ? "No stored procedures or functions found in this schema"
                              : "No routines match your filter"}
                          </td>
                        </tr>
                      ) : (
                        filteredRoutines.map((r) => (
                          <RoutineRow
                            key={`${r.schema_name}.${r.object_type}.${r.routine_name}`}
                            routine={r}
                          />
                        ))
                      )}
                    </tbody>
                  </table>
                )}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {!assessment && !loading && !loading && (
        <EmptyState
          icon={ShieldCheck}
          title="No assessment yet"
          description="Select a SQL Server source connection and click Run Assessment to analyse table and routine migration readiness."
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported page with Suspense for useSearchParams
// ---------------------------------------------------------------------------

export default function AssessmentPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center p-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <AssessmentContent />
    </Suspense>
  );
}
