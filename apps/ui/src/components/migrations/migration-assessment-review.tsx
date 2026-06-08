"use client";

/**
 * Pre-migration assessment report — shown before the user can start a migration job.
 */

import { AlertTriangle, Clock, ShieldCheck, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { TierBadge } from "@/components/shared/tier-badge";
import type { DatabaseAssessment, RoutineAssessment, TableAssessment } from "@/lib/api";
import type { SelectedAssessmentSummary } from "@/lib/migration-readiness";
import { ColumnTypeOverridePanel } from "@/components/migrations/column-type-override-panel";
import {
  ProceduralConversionReview,
  type ProceduralConversionReviewProps,
} from "@/components/migrations/procedural-conversion-review";

function TierHealthBar({
  safe,
  warning,
  blocker,
  total,
}: {
  safe: number;
  warning: number;
  blocker: number;
  total: number;
}) {
  const denom = total || 1;
  return (
    <div className="space-y-2">
      <div className="h-2.5 w-full rounded-full overflow-hidden flex">
        <div style={{ width: `${(safe / denom) * 100}%` }} className="bg-emerald-500" />
        <div style={{ width: `${(warning / denom) * 100}%` }} className="bg-amber-500" />
        <div style={{ width: `${(blocker / denom) * 100}%` }} className="bg-destructive" />
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>{safe} safe</span>
        <span>{warning} warning</span>
        <span>{blocker} blocker</span>
        <span className="ml-auto">{total} selected</span>
      </div>
    </div>
  );
}

function TableAssessmentRow({ assess }: { assess: TableAssessment }) {
  return (
    <div className="rounded-md border bg-card/50 px-3 py-2.5 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs truncate">
          {assess.schema_name}.{assess.table_name}
        </span>
        <TierBadge tier={assess.migration_tier} />
      </div>
      <p className="text-[11px] text-muted-foreground">
        ~{Math.round(assess.estimated_minutes)} min · complexity {assess.complexity_score}/100 · ~
        {assess.row_count_estimate.toLocaleString()} rows
      </p>
      {assess.blockers.length > 0 && (
        <ul className="text-[11px] text-red-400 space-y-0.5 list-disc pl-4">
          {assess.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {assess.warnings.length > 0 && (
        <ul className="text-[11px] text-amber-800 dark:text-amber-300 space-y-0.5 list-disc pl-4">
          {assess.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {assess.prerequisites.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          <strong>Prerequisites:</strong> {assess.prerequisites.join("; ")}
        </p>
      )}
    </div>
  );
}

function RoutineAssessmentRow({ assess }: { assess: RoutineAssessment }) {
  const kind = assess.object_type === "function" ? "FN" : "SP";
  return (
    <div className="rounded-md border bg-card/50 px-3 py-2.5 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs truncate">
          <span className="text-muted-foreground mr-1.5">{kind}</span>
          {assess.schema_name}.{assess.routine_name}
        </span>
        <TierBadge tier={assess.migration_tier} />
      </div>
      <p className="text-[11px] text-muted-foreground">
        ~{Math.round(assess.estimated_minutes)} min · complexity {assess.complexity_score}/100 ·{" "}
        {assess.conversion_difficulty} conversion
        {assess.detected_patterns.length > 0 &&
          ` · ${assess.detected_patterns.join(", ")}`}
      </p>
      {assess.blockers.length > 0 && (
        <ul className="text-[11px] text-red-400 space-y-0.5 list-disc pl-4">
          {assess.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {assess.warnings.length > 0 && (
        <ul className="text-[11px] text-amber-800 dark:text-amber-300 space-y-0.5 list-disc pl-4">
          {assess.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {(assess.table_dependencies?.length ?? 0) > 0 && (
        <ul className="text-[11px] text-muted-foreground space-y-0.5 list-disc pl-4">
          {assess.table_dependencies!.map((dep) => (
            <li key={`${dep.source_schema}.${dep.object_name}`}>
              {dep.source_schema}.{dep.object_name} → {dep.target_schema}.{dep.target_object}
              {dep.status === "missing" && (
                <span className="text-red-400"> (missing on target)</span>
              )}
              {dep.status === "included_in_job" && (
                <span className="text-emerald-400"> (included in this job)</span>
              )}
              {dep.status === "on_target" && (
                <span className="text-emerald-400"> (on target)</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export interface MigrationAssessmentReviewProps {
  summary: SelectedAssessmentSummary;
  databaseAssessment: DatabaseAssessment | null;
  selectedTables: Set<string>;
  tableAssessments: Record<string, TableAssessment>;
  routineAssessments?: Record<string, RoutineAssessment>;
  selectedProcedures?: Set<string>;
  selectedFunctions?: Set<string>;
  sourceSchema: string;
  targetSchema: string;
  migrationBlockedReason: string | null;
  columnTypeOverrides?: Record<string, string>;
  onColumnTypeOverridesChange?: (overrides: Record<string, string>) => void;
  proceduralPreview?: Pick<
    ProceduralConversionReviewProps,
    "summary" | "items" | "loading" | "error" | "onRetry"
  >;
  selectedRoutineCount?: number;
}

export function MigrationAssessmentReview({
  summary,
  databaseAssessment,
  selectedTables,
  tableAssessments,
  routineAssessments = {},
  selectedProcedures = new Set<string>(),
  selectedFunctions = new Set<string>(),
  sourceSchema,
  targetSchema,
  migrationBlockedReason,
  columnTypeOverrides = {},
  onColumnTypeOverridesChange,
  proceduralPreview,
  selectedRoutineCount = 0,
}: MigrationAssessmentReviewProps) {
  const objectCount = selectedTables.size + selectedRoutineCount;
  const selectedRows = Array.from(selectedTables)
    .map((name) => tableAssessments[name.toLowerCase()])
    .filter(Boolean) as TableAssessment[];
  const selectedRoutineRows = [
    ...Array.from(selectedProcedures).map((name) => routineAssessments[name.toLowerCase()]),
    ...Array.from(selectedFunctions).map((name) => routineAssessments[name.toLowerCase()]),
  ].filter(Boolean) as RoutineAssessment[];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Migration readiness assessment</h3>
        {objectCount > 0 && <TierBadge tier={summary.overallTier} />}
        <Badge variant="outline" className="text-[10px]">
          {sourceSchema} → {targetSchema}
        </Badge>
      </div>

      {onColumnTypeOverridesChange && selectedTables.size > 0 && (
        <ColumnTypeOverridePanel
          selectedTables={selectedTables}
          tableAssessments={tableAssessments}
          columnTypeOverrides={columnTypeOverrides}
          onChange={onColumnTypeOverridesChange}
        />
      )}

      {migrationBlockedReason && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm flex items-start gap-2">
          <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-red-400">Migration cannot start</p>
            <p className="text-red-300/90 text-xs mt-1 leading-relaxed">{migrationBlockedReason}</p>
          </div>
        </div>
      )}

      {!migrationBlockedReason && summary.warning > 0 && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm flex items-start gap-2 text-amber-900 dark:text-amber-100">
          <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-amber-800 dark:text-amber-300">Warnings on selected objects</p>
            <p className="text-xs text-amber-800/90 dark:text-amber-200/90 mt-1">
              Migration can proceed, but review warnings below — some objects may need extra steps
              or run slower than estimated.
            </p>
          </div>
        </div>
      )}

      {!migrationBlockedReason && summary.overallTier === "SAFE" && objectCount > 0 && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm flex items-start gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
          <p className="text-emerald-300/90 text-xs">
            All {objectCount} selected object{objectCount !== 1 ? "s are" : " is"} rated SAFE.
            You can start the migration when ready.
          </p>
        </div>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Selected objects summary</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <TierHealthBar
            safe={summary.safe}
            warning={summary.warning}
            blocker={summary.blocker}
            total={objectCount}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-md border p-3">
              <div className="text-2xl font-bold">{objectCount}</div>
              <div className="text-xs text-muted-foreground">Selected</div>
            </div>
            <div className="rounded-md border border-emerald-500/30 p-3">
              <div className="text-2xl font-bold text-emerald-400">{summary.safe}</div>
              <div className="text-xs text-muted-foreground">Safe</div>
            </div>
            <div className="rounded-md border border-amber-500/30 p-3">
              <div className="text-2xl font-bold text-amber-400">{summary.warning}</div>
              <div className="text-xs text-muted-foreground">Warning</div>
            </div>
            <div className="rounded-md border border-red-500/30 p-3">
              <div className="text-2xl font-bold text-red-400">{summary.blocker}</div>
              <div className="text-xs text-muted-foreground">Blocker</div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            Estimated migration time: ~{Math.max(1, Math.round(summary.estimatedMinutes))} min for
            selected objects
          </div>
        </CardContent>
      </Card>

      {databaseAssessment && databaseAssessment.global_prerequisites.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Global prerequisites</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="text-xs text-muted-foreground space-y-1 list-disc pl-4">
              {databaseAssessment.global_prerequisites.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {selectedRows.length > 0 && (
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Table details ({selectedRows.length})
        </p>
        <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
          {selectedRows
            .sort((a, b) => {
              const order = { BLOCKER: 0, WARNING: 1, SAFE: 2 };
              return order[a.migration_tier] - order[b.migration_tier];
            })
            .map((assess) => <TableAssessmentRow key={assess.table_name} assess={assess} />)}
        </div>
      </div>
      )}

      {selectedRoutineRows.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Stored procedures &amp; functions ({selectedRoutineRows.length})
          </p>
          <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
            {selectedRoutineRows
              .sort((a, b) => {
                const order = { BLOCKER: 0, WARNING: 1, SAFE: 2 };
                return order[a.migration_tier] - order[b.migration_tier];
              })
              .map((assess) => (
                <RoutineAssessmentRow
                  key={`${assess.object_type}-${assess.routine_name}`}
                  assess={assess}
                />
              ))}
          </div>
        </div>
      )}

      {selectedRows.length === 0 && selectedRoutineRows.length === 0 && (
        <p className="text-sm text-muted-foreground py-6 text-center">No objects selected.</p>
      )}

      {summary.blockerTables.length > 0 && (
        <Card className="border-red-500/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-red-400 flex items-center gap-2">
              <XCircle className="h-4 w-4" /> Critical blockers
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {summary.blockerTables.map(({ name, messages }) => (
              <div key={name} className="text-xs space-y-1">
                <p className="font-mono font-semibold text-red-300">{name}</p>
                <ul className="list-disc pl-4 text-red-400/90 space-y-0.5">
                  {messages.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </div>
            ))}
            <Progress value={100} className="h-1 opacity-0" aria-hidden />
          </CardContent>
        </Card>
      )}

      {selectedRoutineCount > 0 && proceduralPreview && (
        <ProceduralConversionReview
          summary={proceduralPreview.summary}
          items={proceduralPreview.items}
          loading={proceduralPreview.loading}
          error={proceduralPreview.error}
          sourceSchema={sourceSchema}
          targetSchema={targetSchema}
          onRetry={proceduralPreview.onRetry}
        />
      )}
    </div>
  );
}
