"use client";

/**
 * Module: app/replication/page.tsx
 * Purpose: CDC replication stream management
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Activity,
  AlertTriangle,
  Database,
  Plus,
  Loader2,
  Play,
  Pause,
  Square,
  Server,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { useConnections, type Connection } from "@/lib/ConnectionContext";
import {
  createReplicationStream,
  discoverSchema,
  getReplicationCdcStatus,
  getReplicationStreamStatus,
  listReplicationStreams,
  type ReplicationCdcStatus,
  pauseReplicationStream,
  resumeReplicationStream,
  startReplicationStream,
  stopReplicationStream,
  testConnection,
  type ReplicationStream as ApiReplicationStream,
} from "@/lib/api";
import { formatConnectionTestFailures } from "@/lib/connection-health";
import { EmptyState } from "@/components/shared/empty-state";

interface DiscoveredTable {
  name: string;
  schema: string;
  type: string;
}

export default function ReplicationPage() {
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [sourceConn, setSourceConn] = useState<Connection | null>(null);
  const [targetConn, setTargetConn] = useState<Connection | null>(null);
  const [schema, setSchema] = useState("dbo");
  const [discoveredTables, setDiscoveredTables] = useState<DiscoveredTable[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [streams, setStreams] = useState<ApiReplicationStream[]>([]);
  const [streamsLoading, setStreamsLoading] = useState(true);
  const [targetSchema, setTargetSchema] = useState("public");
  const [streamName, setStreamName] = useState("");
  const [cdcStatus, setCdcStatus] = useState<ReplicationCdcStatus | null>(null);
  const [cdcChecking, setCdcChecking] = useState(false);

  const { sourceConnections, targetConnections } = useConnections();

  const refreshCdcStatus = useCallback(async (tableName?: string) => {
    if (!sourceConn) {
      setCdcStatus(null);
      return;
    }
    setCdcChecking(true);
    try {
      const status = await getReplicationCdcStatus(
        sourceConn.id,
        schema || "dbo",
        tableName ? [tableName] : undefined,
      );
      setCdcStatus(status);
    } catch (err) {
      setCdcStatus({
        db_cdc_enabled: false,
        tables: {},
        ready: false,
        message: err instanceof Error ? err.message : "Could not verify CDC status",
      });
    } finally {
      setCdcChecking(false);
    }
  }, [sourceConn, schema]);

  useEffect(() => {
    if (sourceConn && !sourceConnections.find((c) => c.id === sourceConn.id)) setSourceConn(null);
    if (targetConn && !targetConnections.find((c) => c.id === targetConn.id)) setTargetConn(null);
    if (sourceConnections.length > 0 && !sourceConn) setSourceConn(sourceConnections[0]);
    if (targetConnections.length > 0 && !targetConn) setTargetConn(targetConnections[0]);
  }, [sourceConnections, targetConnections, sourceConn, targetConn]);

  // Auto-discover when dialog opens and we have a source connection
  useEffect(() => {
    if (showAddDialog && sourceConn) {
      handleDiscover();
    }
    if (!showAddDialog) {
      setDiscoveredTables([]);
      setSelectedTable("");
      setDiscoverError(null);
      setCdcStatus(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAddDialog]);

  useEffect(() => {
    if (showAddDialog && sourceConn) {
      refreshCdcStatus();
    }
  }, [showAddDialog, sourceConn, schema, refreshCdcStatus]);

  useEffect(() => {
    if (showAddDialog && sourceConn && selectedTable) {
      refreshCdcStatus(selectedTable);
    }
  }, [selectedTable, showAddDialog, sourceConn, refreshCdcStatus]);

  const handleDiscover = useCallback(async () => {
    if (!sourceConn) {
      toast.error("Select a source connection first");
      return;
    }
    setLoading(true);
    setDiscoverError(null);
    setDiscoveredTables([]);
    setSelectedTable("");
    try {
      const result = await discoverSchema(sourceConn.id, schema || "dbo");
      // Backend returns lowercase type values (StrEnum "table"); normalise before filtering
      const tables = (result.items as DiscoveredTable[]).filter(
        (o) => o.type.toLowerCase() === "table"
      );
      setDiscoveredTables(tables);
      if (tables.length > 0) {
        setSelectedTable(tables[0].name);
        toast.success(`Discovered ${tables.length} tables`);
      } else {
        setDiscoverError(`No tables found in schema "${schema || "dbo"}". Try a different schema name.`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Discovery failed";
      setDiscoverError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [sourceConn, schema]);

  const handleAddStream = useCallback(() => {
    if (!sourceConn || !targetConn) {
      toast.info("Configure source and target connections in Settings first");
      return;
    }
    setShowAddDialog(true);
    // Discovery is triggered by the useEffect above when showAddDialog becomes true
  }, [sourceConn, targetConn]);

  const loadStreams = useCallback(async () => {
    try {
      const rows = await listReplicationStreams();
      setStreams(rows);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load streams");
    } finally {
      setStreamsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStreams();
  }, [loadStreams]);

  const handleCreateAndStart = useCallback(async () => {
    if (!sourceConn || !targetConn || !selectedTable) {
      toast.error("Select connections and a table");
      return;
    }
    setLoading(true);
    try {
      const created = await createReplicationStream({
        name: streamName || `${schema}.${selectedTable}`,
        source_connection_id: sourceConn.id,
        target_connection_id: targetConn.id,
        tables: [selectedTable],
        source_schema: schema || "dbo",
        target_schema: targetSchema || "public",
        mode: "cdc",
      });
      if (created.concerns.some((c) => c.level === "blocker")) {
        toast.warning("Stream created with blockers — resolve concerns before data flows");
        setStreams((prev) => [created, ...prev]);
        setShowAddDialog(false);
        return;
      }
      const started = await startReplicationStream(created.stream_id);
      setStreams((prev) => [started, ...prev.filter((s) => s.stream_id !== started.stream_id)]);
      toast.success(`Replication started for ${selectedTable}`);
      setShowAddDialog(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create stream");
    } finally {
      setLoading(false);
    }
  }, [sourceConn, targetConn, selectedTable, schema, targetSchema, streamName]);

  const handleStreamAction = useCallback(
    async (streamId: string, action: "pause" | "resume" | "stop") => {
      try {
        const updated =
          action === "pause"
            ? await pauseReplicationStream(streamId)
            : action === "resume"
            ? await resumeReplicationStream(streamId)
            : await stopReplicationStream(streamId);
        setStreams((prev) =>
          prev.map((s) => (s.stream_id === streamId ? { ...s, ...updated } : s)),
        );
        toast.success(`Stream ${action}d`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : `Failed to ${action} stream`);
      }
    },
    [],
  );

  const handleTestConnections = useCallback(async () => {
    if (!sourceConn || !targetConn) return;
    toast.loading("Testing connections...");
    try {
      const src = await testConnection(sourceConn.id);
      const tgt = await testConnection(targetConn.id);
      toast.dismiss();
      if (src.status === "connected" && tgt.status === "connected") {
        toast.success("Both connections are valid");
      } else {
        toast.error(
          formatConnectionTestFailures(src, tgt, {
            sourceName: sourceConn.name,
            targetName: targetConn.name,
          }),
          { duration: 8000 },
        );
      }
    } catch {
      toast.dismiss();
      toast.error("Could not test connections");
    }
  }, [sourceConn, targetConn]);

  const activeStreams = streams.filter((s) =>
    ["CDC_STREAMING", "STARTING", "CDC_CATCHUP"].includes(s.status),
  ).length;

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    const interval = activeStreams > 0 ? 5_000 : 30_000;
    pollRef.current = setInterval(() => {
      streams
        .filter((s) => ["CDC_STREAMING", "PAUSED"].includes(s.status))
        .forEach(async (s) => {
          try {
            const fresh = await getReplicationStreamStatus(s.stream_id);
            setStreams((prev) =>
              prev.map((row) => (row.stream_id === s.stream_id ? { ...row, ...fresh } : row)),
            );
          } catch {
            /* ignore poll errors */
          }
        });
    }, interval);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeStreams, streams]);

  const totalCaptured = streams.reduce((n, s) => n + (s.events_captured || 0), 0);
  const totalApplied = streams.reduce((n, s) => n + (s.events_applied || 0), 0);
  const queueDepth = streams.reduce((n, s) => n + (s.queue_depth || 0), 0);

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Replication</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitor and manage active CDC replication streams
          </p>
        </div>
        <Button onClick={handleAddStream}>
          <Plus className="h-4 w-4 mr-2" />
          Add Stream
        </Button>
      </div>

      {sourceConn && targetConn && (
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Badge variant="outline" className="text-[10px] px-1 py-0">Source</Badge>
          <span className="font-mono text-xs">{sourceConn.host}:{sourceConn.port}/{sourceConn.database}</span>
          <span className="text-muted-foreground/50">→</span>
          <Badge variant="secondary" className="text-[10px] px-1 py-0">Target</Badge>
          <span className="font-mono text-xs">{targetConn.host}:{targetConn.port}/{targetConn.database}</span>
        </div>
      )}

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Active Streams</CardTitle>
            <Activity className={`h-4 w-4 ${activeStreams > 0 ? "text-emerald-500" : "text-muted-foreground"}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{activeStreams} / {streams.length}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {streams.length === 0 ? "No streams configured" : `${streams.length - activeStreams} stopped`}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Events Captured</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">{totalCaptured}</div>
            <p className="text-xs text-muted-foreground mt-1">From source polling</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Events Applied</CardTitle>
            <Activity className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-emerald-500">{totalApplied}</div>
            <p className="text-xs text-muted-foreground mt-1">Written to PostgreSQL</p>
          </CardContent>
        </Card>

        <Card className={queueDepth > 100 ? "border-amber-500/40" : ""}>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Queue Depth</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{queueDepth}</div>
            <p className="text-xs text-muted-foreground mt-1">Pending in-memory queue</p>
          </CardContent>
        </Card>
      </div>

      {/* Connection selectors */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={sourceConn?.id || ""}
          onChange={(e) => {
            const c = sourceConnections.find((c) => c.id === e.target.value);
            if (c) { setSourceConn(c); setDiscoveredTables([]); }
          }}
          className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
        >
          {sourceConnections.length === 0 && <option value="">No source connections</option>}
          {sourceConnections.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <span className="text-muted-foreground text-sm">→</span>
        <select
          value={targetConn?.id || ""}
          onChange={(e) => {
            const c = targetConnections.find((c) => c.id === e.target.value);
            if (c) setTargetConn(c);
          }}
          className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
        >
          {targetConnections.length === 0 && <option value="">No target connections</option>}
          {targetConnections.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <Button variant="outline" size="sm" onClick={handleTestConnections} disabled={!sourceConn || !targetConn}>
          Test Connections
        </Button>
      </div>

      {/* Stream list */}
      {streams.length > 0 && (
        <Card>
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-base">Replication Streams</CardTitle>
              <CardDescription>Capture → queue → apply pipeline with pause/resume</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={loadStreams}>
              <RefreshCw className="h-4 w-4 mr-1" /> Refresh
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              {streams.map((s) => {
                const tableName = s.tables[0]?.name ?? s.name;
                const isActive = ["CDC_STREAMING", "STARTING", "CDC_CATCHUP"].includes(s.status);
                return (
                  <div key={s.stream_id} className="flex items-center gap-3 px-6 py-3 hover:bg-muted/50">
                    <div className={`flex h-8 w-8 items-center justify-center rounded-md ${
                      isActive ? "bg-emerald-500/10 text-emerald-500" : "bg-muted text-muted-foreground"
                    }`}>
                      <Activity className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{s.name}</p>
                      <p className="text-xs text-muted-foreground font-mono">
                        {s.source_schema}.{tableName} → {s.target_schema}.{tableName.toLowerCase()}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        captured {s.events_captured} · applied {s.events_applied}
                        {s.concerns.length > 0 && (
                          <span className="text-amber-400 ml-2">{s.concerns.length} concern(s)</span>
                        )}
                      </p>
                    </div>
                    <Badge variant="outline" className="text-[10px]">{s.status}</Badge>
                    {s.status === "CDC_STREAMING" && (
                      <Button variant="ghost" size="sm" onClick={() => handleStreamAction(s.stream_id, "pause")}>
                        <Pause className="h-4 w-4" />
                      </Button>
                    )}
                    {s.status === "PAUSED" && (
                      <Button variant="ghost" size="sm" onClick={() => handleStreamAction(s.stream_id, "resume")}>
                        <Play className="h-4 w-4" />
                      </Button>
                    )}
                    {["CDC_STREAMING", "PAUSED", "IDLE"].includes(s.status) && (
                      <Button variant="ghost" size="sm" onClick={() => handleStreamAction(s.stream_id, "stop")}>
                        <Square className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {!streamsLoading && streams.length === 0 && (
        <EmptyState
          icon={Database}
          title="No replication streams"
          description={
            sourceConnections.length > 0 && targetConnections.length > 0
              ? "Click \"Add Stream\" above to configure a CDC replication stream."
              : "Set up source and target connections in Settings first, then add a replication stream."
          }
          actionLabel={
            sourceConnections.length === 0 || targetConnections.length === 0
              ? "Configure Connections"
              : undefined
          }
          onAction={
            sourceConnections.length === 0 || targetConnections.length === 0
              ? () => { window.location.href = "/settings"; }
              : undefined
          }
        />
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Add Stream Dialog                                                   */}
      {/* ------------------------------------------------------------------ */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="w-full max-w-4xl sm:max-w-5xl flex flex-col p-0 gap-0 overflow-hidden max-h-[90vh]">
          <DialogHeader className="px-6 pt-6 pb-4 border-b shrink-0">
            <DialogTitle>Add Replication Stream</DialogTitle>
            <DialogDescription>
              Select a source table to replicate to the target database via CDC.
            </DialogDescription>
          </DialogHeader>

          <div className="px-6 py-5 space-y-5 flex-1 overflow-y-auto">
            {cdcChecking && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Checking SQL Server CDC status…
              </div>
            )}
            {!cdcChecking && cdcStatus && !cdcStatus.ready && cdcStatus.message && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <div className="whitespace-pre-wrap">{cdcStatus.message}</div>
              </div>
            )}
            {!cdcChecking && cdcStatus?.ready && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-600">
                CDC is enabled for the selected source{selectedTable ? ` table (${selectedTable})` : " database"}.
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Stream Name</Label>
                <Input
                  value={streamName}
                  onChange={(e) => setStreamName(e.target.value)}
                  placeholder="e.g. orders-cdc"
                  className="h-9"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Target Schema</Label>
                <Input
                  value={targetSchema}
                  onChange={(e) => setTargetSchema(e.target.value)}
                  placeholder="public"
                  className="h-9"
                />
              </div>
            </div>
            {/* Connection selectors */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Source Connection</Label>
                <select
                  value={sourceConn?.id || ""}
                  onChange={(e) => {
                    const c = sourceConnections.find((c) => c.id === e.target.value);
                    if (c) { setSourceConn(c); setDiscoveredTables([]); setDiscoverError(null); }
                  }}
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                >
                  {sourceConnections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>Target Connection</Label>
                <select
                  value={targetConn?.id || ""}
                  onChange={(e) => {
                    const c = targetConnections.find((c) => c.id === e.target.value);
                    if (c) setTargetConn(c);
                  }}
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                >
                  {targetConnections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Schema + discover */}
            <div className="flex items-end gap-3">
              <div className="space-y-1.5 w-36">
                <Label>Schema</Label>
                <Input
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                  placeholder="dbo"
                  className="h-9"
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleDiscover}
                disabled={loading || !sourceConn}
                className="h-9"
              >
                {loading
                  ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  : <RefreshCw className="h-4 w-4 mr-2" />}
                {loading ? "Discovering…" : "Refresh Tables"}
              </Button>
            </div>

            {/* Source Table picker */}
            <div className="space-y-1.5">
              <Label>Source Table</Label>

              {loading && (
                <div className="flex items-center gap-2 h-10 px-3 rounded-md border border-input bg-muted/30 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                  Discovering tables from source database…
                </div>
              )}

              {!loading && discoverError && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive flex items-start gap-2">
                  <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <div>
                    <p>{discoverError}</p>
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto p-0 text-xs mt-1"
                      onClick={handleDiscover}
                    >
                      Retry discovery
                    </Button>
                  </div>
                </div>
              )}

              {!loading && !discoverError && discoveredTables.length === 0 && (
                <div className="flex items-center gap-2 h-10 px-3 rounded-md border border-input bg-muted/20 text-sm text-muted-foreground">
                  <Server className="h-4 w-4 shrink-0" />
                  No tables — click Refresh Tables to load from source
                </div>
              )}

              {!loading && discoveredTables.length > 0 && (
                <select
                  value={selectedTable}
                  onChange={(e) => setSelectedTable(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm truncate"
                >
                  {discoveredTables.map((t) => (
                    <option key={t.name} value={t.name}>{t.schema}.{t.name}</option>
                  ))}
                </select>
              )}
            </div>

            {selectedTable && !loading && (
              <div className="rounded-md bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-0.5">
                <p className="font-medium text-foreground">Replication details</p>
                <p>Source: <span className="font-mono">{sourceConn?.database}.{schema}.{selectedTable}</span></p>
                <p>Target: <span className="font-mono">{targetConn?.database}.public.{selectedTable.toLowerCase()}</span></p>
              </div>
            )}
          </div>

          <DialogFooter className="px-6 py-4 border-t shrink-0">
            <Button variant="outline" onClick={() => setShowAddDialog(false)}>Cancel</Button>
            <Button
              onClick={handleCreateAndStart}
              disabled={!selectedTable || loading || cdcChecking || !cdcStatus?.ready}
            >
              <Play className="h-4 w-4 mr-2" />
              Create &amp; Start
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
