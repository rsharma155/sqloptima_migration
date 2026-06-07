"use client";

/**
 * Module: ConnectionContext.tsx
 * Purpose: Next.js frontend UI — shared connection state synced with the backend API.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import {
  type Connection,
  CONNECTIONS_UPDATED_EVENT,
  fetchAndSyncConnections,
  loadConnections,
} from "./connection-store";

export type { Connection };
export { CONNECTIONS_UPDATED_EVENT };

interface ConnectionContextValue {
  connections: Connection[];
  sourceConnections: Connection[];
  targetConnections: Connection[];
  refreshConnections: () => void;
  getConnection: (id: string) => Connection | undefined;
}

const ConnectionContext = createContext<ConnectionContextValue>({
  connections: [],
  sourceConnections: [],
  targetConnections: [],
  refreshConnections: () => {},
  getConnection: () => undefined,
});

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [connections, setConnections] = useState<Connection[]>([]);

  const refreshConnections = useCallback(() => {
    fetchAndSyncConnections()
      .then(setConnections)
      .catch(() => setConnections(loadConnections()));
  }, []);

  useEffect(() => {
    refreshConnections();

    const handleStorage = (e: StorageEvent) => {
      if (e.key === "saved_connections") refreshConnections();
    };
    const handleCustom = () => refreshConnections();

    window.addEventListener("storage", handleStorage);
    window.addEventListener(CONNECTIONS_UPDATED_EVENT, handleCustom);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener(CONNECTIONS_UPDATED_EVENT, handleCustom);
    };
  }, [refreshConnections]);

  const sourceConnections = connections.filter((c) => c.type === "source");
  const targetConnections = connections.filter((c) => c.type === "target");

  const getConnection = useCallback(
    (id: string) => connections.find((c) => c.id === id),
    [connections]
  );

  return (
    <ConnectionContext.Provider
      value={{ connections, sourceConnections, targetConnections, refreshConnections, getConnection }}
    >
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnections() {
  return useContext(ConnectionContext);
}
