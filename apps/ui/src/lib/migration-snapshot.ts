/**
 * Target snapshot policy for migration jobs (dev vs production).
 */
export type MigrationEnvironment = "development" | "production";

export const MIGRATION_ENV_STORAGE_KEY = "migration_environment";
export const MIGRATION_ENV_UPDATED_EVENT = "migration-environment-updated";

export interface MigrationSnapshotWarning {
  environment: MigrationEnvironment;
  title: string;
  message: string;
  requireTargetSnapshot: boolean;
}

function resolveFromBuildConfig(): MigrationEnvironment {
  const explicit = process.env.NEXT_PUBLIC_MIGRATION_ENV?.toLowerCase();
  if (explicit === "production" || explicit === "prod") return "production";
  if (explicit === "development" || explicit === "dev") return "development";
  return process.env.NODE_ENV === "production" ? "production" : "development";
}

function readStoredEnvironment(): MigrationEnvironment | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = localStorage.getItem(MIGRATION_ENV_STORAGE_KEY);
    if (stored === "production" || stored === "development") return stored;
  } catch {
    return null;
  }
  return null;
}

/** User-selected environment (Settings) with build-time default fallback. */
export function loadMigrationEnvironment(): MigrationEnvironment {
  return readStoredEnvironment() ?? resolveFromBuildConfig();
}

export function saveMigrationEnvironment(env: MigrationEnvironment): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(MIGRATION_ENV_STORAGE_KEY, env);
    window.dispatchEvent(new CustomEvent(MIGRATION_ENV_UPDATED_EVENT));
  } catch {
    // Ignore when localStorage is unavailable (SSR/tests).
  }
}

/** @deprecated Use loadMigrationEnvironment — kept for existing imports. */
export function getMigrationEnvironment(): MigrationEnvironment {
  return loadMigrationEnvironment();
}

export function requireTargetSnapshotForEnv(
  env: MigrationEnvironment = loadMigrationEnvironment(),
): boolean {
  return env === "production";
}

export function getMigrationSnapshotWarning(
  env: MigrationEnvironment = loadMigrationEnvironment(),
): MigrationSnapshotWarning {
  const requireTargetSnapshot = requireTargetSnapshotForEnv(env);

  if (env === "production") {
    return {
      environment: env,
      requireTargetSnapshot,
      title: "Production — target snapshot required",
      message:
        "A verified PostgreSQL backup is required before migration starts. " +
        "The platform will run pg_dump on the selected target tables, or you can supply snapshot_ref via the API. " +
        "Ensure pg_dump is installed on the API host and MIGRATION_SNAPSHOT_DIR is writable.",
    };
  }

  return {
    environment: env,
    requireTargetSnapshot,
    title: "Development — target snapshot skipped",
    message:
      "Target backup verification is disabled for this environment (require_target_snapshot=false). " +
      "Migrations can start without a pg_dump snapshot. " +
      "Switch to Production in Settings when running against a live cutover target.",
  };
}
