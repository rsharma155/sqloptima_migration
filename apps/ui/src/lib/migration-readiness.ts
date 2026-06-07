/**
 * Helpers for pre-migration readiness assessment in the Migration Center wizard.
 */

import type { DatabaseAssessment, ProceduralPreviewItem, TableAssessment } from "@/lib/api";

export type MigrationWizardStep = "setup" | "review";

export interface SelectedAssessmentSummary {
  safe: number;
  warning: number;
  blocker: number;
  estimatedMinutes: number;
  overallTier: "SAFE" | "WARNING" | "BLOCKER";
  blockerTables: Array<{ name: string; messages: string[] }>;
  warningTables: Array<{ name: string; messages: string[] }>;
  missingAssessment: string[];
  typeOverridePending: string[];
}

export function overrideKey(tableName: string, columnName: string): string {
  return `${tableName}.${columnName}`;
}

export function isUnsupportedTypeOnlyBlocker(assess: TableAssessment): boolean {
  if (assess.migration_tier !== "BLOCKER") return false;
  if (!assess.blocker_types?.length) return false;
  return assess.blockers.every((msg) => msg.includes("uses unsupported type"));
}

export function missingTypeOverrideKeys(
  assess: TableAssessment,
  columnTypeOverrides: Record<string, string>,
): string[] {
  return assess.blocker_types.filter(
    (col) => !columnTypeOverrides[overrideKey(assess.table_name, col)],
  );
}

export function listTypeOverrideColumns(
  selectedTables: Iterable<string>,
  tableAssessments: Record<string, TableAssessment>,
): Array<{ tableName: string; columnName: string; sourceType: string; overrideKey: string }> {
  const rows: Array<{ tableName: string; columnName: string; sourceType: string; overrideKey: string }> = [];
  for (const name of selectedTables) {
    const assess = tableAssessments[name.toLowerCase()];
    if (!assess || !isUnsupportedTypeOnlyBlocker(assess)) continue;
    for (const entry of assess.unsupported_type_columns ?? []) {
      rows.push({
        tableName: assess.table_name,
        columnName: entry.column_name,
        sourceType: entry.source_type,
        overrideKey: overrideKey(assess.table_name, entry.column_name),
      });
    }
    if (!assess.unsupported_type_columns?.length) {
      for (const col of assess.blocker_types) {
        rows.push({
          tableName: assess.table_name,
          columnName: col,
          sourceType: "unknown",
          overrideKey: overrideKey(assess.table_name, col),
        });
      }
    }
  }
  return rows;
}

function tableCountsAsBlocker(
  assess: TableAssessment,
  columnTypeOverrides: Record<string, string>,
): boolean {
  if (assess.migration_tier !== "BLOCKER") return false;
  if (isUnsupportedTypeOnlyBlocker(assess)) {
    return missingTypeOverrideKeys(assess, columnTypeOverrides).length > 0;
  }
  return true;
}

export interface ProceduralPreviewSummary {
  total: number;
  ready: number;
  reviewRequired: number;
  failed: number;
  failedNames: string[];
}

export function isProceduralPreviewItemFailed(item: ProceduralPreviewItem): boolean {
  const blockingErrors = item.errors.filter(
    (message) => !/manual review/i.test(message),
  );
  return (
    blockingErrors.length > 0 ||
    !item.postgres_syntax_valid ||
    (!item.success && !item.converted_sql.trim())
  );
}

export function summarizeProceduralPreview(
  items: ProceduralPreviewItem[],
): ProceduralPreviewSummary {
  let ready = 0;
  let reviewRequired = 0;
  let failed = 0;
  const failedNames: string[] = [];

  for (const item of items) {
    if (isProceduralPreviewItemFailed(item)) {
      failed += 1;
      failedNames.push(item.name);
    } else if (item.manual_review_required) {
      reviewRequired += 1;
    } else if (item.success) {
      ready += 1;
    } else {
      failed += 1;
      failedNames.push(item.name);
    }
  }

  return {
    total: items.length,
    ready,
    reviewRequired,
    failed,
    failedNames,
  };
}

export function proceduralPreviewGate(
  options: {
    selectedTableCount: number;
    selectedRoutineCount: number;
    loading: boolean;
    error: string | null;
    summary: ProceduralPreviewSummary | null;
  },
): { allowed: boolean; reason: string | null } {
  if (options.selectedRoutineCount === 0) {
    return { allowed: true, reason: null };
  }

  const proceduralOnly = options.selectedTableCount === 0;
  if (!proceduralOnly) {
    return { allowed: true, reason: null };
  }

  if (options.loading) {
    return {
      allowed: false,
      reason: "Converting selected routines — wait for the preview to finish.",
    };
  }
  if (options.error) {
    return {
      allowed: false,
      reason: `Routine conversion preview failed: ${options.error}`,
    };
  }
  if (!options.summary || options.summary.total === 0) {
    return {
      allowed: false,
      reason: "Routine conversion preview has not completed yet.",
    };
  }
  if (options.summary.failed > 0) {
    return {
      allowed: false,
      reason: `Fix conversion errors before migrating: ${options.summary.failedNames.join(", ")}`,
    };
  }
  return { allowed: true, reason: null };
}

export function summarizeSelectedTables(
  selectedTables: Iterable<string>,
  tableAssessments: Record<string, TableAssessment>,
  columnTypeOverrides: Record<string, string> = {},
): SelectedAssessmentSummary {
  let safe = 0;
  let warning = 0;
  let blocker = 0;
  let estimatedMinutes = 0;
  const blockerTables: Array<{ name: string; messages: string[] }> = [];
  const warningTables: Array<{ name: string; messages: string[] }> = [];
  const missingAssessment: string[] = [];
  const typeOverridePending: string[] = [];

  for (const name of selectedTables) {
    const assess = tableAssessments[name.toLowerCase()];
    if (!assess) {
      missingAssessment.push(name);
      continue;
    }
    estimatedMinutes += assess.estimated_minutes;
    if (tableCountsAsBlocker(assess, columnTypeOverrides)) {
      blocker += 1;
      const pending = missingTypeOverrideKeys(assess, columnTypeOverrides);
      if (pending.length > 0) {
        typeOverridePending.push(...pending);
        blockerTables.push({
          name,
          messages: [
            `Choose PostgreSQL target types for: ${pending.map((k) => k.split(".")[1]).join(", ")}`,
          ],
        });
      } else {
        blockerTables.push({
          name,
          messages: assess.blockers.length > 0 ? assess.blockers : ["Critical blocker — manual remediation required"],
        });
      }
    } else if (assess.migration_tier === "BLOCKER" && isUnsupportedTypeOnlyBlocker(assess)) {
      warning += 1;
    } else if (assess.migration_tier === "WARNING" || assess.migration_tier === "BLOCKER") {
      warning += 1;
      if (assess.warnings.length > 0) {
        warningTables.push({ name, messages: assess.warnings });
      }
    } else {
      safe += 1;
    }
  }

  const overallTier: "SAFE" | "WARNING" | "BLOCKER" =
    blocker > 0 ? "BLOCKER" : warning > 0 ? "WARNING" : "SAFE";

  return {
    safe,
    warning,
    blocker,
    estimatedMinutes,
    overallTier,
    blockerTables,
    warningTables,
    missingAssessment,
    typeOverridePending,
  };
}

export function canStartMigrationFromAssessment(
  summary: SelectedAssessmentSummary,
  options: {
    assessmentComplete: boolean;
    selectedTableCount: number;
    selectedRoutineCount: number;
    columnTypeOverrides?: Record<string, string>;
  },
): { allowed: boolean; reason: string | null } {
  if (options.selectedTableCount === 0 && options.selectedRoutineCount === 0) {
    return {
      allowed: false,
      reason: "Select at least one table or stored procedure/function to migrate.",
    };
  }
  if (options.selectedTableCount > 0 && !options.assessmentComplete) {
    return {
      allowed: false,
      reason: "Run Discover Table, SP and FN to complete the readiness assessment before migrating.",
    };
  }
  if (options.selectedTableCount === 0) {
    return { allowed: true, reason: null };
  }
  if (summary.missingAssessment.length > 0) {
    return {
      allowed: false,
      reason: `Assessment missing for: ${summary.missingAssessment.join(", ")}. Re-run discovery.`,
    };
  }
  if (summary.typeOverridePending.length > 0) {
    return {
      allowed: false,
      reason: `Choose PostgreSQL target types for unsupported columns: ${summary.typeOverridePending.join(", ")}`,
    };
  }
  if (summary.blocker > 0) {
    const names = summary.blockerTables.map((t) => t.name).join(", ");
    return {
      allowed: false,
      reason: `Migration is not possible: ${names} ${summary.blocker === 1 ? "has" : "have"} critical BLOCKER issues that would break the migration. Resolve them or deselect those tables.`,
    };
  }
  return { allowed: true, reason: null };
}

export function selectionAssessmentFromDatabase(
  databaseAssessment: DatabaseAssessment | null,
  selectedTables: Iterable<string>,
  columnTypeOverrides: Record<string, string> = {},
): SelectedAssessmentSummary {
  if (!databaseAssessment) {
    return summarizeSelectedTables(selectedTables, {}, columnTypeOverrides);
  }
  const byName: Record<string, TableAssessment> = {};
  for (const row of databaseAssessment.tables) {
    byName[row.table_name.toLowerCase()] = row;
  }
  return summarizeSelectedTables(selectedTables, byName, columnTypeOverrides);
}
