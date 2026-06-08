"use client";

/**
 * Module: app/replication/page.tsx
 * Purpose: CDC replication stream management
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  Database,
  Plus,
  Loader2,
  Play,
  Pause,
  Square,
  Server,
  RefreshCw,
  XCircle,
  Pencil,
  Trash2,
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
  deleteReplicationStream,
  discoverSchema,
  getReplicationCdcStatus,
  getReplicationSummary,
  getReplicationTargetStatus,
  listReplicationStreams,
  type ReplicationSummary,
  type ReplicationCdcStatus,
  type ReplicationTargetTableStatus,
  pauseReplicationStream,
  resumeReplicationStream,
  startReplicationStream,
  stopReplicationStream,
  testConnection,
  updateReplicationStream,
  type ReplicationStream as ApiReplicationStream,
} from "@/lib/api";
import { formatConnectionTestFailures } from "@/lib/connection-health";
import { resolveTargetSchema } from "@/lib/schema-mapping";
import { EmptyState } from "@/components/shared/empty-state";

interface DiscoveredTable {
  name: string;
  schema: string;
  type: string;
}

const ACTIVE_STREAM_STATUSES = ["CDC_STREAMING", "STARTING", "CDC_CATCHUP", "PAUSED"];

export default function ReplicationPage() {
  const [showStreamDialog, setShowStreamDialog] = useState(false);
  const [editingStreamId, setEditingStreamId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ApiReplicationStream | null>(null);
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
  const [targetStatus, setTargetStatus] = useState<ReplicationTargetTableStatus | null>(null);
  const [targetChecking, setTargetChecking] = useState(false);
  const [summary, setSummary] = useState<ReplicationSummary | null>(null);

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

  const resolvedTargetSchema = resolveTargetSchema(schema, targetSchema);

  const refreshTargetStatus = useCallback(async (tableName?: string) => {
    if (!targetConn || !tableName) {
      setTargetStatus(null);
      return;
    }
    setTargetChecking(true);
    try {
      const rows = await getReplicationTargetStatus(
        targetConn.id,
        resolvedTargetSchema,
        [tableName],
        schema || "dbo",
      );
      setTargetStatus(rows[0] ?? null);
    } catch (err) {
      setTargetStatus({
        table_name: tableName,
        exists: false,
        row_count: 0,
        schema_mismatch: false,
        ready: false,
        message: err instanceof Error ? err.message : "Could not verify target table",
      });
    } finally {
      setTargetChecking(false);
    }
  }, [targetConn, resolvedTargetSchema, schema]);

  const resetStreamDialog = useCallback(() => {
    setEditingStreamId(null);
    setStreamName("");
    setDiscoveredTables([]);
    setSelectedTable("");
    setDiscoverError(null);
    setCdcStatus(null);
    setTargetStatus(null);
  }, []);

  const openCreateDialog = useCallback(() => {
    resetStreamDialog();
    setShowStreamDialog(true);
  }, [resetStreamDialog]);

  const openEditDialog = useCallback((stream: ApiReplicationStream) => {
    if (ACTIVE_STREAM_STATUSES.includes(stream.status)) {
      toast.error("Stop the stream before editing");
      return;
    }
    const tableName = stream.tables[0]?.name ?? "";
    const src = sourceConnections.find((c) => c.id === stream.source_connection_id) ?? sourceConn;
    const tgt = targetConnections.find((c) => c.id === stream.target_connection_id) ?? targetConn;
    if (src) setSourceConn(src);
    if (tgt) setTargetConn(tgt);
    setSchema(stream.source_schema || "dbo");
    setTargetSchema(stream.target_schema || "public");
    setStreamName(stream.name);
    setSelectedTable(tableName);
    if (tableName) {
      setDiscoveredTables([{ name: tableName, schema: stream.source_schema, type: "table" }]);
    }
    setEditingStreamId(stream.stream_id);
    setShowStreamDialog(true);
  }, [sourceConnections, targetConnections, sourceConn, targetConn]);

  useEffect(() => {
    if (sourceConn && !sourceConnections.find((c) => c.id === sourceConn.id)) setSourceConn(null);
    if (targetConn && !targetConnections.find((c) => c.id === targetConn.id)) setTargetConn(null);
    if (sourceConnections.length > 0 && !sourceConn) setSourceConn(sourceConnections[0]);
    if (targetConnections.length > 0 && !targetConn) setTargetConn(targetConnections[0]);
  }, [sourceConnections, targetConnections, sourceConn, targetConn]);

  // Auto-discover when create dialog opens and we have a source connection
  useEffect(() => {
    if (showStreamDialog && sourceConn && !editingStreamId) {
      handleDiscover();
    }
    if (!showStreamDialog) {
      resetStreamDialog();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showStreamDialog, editingStreamId]);

  useEffect(() => {
    if (showStreamDialog && sourceConn) {
      refreshCdcStatus();
    }
  }, [showStreamDialog, sourceConn, schema, refreshCdcStatus]);

  useEffect(() => {
    if (showStreamDialog && sourceConn && selectedTable) {
      refreshCdcStatus(selectedTable);
    }
  }, [selectedTable, showStreamDialog, sourceConn, refreshCdcStatus]);

  useEffect(() => {
    if (showStreamDialog && targetConn && selectedTable) {
      refreshTargetStatus(selectedTable);
    }
  }, [selectedTable, showStreamDialog, targetConn, resolvedTargetSchema, refreshTargetStatus]);

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
    openCreateDialog();
  }, [sourceConn, targetConn, openCreateDialog]);

  const loadStreams = useCallback(async () => {
    try {
      const [rows, summaryData] = await Promise.all([
        listReplicationStreams(),
        getReplicationSummary(),
      ]);
      setStreams(rows);
      setSummary(summaryData);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load streams");
    } finally {
      setStreamsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStreams();
  }, [loadStreams]);

  const handleSaveAndStart = useCallback(async () => {
    if (!sourceConn || !targetConn || !selectedTable) {
      toast.error("Select connections and a table");
      return;
    }
    if (!targetStatus?.ready) {
      toast.error("Migrate the selected table to the target before starting replication");
      return;
    }
    setLoading(true);
    const payload = {
      name: streamName || `${schema}.${selectedTable}`,
      source_connection_id: sourceConn.id,
      target_connection_id: targetConn.id,
      tables: [selectedTable],
      source_schema: schema || "dbo",
      target_schema: resolvedTargetSchema,
      mode: "cdc" as const,
    };

    try {
      const saved = editingStreamId
        ? await updateReplicationStream(editingStreamId, payload)
        : await createReplicationStream(payload);

      if (saved.concerns.some((c) => c.level === "blocker")) {
        toast.warning("Stream saved with blockers — resolve concerns before data flows");
        setStreams((prev) => {
          const without = prev.filter((s) => s.stream_id !== saved.stream_id);
          return [saved, ...without];
        });
        setShowStreamDialog(false);
        return;
      }

      try {
        const started = await startReplicationStream(saved.stream_id);
        setStreams((prev) => [
          started,
          ...prev.filter((s) => s.stream_id !== started.stream_id),
        ]);
        toast.success(
          editingStreamId
            ? `Replication updated and started for ${selectedTable}`
            : `Replication started for ${selectedTable}`,
        );
        setShowStreamDialog(false);
      } catch (startErr) {
        setStreams((prev) => {
          const without = prev.filter((s) => s.stream_id !== saved.stream_id);
          return [saved, ...without];
        });
        const msg =
          startErr instanceof Error ? startErr.message : "Failed to start replication";
        toast.error(`Stream saved but could not start: ${msg}`);
        setShowStreamDialog(false);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save stream";
      toast.error(
        editingStreamId ? `Failed to update stream: ${msg}` : `Failed to create stream: ${msg}`,
      );
    } finally {
      setLoading(false);
    }
  }, [
    sourceConn,
    targetConn,
    selectedTable,
    schema,
    resolvedTargetSchema,
    streamName,
    editingStreamId,
    targetStatus,
  ]);

  const handleDeleteStream = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      if (ACTIVE_STREAM_STATUSES.includes(deleteTarget.status)) {
        await stopReplicationStream(deleteTarget.stream_id);
      }
      await deleteReplicationStream(deleteTarget.stream_id);
      setStreams((prev) => prev.filter((s) => s.stream_id !== deleteTarget.stream_id));
      toast.success(`Deleted stream ${deleteTarget.name}`);
      setDeleteTarget(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete stream");
    }
  }, [deleteTarget]);

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
        );
      }
    } catch {
      toast.dismiss();
      toast.error("Could not test connections");
    }
  }, [sourceConn, targetConn]);

  const activeStreams = summary?.active_streams ?? streams.filter((s) =>
    ["CDC_STREAMING", "STARTING", "CDC_CATCHUP", "PAUSED"].includes(s.status),
  ).length;

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    const hasLive = summary?.live ?? streams.some((s) => s.is_active);
    const interval = hasLive ? 4_000 : 30_000;
    pollRef.current = setInterval(async () => {
      try {
        const [summaryData, rows] = await Promise.all([
          getReplicationSummary(),
          listReplicationStreams(),
        ]);
        setSummary(summaryData);
        setStreams(rows);
      } catch {
        /* ignore poll errors */
      }
    }, interval);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [summary?.live, streams]);

  const totalCaptured = summary?.events_captured ?? 0;
  const totalApplied = summary?.events_applied ?? 0;
  const queueDepth = summary?.queue_depth ?? 0;
  const pendingLag = summary?.pending_lag ?? 0;
  const kpiLive = summary?.live ?? false;

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

      <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-amber-950 dark:text-amber-100 text-xs leading-relaxed">
          <span className="font-medium">Preview feature.</span>{" "}
          Replication is still in progress and may not work as expected. Full functionality is
          planned for a future release.
        </p>
      </div>

      <div className="rounded-md border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm flex items-start gap-2">
        <Database className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
        <p className="text-blue-900 dark:text-blue-100 text-xs leading-relaxed">
          <span className="font-medium">CDC replication requires a migrated baseline.</span>{" "}
          Run a full table migration first, then add a stream here to apply ongoing SQL Server
          changes to PostgreSQL.
        </p>
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

      {/* Stats — sourced from /replication/summary with live runtime merge */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Active Streams</CardTitle>
            <Activity className={`h-4 w-4 ${activeStreams > 0 ? "text-emerald-500" : "text-muted-foreground"}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {summary ? `${summary.active_streams} / ${summary.total_streams}` : `${activeStreams} / ${streams.length}`}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {kpiLive ? "Live metrics updating" : streams.length === 0 ? "No streams configured" : "No active capture"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Commands Captured</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">{totalCaptured.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground mt-1">
              CDC events read from SQL Server{kpiLive ? " · live" : ""}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Commands Applied</CardTitle>
            <Activity className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-emerald-500">{totalApplied.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground mt-1">
              Synced to PostgreSQL{pendingLag > 0 ? ` · ${pendingLag} pending` : ""}
            </p>
          </CardContent>
        </Card>

        <Card className={queueDepth > 100 || pendingLag > 50 ? "border-amber-500/40" : ""}>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Queue / Lag</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">{queueDepth.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground mt-1">
              In-memory queue · lag {pendingLag.toLocaleString()}
            </p>
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
                    <Link
                      href={`/replication/${s.stream_id}`}
                      className="flex-1 min-w-0 group"
                    >
                      <p className="text-sm font-medium truncate group-hover:text-primary transition-colors">
                        {s.name}
                      </p>
                      <p className="text-xs text-muted-foreground font-mono">
                        {s.source_schema}.{tableName} → {s.target_schema}.{tableName.toLowerCase()}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        captured {s.events_captured?.toLocaleString()} · applied {s.events_applied?.toLocaleString()}
                        {(s.pending_lag ?? 0) > 0 && (
                          <span className="text-amber-400 ml-2">lag {s.pending_lag}</span>
                        )}
                        {s.concerns.length > 0 && (
                          <span className="text-amber-400 ml-2">{s.concerns.length} concern(s)</span>
                        )}
                      </p>
                    </Link>
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
                    {!ACTIVE_STREAM_STATUSES.includes(s.status) && (
                      <Button variant="ghost" size="sm" onClick={() => openEditDialog(s)} title="Edit stream">
                        <Pencil className="h-4 w-4" />
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" asChild title="View details">
                      <Link href={`/replication/${s.stream_id}`}>
                        <ChevronRight className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setDeleteTarget(s)}
                      title="Delete stream"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
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
      <Dialog open={showStreamDialog} onOpenChange={setShowStreamDialog}>
        <DialogContent className="w-full max-w-4xl sm:max-w-5xl flex flex-col p-0 gap-0 overflow-hidden max-h-[90vh]">
          <DialogHeader className="px-6 pt-6 pb-4 border-b shrink-0">
            <DialogTitle>{editingStreamId ? "Edit Replication Stream" : "Add Replication Stream"}</DialogTitle>
            <DialogDescription>
              Select a source table that has already been migrated to PostgreSQL, then stream CDC changes.
            </DialogDescription>
          </DialogHeader>

          <div className="px-6 py-5 space-y-5 flex-1 overflow-y-auto">
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-950 dark:text-amber-100">
              Replication is in active development and may not work as expected yet.
            </div>
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
            {targetChecking && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Checking whether the table exists on the target…
              </div>
            )}
            {!targetChecking && targetStatus && !targetStatus.ready && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100 flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
                <div className="space-y-2">
                  <p>{targetStatus.message}</p>
                  <Button variant="outline" size="sm" asChild>
                    <Link href="/migrations">Run migration first</Link>
                  </Button>
                </div>
              </div>
            )}
            {!targetChecking && targetStatus?.ready && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-600">
                {targetStatus.message}
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
                <p>Target: <span className="font-mono">{targetConn?.database}.{resolvedTargetSchema}.{selectedTable.toLowerCase()}</span></p>
              </div>
            )}
          </div>

          <DialogFooter className="px-6 py-4 border-t shrink-0">
            <Button variant="outline" onClick={() => setShowStreamDialog(false)}>Cancel</Button>
            <Button
              onClick={handleSaveAndStart}
              disabled={
                !selectedTable
                || loading
                || cdcChecking
                || targetChecking
                || !cdcStatus?.ready
                || !targetStatus?.ready
              }
            >
              <Play className="h-4 w-4 mr-2" />
              {editingStreamId ? "Save & Start" : "Create & Start"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete replication stream?</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `This removes "${deleteTarget.name}" and stops capture if it is still running.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDeleteStream}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
