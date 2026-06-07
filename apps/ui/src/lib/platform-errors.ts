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
  const lower = detail.toLowerCase();
  if (/login failed|authentication|password/.test(lower)) {
    return { ...FALLBACKS.CONN_AUTH_FAILED, detail };
  }
  if (/asyncpg|postgres|5432|pg_hba/.test(lower)) {
    return { ...FALLBACKS.CONN_TARGET_UNREACHABLE, detail };
  }
  if (/pyodbc|sql server|1433|connection|refused|timeout|unreachable|network/.test(lower)) {
    return { ...FALLBACKS.CONN_SOURCE_UNREACHABLE, detail };
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
  const fb = err.error_code ? FALLBACKS[err.error_code] : undefined;
  const title = err.title || fb?.title || "Something went wrong";
  const fix = err.remediation || fb?.remediation || "";
  const cause = err.cause ? ` ${err.cause}` : "";
  const detail = err.detail && !err.cause ? ` (${err.detail})` : "";
  const base = fix ? `${title}. ${fix}` : title;
  return `${base}${cause}${detail}`.trim();
}
