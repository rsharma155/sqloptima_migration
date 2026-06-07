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

export async function probeConnection(
  id: string,
  meta?: { host?: string; database?: string },
  fallback?: ConnectionFallback,
): Promise<ConnectionHealth> {
  try {
    const res = await testConnection(id);
    return healthFromTest(res, meta);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404 && fallback) {
      try {
        const raw = await probeRawFallback(fallback, meta);
        if (raw) return raw;
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
