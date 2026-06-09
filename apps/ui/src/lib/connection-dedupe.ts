/**
 * Module: connection-dedupe.ts
 * Purpose: Pure helpers to collapse duplicate saved database connections.
 */

export interface ConnectionIdentity {
  id: string;
  name: string;
  type: "source" | "target";
  host: string;
  port: number;
  database: string;
  password?: string;
  status?: "connected" | "disconnected" | "error";
}

export function normalizeConnectionHost(host: string | null | undefined): string {
  return (host || "").trim().toLowerCase();
}

export function normalizeConnectionDatabase(database: string | null | undefined): string {
  return (database || "").trim().toLowerCase();
}

export function normalizeConnectionPort(port: number | string | undefined): number {
  const n = Number(port);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
}

/** Stable key for type + host + port + database endpoint matching (case-insensitive host/database). */
export function connectionEndpointKey(
  type: "source" | "target",
  host: string | null | undefined,
  database: string | null | undefined,
  port: number | string | undefined,
): string {
  return `${type}:${normalizeConnectionHost(host)}:${normalizeConnectionPort(port)}:${normalizeConnectionDatabase(database)}`;
}

export function connectionKey(c: ConnectionIdentity): string {
  return `${c.type}:${normalizeConnectionHost(c.host)}:${normalizeConnectionPort(c.port)}:${normalizeConnectionDatabase(c.database)}:${(c.name || "").trim().toLowerCase()}`;
}

/** Find an existing connection with the same name (case-insensitive). */
export function findDuplicateName<T extends ConnectionIdentity>(
  connections: T[],
  name: string,
  excludeId?: string | null,
): T | undefined {
  const normalized = (name || "").trim().toLowerCase();
  if (!normalized) return undefined;
  return connections.find(
    (c) => c.id !== excludeId && (c.name || "").trim().toLowerCase() === normalized,
  );
}

/** Find connections pointing at the same type, host, port, and database. */
export function findSimilarConnections<T extends ConnectionIdentity>(
  connections: T[],
  type: "source" | "target",
  host: string | null | undefined,
  database: string | null | undefined,
  port: number | string | undefined,
  excludeId?: string | null,
): T[] {
  if (!host?.trim() || !database?.trim()) return [];
  const endpoint = connectionEndpointKey(type, host, database, port);
  return connections.filter(
    (c) =>
      c.id !== excludeId &&
      connectionEndpointKey(c.type, c.host, c.database, c.port) === endpoint,
  );
}

const DELETED_CONNECTIONS_KEY = "deleted_connection_tombstones";

export function loadDeletedTombstones(): Set<string> {
  if (typeof window === "undefined" || typeof localStorage === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(DELETED_CONNECTIONS_KEY);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch {}
  return new Set();
}

function persistDeletedTombstones(tombstones: Set<string>): void {
  if (typeof window === "undefined" || typeof localStorage === "undefined") return;
  localStorage.setItem(DELETED_CONNECTIONS_KEY, JSON.stringify([...tombstones]));
}

/** Record a connection the user deleted so sync cannot resurrect it. */
export function markConnectionDeleted(c: ConnectionIdentity | { id: string }): void {
  const tombstones = loadDeletedTombstones();
  tombstones.add(c.id);
  if ("host" in c && "database" in c && "name" in c && "type" in c) {
    tombstones.add(connectionKey(c));
  }
  persistDeletedTombstones(tombstones);
}

/** Allow re-adding a connection the user explicitly saved again. */
export function clearConnectionTombstone(c: ConnectionIdentity): void {
  const tombstones = loadDeletedTombstones();
  tombstones.delete(c.id);
  tombstones.delete(connectionKey(c));
  persistDeletedTombstones(tombstones);
}

export function isConnectionDeleted(c: ConnectionIdentity): boolean {
  const tombstones = loadDeletedTombstones();
  return tombstones.has(c.id) || tombstones.has(connectionKey(c));
}

function preferConnection<T extends ConnectionIdentity>(a: T, b: T): T {
  if (a.password && !b.password) return a;
  if (b.password && !a.password) return b;
  if (a.status === "connected" && b.status !== "connected") return a;
  if (b.status === "connected" && a.status !== "connected") return b;
  return b;
}

/** Collapse duplicate entries (same id or same type/host/database/name). */
export function dedupeConnections<T extends ConnectionIdentity>(connections: T[]): T[] {
  const byKey = new Map<string, T>();
  for (const c of connections) {
    const key = connectionKey(c);
    const existing = byKey.get(key);
    byKey.set(key, existing ? preferConnection(existing, c) : c);
  }
  const byId = new Map<string, T>();
  for (const c of byKey.values()) {
    const existing = byId.get(c.id);
    byId.set(c.id, existing ? preferConnection(existing, c) : c);
  }
  return Array.from(byId.values());
}
