import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getMigrationEnvironment,
  getMigrationSnapshotWarning,
  loadMigrationEnvironment,
  requireTargetSnapshotForEnv,
  saveMigrationEnvironment,
  MIGRATION_ENV_STORAGE_KEY,
} from "../migration-snapshot";

function mockLocalStorage() {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value); },
    removeItem: (key: string) => { store.delete(key); },
    clear: () => { store.clear(); },
  };
  vi.stubGlobal("localStorage", storage);
  return store;
}

describe("migration-snapshot", () => {
  beforeEach(() => {
    mockLocalStorage();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("defaults to development outside production NODE_ENV", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_MIGRATION_ENV", "");
    expect(loadMigrationEnvironment()).toBe("development");
    expect(requireTargetSnapshotForEnv("development")).toBe(false);
  });

  it("treats NEXT_PUBLIC_MIGRATION_ENV=production as production when no user override", () => {
    vi.stubEnv("NEXT_PUBLIC_MIGRATION_ENV", "production");
    expect(loadMigrationEnvironment()).toBe("production");
    expect(requireTargetSnapshotForEnv("production")).toBe(true);
  });

  it("prefers user setting from localStorage over build config", () => {
    vi.stubEnv("NEXT_PUBLIC_MIGRATION_ENV", "production");
    saveMigrationEnvironment("development");
    expect(loadMigrationEnvironment()).toBe("development");
    expect(getMigrationEnvironment()).toBe("development");
  });

  it("persists user environment choice", () => {
    saveMigrationEnvironment("production");
    expect(localStorage.getItem(MIGRATION_ENV_STORAGE_KEY)).toBe("production");
    expect(loadMigrationEnvironment()).toBe("production");
  });

  it("returns environment-specific warnings", () => {
    const dev = getMigrationSnapshotWarning("development");
    expect(dev.title).toContain("Development");
    expect(dev.requireTargetSnapshot).toBe(false);

    const prod = getMigrationSnapshotWarning("production");
    expect(prod.title).toContain("Production");
    expect(prod.message).toContain("pg_dump");
    expect(prod.requireTargetSnapshot).toBe(true);
  });
});
