/**
 * Probe saved connections before schema discovery / comparison.
 */
import { testConnection, testRawConnection, ApiError, type ConnectionConfig } from "./api";

export type ConnectionHealthStatus = "unknown" | "checking" | "reachable" | "unreachable";

export interface ConnectionHealth {
  status: ConnectionHealthStatus;
  message: string;
  host?: string;
  database?: string;
}

type ConnectionFallback = Pick<
  ConnectionConfig,
  "type" | "host" | "port" | "database" | "username" | "password" | "trust_server_certificate"
> & { name?: string };

function healthFromTest(
  res: { status: string; message: string },
  meta?: { host?: string; database?: string },
): ConnectionHealth {
  if (res.status === "connected") {
    return {
      status: "reachable",
      message: "Connection successful",
      host: meta?.host,
      database: meta?.database,
    };
  }
  return {
    status: "unreachable",
    message: res.message || "Connection test failed",
    host: meta?.host,
    database: meta?.database,
  };
}

async function probeRawFallback(
  fallback: ConnectionFallback,
  meta?: { host?: string; database?: string },
): Promise<ConnectionHealth | null> {
  if (!fallback.host || !fallback.database || !fallback.username) return null;
  const res = await testRawConnection({
    name: fallback.name ?? fallback.database,
    type: fallback.type,
    host: fallback.host,
    port: fallback.port,
    database: fallback.database,
    username: fallback.username,
    password: fallback.password,
    trust_server_certificate: fallback.trust_server_certificate,
  });
  return healthFromTest(res, meta);
}

async function probeWithRawFallback(
  fallback: ConnectionFallback,
  meta?: { host?: string; database?: string },
): Promise<ConnectionHealth | null> {
  try {
    return await probeRawFallback(fallback, meta);
  } catch (rawErr) {
    const message =
      rawErr instanceof ApiError
        ? rawErr.message
        : rawErr instanceof Error
          ? rawErr.message
          : "Unable to reach the database server";
    return {
      status: "unreachable",
      message,
      host: meta?.host,
      database: meta?.database,
    };
  }
}

export async function probeConnection(
  id: string,
  meta?: { host?: string; database?: string },
  fallback?: ConnectionFallback,
): Promise<ConnectionHealth> {
  try {
    const res = await testConnection(id);
    if (res.status === "connected") {
      return healthFromTest(res, meta);
    }
    // Stored credentials on the API may be stale — retry with local password when available.
    if (fallback?.password) {
      const raw = await probeWithRawFallback(fallback, meta);
      if (raw) return raw;
    }
    return healthFromTest(res, meta);
  } catch (err) {
    if (fallback?.password) {
      const raw = await probeWithRawFallback(fallback, meta);
      if (raw) return raw;
    }
    const message =
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : "Unable to reach the database server";
    return {
      status: "unreachable",
      message,
      host: meta?.host,
      database: meta?.database,
    };
  }
}

/** Probe every saved connection and refresh local connected/error status. */
export async function refreshAllConnectionStatuses(
  connections: Array<
    ConnectionFallback & { id: string; status?: "connected" | "disconnected" | "error" }
  >,
): Promise<
  Array<ConnectionFallback & { id: string; status: "connected" | "disconnected" | "error" }>
> {
  const results = await Promise.all(
    connections.map(async (conn) => {
      const health = await probeConnection(
        conn.id,
        { host: conn.host, database: conn.database },
        conn,
      );
      const status: "connected" | "disconnected" | "error" =
        health.status === "reachable"
          ? "connected"
          : health.status === "unreachable"
            ? "error"
            : conn.status ?? "disconnected";
      return { ...conn, status };
    }),
  );
  return results;
}

export function formatUnreachableMessage(
  label: string,
  health: ConnectionHealth,
): string {
  const target = health.host
    ? `${label} (${health.host}${health.database ? `/${health.database}` : ""})`
    : label;
  return `${target} is not reachable. ${health.message}`;
}

/** Format source + target connection test results for toast / inline display. */
export function formatConnectionTestFailures(
  source: { status: string; message: string },
  target: { status: string; message: string },
  meta?: { sourceName?: string; targetName?: string },
): string {
  const parts: string[] = [];
  if (source.status !== "connected") {
    const label = meta?.sourceName ? `SQL Server (${meta.sourceName})` : "SQL Server";
    parts.push(`${label}: ${source.message}`);
  }
  if (target.status !== "connected") {
    const label = meta?.targetName ? `PostgreSQL (${meta.targetName})` : "PostgreSQL";
    parts.push(`${label}: ${target.message}`);
  }
  return parts.join("\n");
}
