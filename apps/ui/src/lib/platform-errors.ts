/**
 * Platform error catalog client (§13.11).
 */
export interface PlatformErrorPayload {
  error_code?: string;
  title?: string;
  cause?: string;
  remediation?: string;
  doc_anchor?: string;
  correlation_id?: string;
  detail?: string;
}

const FALLBACKS: Record<string, { title: string; remediation: string }> = {
  CONN_AUTH_FAILED: {
    title: "Authentication failed",
    remediation: "Check database username and password in Connections.",
  },
  CONN_SOURCE_UNREACHABLE: {
    title: "Cannot reach SQL Server",
    remediation: "Verify host, port 1433, and firewall rules.",
  },
  CONN_TARGET_UNREACHABLE: {
    title: "Cannot reach PostgreSQL",
    remediation: "Verify host, port 5432, and pg_hba.conf.",
  },
  MIG_TARGET_CONFLICT: {
    title: "Target tables already exist",
    remediation:
      "Choose “Skip data load” if migration already completed, or “Truncate and reload” for a full refresh.",
  },
  MIG_SNAPSHOT_REQUIRED: {
    title: "Target backup required",
    remediation: "Provide snapshot_ref or disable require_target_snapshot for dev.",
  },
  INTERNAL_ERROR: {
    title: "Unexpected error",
    remediation: "Retry the operation or contact support with the correlation ID.",
  },
};

function classifyDetailMessage(detail: string, status: number): PlatformErrorPayload {
  if (/^SQL Server\s*\(/i.test(detail)) {
    return { title: "SQL Server connection failed", detail };
  }
  if (/^PostgreSQL\s*\(/i.test(detail)) {
    return { title: "PostgreSQL connection failed", detail };
  }
  const lower = detail.toLowerCase();
  if (/login failed|authentication|password/.test(lower)) {
    return { ...FALLBACKS.CONN_AUTH_FAILED, detail };
  }
  if (/target table conflict|choose a policy|already exist/.test(lower)) {
    return { ...FALLBACKS.MIG_TARGET_CONFLICT, detail };
  }
  if (/postgresql target|asyncpg|pg_hba|cannot reach postgresql/.test(lower)) {
    return { ...FALLBACKS.CONN_TARGET_UNREACHABLE, detail };
  }
  if (
    /sql server source|pyodbc|cannot reach sql server|:1433\b|tcp:.*1433/.test(
      lower,
    )
  ) {
    return { ...FALLBACKS.CONN_SOURCE_UNREACHABLE, detail };
  }
  if (
    /connection refused|timed out|host refused|unreachable/.test(lower) &&
    /postgres|5432|asyncpg/.test(lower)
  ) {
    return { ...FALLBACKS.CONN_TARGET_UNREACHABLE, detail };
  }
  if (
    /connection refused|timed out|host refused|unreachable/.test(lower) &&
    /sql server|1433|pyodbc/.test(lower)
  ) {
    return { ...FALLBACKS.CONN_SOURCE_UNREACHABLE, detail };
  }
  if (status === 502 && /postgres|asyncpg/.test(lower)) {
    return { ...FALLBACKS.CONN_TARGET_UNREACHABLE, detail };
  }
  if (status === 502) {
    return { ...FALLBACKS.CONN_SOURCE_UNREACHABLE, detail };
  }
  return { detail, error_code: "INTERNAL_ERROR", ...FALLBACKS.INTERNAL_ERROR };
}

export function parseApiError(body: unknown, status: number): PlatformErrorPayload {
  if (body && typeof body === "object") {
    const o = body as PlatformErrorPayload & { detail?: unknown };
    if (o.error_code) {
      return o;
    }
    if (o.detail && typeof o.detail === "object") {
      const nested = o.detail as PlatformErrorPayload;
      if (nested.error_code) {
        return nested;
      }
    }
    if (typeof o.detail === "string") {
      if (status === 401 && /invalid credentials/i.test(o.detail)) {
        return {
          title: "Invalid username or password",
          detail: o.detail,
          remediation: "Check the username and password, then try again.",
        };
      }
      if (status === 404 && /user not found/i.test(o.detail)) {
        return {
          title: "User not found",
          detail: o.detail,
          remediation: "Refresh the user list — this account may already have been deleted.",
        };
      }
      return classifyDetailMessage(o.detail, status);
    }
  }
  if (typeof body === "string") {
    return classifyDetailMessage(body, status);
  }
  return {
    error_code: "INTERNAL_ERROR",
    title: `Request failed (${status})`,
    remediation: FALLBACKS.INTERNAL_ERROR.remediation,
  };
}

export function formatUserMessage(err: PlatformErrorPayload): string {
  if (err.detail && /^(SQL Server|PostgreSQL)\s*\(/i.test(err.detail)) {
    return err.detail;
  }
  const fb = err.error_code ? FALLBACKS[err.error_code] : undefined;
  const title = err.title || fb?.title || "Something went wrong";
  const fix = err.remediation || fb?.remediation || "";
  const cause = err.cause ? ` ${err.cause}` : "";
  const detail = err.detail && !err.cause ? ` (${err.detail})` : "";
  const base = fix ? `${title}. ${fix}` : title;
  return `${base}${cause}${detail}`.trim();
}
