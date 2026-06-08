import { describe, expect, it } from "vitest";
import { formatUserMessage, parseApiError } from "../platform-errors";

describe("platform-errors", () => {
  it("parses catalog error payload", () => {
    const err = parseApiError(
      {
        error_code: "CONN_AUTH_FAILED",
        title: "Cannot authenticate",
        remediation: "Fix credentials",
      },
      500,
    );
    expect(err.error_code).toBe("CONN_AUTH_FAILED");
    expect(formatUserMessage(err)).toContain("Fix credentials");
  });

  it("falls back for plain detail string", () => {
    const err = parseApiError({ detail: "pyodbc error" }, 500);
    expect(err.error_code).toBe("INTERNAL_ERROR");
  });
});
