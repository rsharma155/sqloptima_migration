import { describe, expect, it } from "vitest";
import {
  formatMigrationStatus,
  isActiveMigration,
  isLiveMigrationDetail,
  isTerminalMigration,
  migrationStatusVariant,
} from "../migration-status";

describe("migration-status", () => {
  it("formats known statuses", () => {
    expect(formatMigrationStatus("running")).toBe("Running");
    expect(formatMigrationStatus("FAILED")).toBe("Failed");
  });

  it("maps variants for badges", () => {
    expect(migrationStatusVariant("completed")).toBe("success");
    expect(migrationStatusVariant("failed")).toBe("destructive");
    expect(migrationStatusVariant("running")).toBe("warning");
  });

  it("detects active migrations", () => {
    expect(isActiveMigration("running")).toBe(true);
    expect(isActiveMigration("queued")).toBe(true);
    expect(isActiveMigration("completed")).toBe(false);
  });

  it("detects live detail polling statuses", () => {
    expect(isLiveMigrationDetail("queued")).toBe(true);
    expect(isLiveMigrationDetail("running")).toBe(true);
    expect(isLiveMigrationDetail("completed")).toBe(false);
    expect(isTerminalMigration("failed")).toBe(true);
  });
});
