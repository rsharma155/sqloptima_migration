import { describe, expect, it } from "vitest";
import {
  dedupeConnections,
  findDuplicateName,
  findSimilarConnections,
} from "../connection-dedupe";

const base = (overrides: Record<string, unknown> = {}) => ({
  id: "9b5730d3-e7b7-4d66-b2d8-db59af01c812",
  name: "Local SQL Server",
  type: "source",
  host: "localhost",
  port: 1433,
  database: "AdventureWorks",
  username: "sa",
  password: "secret",
  status: "disconnected",
  ...overrides,
});

describe("dedupeConnections", () => {
  it("removes duplicate entries with the same server id", () => {
    const dupes = [
      base(),
      base({ status: "connected" }),
    ];
    const result = dedupeConnections(dupes);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("9b5730d3-e7b7-4d66-b2d8-db59af01c812");
    expect(result[0].status).toBe("connected");
  });

  it("collapses local and server ids for the same logical connection", () => {
    const dupes = [
      base({ id: "conn-local-1", password: "secret" }),
      base({ id: "9b5730d3-e7b7-4d66-b2d8-db59af01c812", password: "" }),
    ];
    const result = dedupeConnections(dupes);
    expect(result).toHaveLength(1);
    expect(result[0].password).toBe("secret");
  });
});

describe("findDuplicateName", () => {
  it("detects case-insensitive name collisions", () => {
    const connections = [base({ name: "Production SQL" })];
    expect(findDuplicateName(connections, "production sql")).toEqual(connections[0]);
    expect(findDuplicateName(connections, "Production SQL", "9b5730d3-e7b7-4d66-b2d8-db59af01c812")).toBeUndefined();
  });
});

describe("findSimilarConnections", () => {
  it("matches host and database case-insensitively", () => {
    const connections = [
      base({ id: "a", name: "Primary", host: "LOCALHOST", database: "AdventureWorks" }),
      base({ id: "b", name: "Replica", host: "db.example.com", database: "OtherDb" }),
    ];
    const matches = findSimilarConnections(connections, "source", "localhost", "adventureworks", 1433);
    expect(matches).toHaveLength(1);
    expect(matches[0].name).toBe("Primary");
  });

  it("excludes the connection being edited", () => {
    const connections = [base({ id: "edit-me", host: "localhost", database: "AdventureWorks" })];
    expect(findSimilarConnections(connections, "source", "localhost", "AdventureWorks", 1433, "edit-me")).toHaveLength(0);
  });
});
