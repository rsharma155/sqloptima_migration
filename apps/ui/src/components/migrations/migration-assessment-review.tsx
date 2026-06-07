"use client";

/**
 * Pre-migration assessment report — shown before the user can start a migration job.
 */

import { AlertTriangle, Clock, ShieldCheck, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { TierBadge } from "@/components/shared/tier-badge";
import type { DatabaseAssessment, TableAssessment } from "@/lib/api";
import type { SelectedAssessmentSummary } from "@/lib/migration-readiness";

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
        <ul className="text-[11px] text-amber-400 space-y-0.5 list-disc pl-4">
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

export interface MigrationAssessmentReviewProps {
  summary: SelectedAssessmentSummary;
  databaseAssessment: DatabaseAssessment | null;
  selectedTables: Set<string>;
  tableAssessments: Record<string, TableAssessment>;
  sourceSchema: string;
  targetSchema: string;
  migrationBlockedReason: string | null;
}

export function MigrationAssessmentReview({
  summary,
  databaseAssessment,
  selectedTables,
  tableAssessments,
  sourceSchema,
  targetSchema,
  migrationBlockedReason,
}: MigrationAssessmentReviewProps) {
  const selectedCount = selectedTables.size;
  const selectedRows = Array.from(selectedTables)
    .map((name) => tableAssessments[name.toLowerCase()])
    .filter(Boolean) as TableAssessment[];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Migration readiness assessment</h3>
        <TierBadge tier={summary.overallTier} />
        <Badge variant="outline" className="text-[10px]">
          {sourceSchema} → {targetSchema}
        </Badge>
      </div>

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
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-amber-300">Warnings on selected tables</p>
            <p className="text-xs text-amber-200/80 mt-1">
              Migration can proceed, but review warnings below — some tables may need extra steps
              or run slower than estimated.
            </p>
          </div>
        </div>
      )}

      {!migrationBlockedReason && summary.overallTier === "SAFE" && selectedCount > 0 && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm flex items-start gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
          <p className="text-emerald-300/90 text-xs">
            All {selectedCount} selected table{selectedCount !== 1 ? "s are" : " is"} rated SAFE.
            You can start the migration when ready.
          </p>
        </div>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Selected tables summary</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <TierHealthBar
            safe={summary.safe}
            warning={summary.warning}
            blocker={summary.blocker}
            total={selectedCount}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-md border p-3">
              <div className="text-2xl font-bold">{selectedCount}</div>
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
            selected tables
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

      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Table details ({selectedRows.length})
        </p>
        <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
          {selectedRows.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">No tables selected.</p>
          ) : (
            selectedRows
              .sort((a, b) => {
                const order = { BLOCKER: 0, WARNING: 1, SAFE: 2 };
                return order[a.migration_tier] - order[b.migration_tier];
              })
              .map((assess) => <TableAssessmentRow key={assess.table_name} assess={assess} />)
          )}
        </div>
      </div>

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
    </div>
  );
}
