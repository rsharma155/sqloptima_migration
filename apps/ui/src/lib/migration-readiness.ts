/**
 * Helpers for pre-migration readiness assessment in the Migration Center wizard.
 */

import type { DatabaseAssessment, TableAssessment } from "@/lib/api";

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
}

export function summarizeSelectedTables(
  selectedTables: Iterable<string>,
  tableAssessments: Record<string, TableAssessment>,
): SelectedAssessmentSummary {
  let safe = 0;
  let warning = 0;
  let blocker = 0;
  let estimatedMinutes = 0;
  const blockerTables: Array<{ name: string; messages: string[] }> = [];
  const warningTables: Array<{ name: string; messages: string[] }> = [];
  const missingAssessment: string[] = [];

  for (const name of selectedTables) {
    const assess = tableAssessments[name.toLowerCase()];
    if (!assess) {
      missingAssessment.push(name);
      continue;
    }
    estimatedMinutes += assess.estimated_minutes;
    if (assess.migration_tier === "BLOCKER") {
      blocker += 1;
      blockerTables.push({
        name,
        messages: assess.blockers.length > 0 ? assess.blockers : ["Critical blocker — manual remediation required"],
      });
    } else if (assess.migration_tier === "WARNING") {
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
  };
}

export function canStartMigrationFromAssessment(
  summary: SelectedAssessmentSummary,
  options: { assessmentComplete: boolean; selectedCount: number },
): { allowed: boolean; reason: string | null } {
  if (options.selectedCount === 0) {
    return { allowed: false, reason: "Select at least one table to migrate." };
  }
  if (!options.assessmentComplete) {
    return {
      allowed: false,
      reason: "Run Discover Tables to complete the readiness assessment before migrating.",
    };
  }
  if (summary.missingAssessment.length > 0) {
    return {
      allowed: false,
      reason: `Assessment missing for: ${summary.missingAssessment.join(", ")}. Re-run discovery.`,
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
): SelectedAssessmentSummary {
  if (!databaseAssessment) {
    return summarizeSelectedTables(selectedTables, {});
  }
  const byName: Record<string, TableAssessment> = {};
  for (const row of databaseAssessment.tables) {
    byName[row.table_name.toLowerCase()] = row;
  }
  return summarizeSelectedTables(selectedTables, byName);
}
