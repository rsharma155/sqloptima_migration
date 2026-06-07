"use client";

/**
 * Inline conversion preview for stored procedures / functions on the assessment review step.
 */

import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ProceduralPreviewItem } from "@/lib/api";
import type { ProceduralPreviewSummary } from "@/lib/migration-readiness";

function PreviewStatusBadge({ item }: { item: ProceduralPreviewItem }) {
  if (item.errors.length > 0 || !item.postgres_syntax_valid) {
    return (
      <Badge variant="destructive" className="text-[10px] h-5">
        Parse / conversion error
      </Badge>
    );
  }
  if (item.success && !item.manual_review_required) {
    return (
      <Badge className="text-[10px] h-5 bg-emerald-600 hover:bg-emerald-600">
        Ready
      </Badge>
    );
  }
  if (item.manual_review_required) {
    return (
      <Badge variant="outline" className="text-[10px] h-5 border-amber-500/50 text-amber-600">
        Manual review
      </Badge>
    );
  }
  return (
    <Badge variant="destructive" className="text-[10px] h-5">
      Failed
    </Badge>
  );
}

function PreviewItemCard({ item }: { item: ProceduralPreviewItem }) {
  const hasErrors = item.errors.length > 0 || !item.postgres_syntax_valid;

  return (
    <div
      className={`rounded-md border px-3 py-3 space-y-2 ${
        hasErrors ? "border-destructive/40 bg-destructive/5" : "bg-card/50"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-xs">
          {item.object_type}{" "}
          <span className="text-muted-foreground">{item.schema_name}.</span>
          {item.name}
        </p>
        <PreviewStatusBadge item={item} />
      </div>
      <p className="text-[11px] text-muted-foreground">
        Target schema: <code className="text-[10px]">{item.target_schema}</code>
      </p>
      {item.warnings.length > 0 && (
        <ul className="text-[11px] text-amber-800 dark:text-amber-300 space-y-0.5 list-disc pl-4">
          {item.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {item.errors.length > 0 && (
        <ul className="text-[11px] text-destructive space-y-0.5 list-disc pl-4">
          {item.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {!item.postgres_syntax_valid && item.errors.length === 0 && (
        <p className="text-[11px] text-destructive">
          Generated PL/pgSQL did not pass syntax validation.
        </p>
      )}
      <div className="space-y-1">
        <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Converted PL/pgSQL
        </p>
        <pre className="text-[11px] font-mono bg-muted/40 rounded p-2 overflow-x-auto whitespace-pre-wrap max-h-56 overflow-y-auto border">
          {item.converted_sql.trim() || "-- no output — conversion failed or produced empty SQL"}
        </pre>
      </div>
    </div>
  );
}

export interface ProceduralConversionReviewProps {
  summary: ProceduralPreviewSummary | null;
  items: ProceduralPreviewItem[];
  loading: boolean;
  error: string | null;
  sourceSchema: string;
  targetSchema: string;
  onRetry?: () => void;
}

export function ProceduralConversionReview({
  summary,
  items,
  loading,
  error,
  sourceSchema,
  targetSchema,
  onRetry,
}: ProceduralConversionReviewProps) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold">Routine conversion preview</h3>
          <p className="text-xs text-muted-foreground max-w-2xl">
            T-SQL → PL/pgSQL conversion for selected routines ({sourceSchema} → {targetSchema}).
            Review converted SQL and any parse errors before starting migration.
          </p>
        </div>
        {onRetry && !loading && (
          <Button variant="outline" size="sm" className="h-8 shrink-0" onClick={onRetry}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Re-run conversion
          </Button>
        )}
      </div>

      {loading && (
        <div className="flex flex-col items-center justify-center gap-3 py-10 text-muted-foreground border rounded-lg bg-muted/10">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-sm">Converting selected routines…</p>
        </div>
      )}

      {!loading && error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm flex items-start gap-2">
          <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
          <div className="space-y-2 min-w-0">
            <p className="font-semibold text-red-400">Conversion preview failed</p>
            <p className="text-xs text-red-300/90 leading-relaxed">{error}</p>
            {onRetry && (
              <Button variant="outline" size="sm" className="h-7" onClick={onRetry}>
                Retry
              </Button>
            )}
          </div>
        </div>
      )}

      {!loading && !error && summary && (
        <>
          {summary.failed > 0 && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm flex items-start gap-2">
              <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-red-400">Migration blocked — conversion errors</p>
                <p className="text-xs text-red-300/90 mt-1 leading-relaxed">
                  {summary.failed} routine{summary.failed !== 1 ? "s have" : " has"} parse or
                  conversion errors: {summary.failedNames.join(", ")}. Fix the source T-SQL or
                  deselect those routines before migrating.
                </p>
              </div>
            </div>
          )}

          {summary.failed === 0 && summary.reviewRequired > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm flex items-start gap-2 text-amber-900 dark:text-amber-100">
              <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
              <p className="text-xs text-amber-800/90 dark:text-amber-200/90">
                {summary.reviewRequired} routine{summary.reviewRequired !== 1 ? "s require" : " requires"}{" "}
                manual review — conversion succeeded but deploy may need changes on PostgreSQL.
              </p>
            </div>
          )}

          {summary.failed === 0 && summary.ready === summary.total && summary.total > 0 && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm flex items-start gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
              <p className="text-xs text-emerald-300/90">
                All {summary.ready} selected routine{summary.ready !== 1 ? "s converted" : " converted"}{" "}
                successfully. You can start migration when ready.
              </p>
            </div>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Conversion summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-md border p-3">
                  <div className="text-2xl font-bold">{summary.total}</div>
                  <div className="text-xs text-muted-foreground">Selected</div>
                </div>
                <div className="rounded-md border border-emerald-500/30 p-3">
                  <div className="text-2xl font-bold text-emerald-400">{summary.ready}</div>
                  <div className="text-xs text-muted-foreground">Ready</div>
                </div>
                <div className="rounded-md border border-amber-500/30 p-3">
                  <div className="text-2xl font-bold text-amber-400">{summary.reviewRequired}</div>
                  <div className="text-xs text-muted-foreground">Review</div>
                </div>
                <div className="rounded-md border border-red-500/30 p-3">
                  <div className="text-2xl font-bold text-red-400">{summary.failed}</div>
                  <div className="text-xs text-muted-foreground">Failed</div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Converted routines ({items.length})
            </p>
            <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
              {items.map((item) => (
                <PreviewItemCard key={`${item.object_type}-${item.name}`} item={item} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
