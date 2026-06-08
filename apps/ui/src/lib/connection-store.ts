/**
 * Module: connection-store.ts
 * Purpose: Sync database connections between localStorage and the backend API.
 *          API routes (list-schemas, test, discover, etc.) resolve connections
 *          by ID from the server store — local-only entries cause 404s.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import {
  ApiError,
  createConnection,
  deleteConnection as apiDeleteConnection,
  getConnections,
  getToken,
  updateConnection,
  type ConnectionResponse,
} from "./api";
import {
  clearConnectionTombstone,
  connectionKey,
  dedupeConnections,
  isConnectionDeleted,
  markConnectionDeleted,
  type ConnectionIdentity,
} from "./connection-dedupe";

export {
  clearConnectionTombstone,
  connectionKey,
  dedupeConnections,
  findDuplicateName,
  findSimilarConnections,
  isConnectionDeleted,
  markConnectionDeleted,
} from "./connection-dedupe";

export interface Connection {
  id: string;
  name: string;
  type: "source" | "target";
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  trust_server_certificate?: boolean;
  status: "connected" | "disconnected" | "error";
}

export const STORAGE_KEY = "saved_connections";
export const CONNECTIONS_UPDATED_EVENT = "connections-updated";

export function loadConnections(): Connection[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Connection[];
  } catch {}
  return [];
}

export function saveConnections(connections: Connection[]): void {
  if (typeof window === "undefined") return;
  const deduped = dedupeConnections(connections.filter((c) => !isConnectionDeleted(c)));
  const next = JSON.stringify(deduped);
  const prev = localStorage.getItem(STORAGE_KEY);
  if (prev === next) return;
  localStorage.setItem(STORAGE_KEY, next);
  window.dispatchEvent(new CustomEvent(CONNECTIONS_UPDATED_EVENT));
}

/** Remove a connection from the API (when available) and local storage. */
export async function removeConnection(
  id: string,
  identity?: ConnectionIdentity,
): Promise<Connection[]> {
  const local = loadConnections();
  const target = local.find((c) => c.id === id) ?? identity;

  if (getToken()) {
    try {
      await apiDeleteConnection(id);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) {
        throw err;
      }
    }
  }

  if (target) {
    markConnectionDeleted(target);
  } else {
    markConnectionDeleted({ id });
  }

  const updated = local.filter((c) => {
    if (c.id === id) return false;
    if (target && connectionKey(c) === connectionKey(target)) return false;
    return !isConnectionDeleted(c);
  });

  saveConnections(updated);
  return updated;
}

function apiToConnection(
  c: ConnectionResponse,
  password = "",
  localTrust?: boolean,
): Connection {
  const status =
    c.status === "connected" || c.status === "error" ? c.status : "disconnected";
  return {
    id: c.id,
    name: c.name,
    type: c.type as "source" | "target",
    host: c.host,
    port: c.port,
    database: c.database,
    username: c.username,
    password,
    trust_server_certificate: Boolean(c.trust_server_certificate ?? localTrust ?? false),
    status,
  };
}

async function healTrustCertificate(
  remote: ConnectionResponse,
  local: Connection,
): Promise<ConnectionResponse | null> {
  if (
    local.type !== "source" ||
    !local.trust_server_certificate ||
    remote.trust_server_certificate ||
    !local.password
  ) {
    return null;
  }
  try {
    return await updateConnection(remote.id, {
      name: remote.name,
      type: remote.type as "source" | "target",
      host: remote.host,
      port: remote.port,
      database: remote.database,
      username: remote.username,
      password: local.password,
      trust_server_certificate: true,
    });
  } catch {
    return null;
  }
}

/** Load connections from the API and push any local-only entries to the backend. */
export async function fetchAndSyncConnections(): Promise<Connection[]> {
  const local = loadConnections().filter((c) => !isConnectionDeleted(c));
  if (!getToken()) {
    saveConnections(local);
    return local;
  }

  try {
    const remote = (await getConnections()).filter((c) => !isConnectionDeleted(c));
    const remoteById = new Map(remote.map((c) => [c.id, c]));
    const remoteByKey = new Map(remote.map((c) => [connectionKey(c), c]));

    const merged: Connection[] = [];
    const seenIds = new Set<string>();

    for (const lc of local) {
      if (isConnectionDeleted(lc)) continue;

      const match = remoteById.get(lc.id) ?? remoteByKey.get(connectionKey(lc));
      if (match) {
        if (!seenIds.has(match.id)) {
          const healed = await healTrustCertificate(match, lc);
          const effective = healed ?? match;
          merged.push(apiToConnection(effective, lc.password, lc.trust_server_certificate));
          seenIds.add(match.id);
        }
        continue;
      }

      if (!lc.password) {
        merged.push(lc);
        continue;
      }

      if (isConnectionDeleted(lc)) continue;

      try {
        const created = await createConnection({
          name: lc.name,
          type: lc.type,
          host: lc.host,
          port: lc.port,
          database: lc.database,
          username: lc.username,
          password: lc.password,
          trust_server_certificate: lc.trust_server_certificate,
        });
        merged.push(apiToConnection(created, lc.password));
        seenIds.add(created.id);
      } catch {
        merged.push(lc);
      }
    }

    for (const rc of remote) {
      if (isConnectionDeleted(rc)) continue;
      if (!seenIds.has(rc.id)) {
        merged.push(apiToConnection(rc));
        seenIds.add(rc.id);
      }
    }

    const deduped = dedupeConnections(merged);
    saveConnections(deduped);
    return deduped;
  } catch {
    saveConnections(local);
    return local;
  }
}
