"use client";

/**
 * Module: page.tsx
 * Purpose: Schema comparison — split-pane view with source on left and
 *          target on right, colour-coded by comparison status.
 *          Mismatched items expose inline diff details on the source side.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback } from "react";
import {
  Database,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Server,
  ArrowRight,
  Table2,
  Columns3,
  ListOrdered,
  FileCode2,
  FunctionSquare,
  FolderTree,
  GitCompare,
  ChevronDown,
  ChevronRight,
  Info,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { useConnections, type Connection } from "@/lib/ConnectionContext";
import { compareDatabases, listSchemas, testConnection, ApiError } from "@/lib/api";
import {
  probeConnection,
  formatUnreachableMessage,
  type ConnectionHealth,
} from "@/lib/connection-health";

interface ObjectCountPair {
  source: number;
  target: number;
}

interface CompareSummary {
  total_source_objects: number;
  total_target_objects: number;
  matched: number;
  source_only: number;
  target_only: number;
  partial_match: number;
  source_database: string;
  target_database: string;
  source_schema?: string;
  target_schema?: string;
  object_counts?: {
    tables?: ObjectCountPair;
    procedures?: ObjectCountPair;
    functions?: ObjectCountPair;
    indexes?: ObjectCountPair;
  };
}

interface CompareTreeItem {
  name: string;
  node_type: string;
  status: string;
  children: CompareTreeItem[];
  properties: Record<string, unknown>;
}

interface CompareResult {
  comparison_id: string;
  summary: CompareSummary;
  tree: CompareTreeItem[];
  source_tree: CompareTreeItem[];
  target_tree: CompareTreeItem[];
  duration_ms: number;
}

function fmtMs(ms: number): string {
  if (ms < 1) return "< 1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/** Backend MatchStatus is lowercase; UI compares uppercase labels. */
function normalizeStatus(status: string): string {
  return status.toUpperCase();
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function statusIcon(status: string) {
  switch (normalizeStatus(status)) {
    case "EXACT": return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />;
    case "SOURCE_ONLY": return <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />;
    case "TARGET_ONLY": return <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />;
    case "PARTIAL": return <AlertTriangle className="h-3.5 w-3.5 text-orange-500 shrink-0" />;
    default: return <AlertTriangle className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  }
}

function statusBadge(status: string) {
  const normalized = normalizeStatus(status);
  const map: Record<string, { variant: "secondary" | "destructive" | "outline"; className: string }> = {
    EXACT:       { variant: "secondary", className: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px]" },
    SOURCE_ONLY: { variant: "destructive", className: "text-[10px]" },
    TARGET_ONLY: { variant: "outline", className: "text-amber-500 border-amber-500/20 text-[10px]" },
    PARTIAL:     { variant: "outline", className: "text-orange-500 border-orange-500/20 text-[10px]" },
  };
  const v = map[normalized] || { variant: "outline" as const, className: "text-[10px]" };
  return <Badge variant={v.variant} className={v.className}>{normalized.replace("_", " ")}</Badge>;
}

function rowBg(status: string) {
  switch (normalizeStatus(status)) {
    case "EXACT": return "";
    case "SOURCE_ONLY": return "bg-red-500/5";
    case "TARGET_ONLY": return "bg-amber-500/5";
    case "PARTIAL": return "bg-orange-500/5";
    default: return "";
  }
}

function nodeTypeIcon(nodeType: string) {
  const t = nodeType.toLowerCase();
  if (t === "table") return <Table2 className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  if (t === "column") return <Columns3 className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  if (t === "index") return <ListOrdered className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  if (t === "procedure") return <FileCode2 className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  if (t === "function") return <FunctionSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  if (t === "category") return <FolderTree className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  return null;
}

function mismatchReason(item: CompareTreeItem): string {
  const props = item.properties || {};
  const status = normalizeStatus(item.status);
  if (status === "SOURCE_ONLY") return "Present in source but missing from target.";
  if (status === "TARGET_ONLY") return "Present in target but not found in source.";
  if (status === "PARTIAL") {
    const srcType = props.source_type ?? props.type;
    const tgtType = props.target_type;
    if (srcType && tgtType && srcType !== tgtType) {
      return `Type mismatch — source: ${srcType}, target: ${tgtType}`;
    }
    const childDiffs = item.children.filter((c) => normalizeStatus(c.status) !== "EXACT");
    if (childDiffs.length > 0) {
      return `${childDiffs.length} child object(s) differ: ${childDiffs.map((c) => c.name).slice(0, 3).join(", ")}${childDiffs.length > 3 ? "…" : ""}`;
    }
    return "Has differences in child objects.";
  }
  return "";
}

// ---------------------------------------------------------------------------
// Details panel (inline expansion for mismatched items)
// ---------------------------------------------------------------------------

function DetailsPanel({ item }: { item: CompareTreeItem }) {
  const reason = mismatchReason(item);
  const childDiffs = item.children.filter((c) => normalizeStatus(c.status) !== "EXACT");
  const props = item.properties || {};
  const rawDiffs = Array.isArray(props.differences) ? props.differences as Array<{
    property?: string;
    source?: unknown;
    target?: unknown;
    severity?: string;
  }> : [];
  const significantDiffs = rawDiffs.filter((d) => d.severity !== "info");

  return (
    <div className="mx-4 mb-2 rounded-md border border-border bg-muted/30 px-4 py-3 space-y-2 text-xs">
      <p className="font-semibold text-foreground">Mismatch Details — <span className="font-mono">{item.name}</span></p>
      {reason && <p className="text-muted-foreground">{reason}</p>}
      {significantDiffs.length > 0 && (
        <div>
          <p className="font-medium text-muted-foreground mb-1">Property differences:</p>
          <ul className="space-y-0.5 font-mono">
            {significantDiffs.map((d, i) => (
              <li key={i} className="text-muted-foreground">
                {d.property}: {String(d.source ?? "—")} → {String(d.target ?? "—")}
                {d.severity && d.severity !== "warning" && (
                  <span className="ml-1 text-red-400">({d.severity})</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {props.source_type != null && props.target_type != null && (
        <div className="grid grid-cols-2 gap-2">
          <div><span className="text-muted-foreground">Source type: </span><span className="font-mono text-foreground">{String(props.source_type)}</span></div>
          <div><span className="text-muted-foreground">Target type: </span><span className="font-mono text-foreground">{String(props.target_type)}</span></div>
        </div>
      )}
      {childDiffs.length > 0 && (
        <div>
          <p className="font-medium text-muted-foreground mb-1">Differing children:</p>
          <ul className="space-y-0.5">
            {childDiffs.map((c, i) => {
              const cSrc = c.properties?.source_type;
              const cTgt = c.properties?.target_type;
              return (
                <li key={i} className="flex items-center gap-2">
                  {statusIcon(c.status)}
                  <span className="font-mono">{c.name}</span>
                  {statusBadge(c.status)}
                  {cSrc != null && cTgt != null && (
                    <span className="text-muted-foreground">{String(cSrc)} → {String(cTgt)}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Side tree node
// ---------------------------------------------------------------------------

function SideTreeNode({
  item, depth, side, expandedNodes, toggleNode, detailsOpen, toggleDetails,
  sourceSchema, targetSchema, sourceDatabase, targetDatabase,
}: {
  item: CompareTreeItem;
  depth: number;
  side: "source" | "target";
  expandedNodes: Set<string>;
  toggleNode: (key: string) => void;
  detailsOpen: string | null;
  toggleDetails: (key: string | null) => void;
  sourceSchema: string;
  targetSchema: string;
  sourceDatabase: string;
  targetDatabase: string;
}) {
  const nodeKey = `${depth}-${item.name}`;
  const detailsKey = `details-${depth}-${item.name}`;
  const hasChildren = item.children && item.children.length > 0;
  const isExpanded = expandedNodes.has(nodeKey);
  const isDetailsOpen = detailsOpen === detailsKey;
  const itemStatus = normalizeStatus(item.status);
  const hasMismatch = itemStatus !== "EXACT";

  const displayName = (() => {
    const nodeType = item.node_type.toLowerCase();
    const props = item.properties || {};
    if (nodeType === "schema") {
      if (props.schema) return String(props.schema);
      if (props.source_schema && props.target_schema) {
        return side === "source" ? String(props.source_schema) : String(props.target_schema);
      }
      return side === "source" ? sourceSchema : targetSchema;
    }
    if (nodeType === "database") {
      if (props.database) return String(props.database);
      if (side === "target") {
        return String(props.target_database || targetDatabase || item.name);
      }
      return String(props.source_database || sourceDatabase || item.name);
    }
    if (nodeType === "column") {
      const sideType = side === "source"
        ? (props.source_type ?? props.data_type)
        : (props.target_type ?? props.data_type);
      if (sideType) {
        return `${item.name} (${String(sideType)})`;
      }
    }
    if (nodeType === "index") {
      const sideCols = side === "source"
        ? (props.source_columns ?? props.key_columns)
        : (props.target_columns ?? props.key_columns);
      if (Array.isArray(sideCols) && sideCols.length > 0) {
        return `${item.name} (${sideCols.join(", ")})`;
      }
    }
    return item.name;
  })();

  const isGhost =
    (side === "source" && itemStatus === "TARGET_ONLY") ||
    (side === "target" && itemStatus === "SOURCE_ONLY");

  if (isGhost) {
    return (
      <div className="flex items-center gap-2 py-1 text-sm" style={{ paddingLeft: `${12 + depth * 20}px` }}>
        <span className="w-4 shrink-0" />
        <span className="w-3.5 shrink-0" />
        <span className="flex-1 text-muted-foreground/30 italic text-xs">— not present —</span>
      </div>
    );
  }

  return (
    <div className={rowBg(item.status)}>
      <div
        className={`flex items-center gap-2 py-1 text-sm ${hasChildren ? "cursor-pointer" : ""} hover:bg-muted/30`}
        style={{ paddingLeft: `${12 + depth * 20}px` }}
        onClick={() => hasChildren && toggleNode(nodeKey)}
      >
        {hasChildren ? (
          <span className="text-xs text-muted-foreground w-4 shrink-0">
            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </span>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        {statusIcon(item.status)}
        {nodeTypeIcon(item.node_type)}
        <span className="flex-1 truncate">{displayName}</span>
        {itemStatus !== "EXACT" && statusBadge(item.status)}
        {side === "source" && hasMismatch && (
          <button
            onClick={(e) => { e.stopPropagation(); toggleDetails(isDetailsOpen ? null : detailsKey); }}
            className="ml-1 text-[10px] text-blue-400 hover:text-blue-300 underline underline-offset-2 shrink-0"
          >
            {isDetailsOpen ? "Hide" : "Details"}
          </button>
        )}
      </div>
      {side === "source" && isDetailsOpen && <DetailsPanel item={item} />}
      {hasChildren && isExpanded &&
        item.children.map((child, i) => (
          <SideTreeNode
            key={i}
            item={child}
            depth={depth + 1}
            side={side}
            expandedNodes={expandedNodes}
            toggleNode={toggleNode}
            detailsOpen={detailsOpen}
            toggleDetails={toggleDetails}
            sourceSchema={sourceSchema}
            targetSchema={targetSchema}
            sourceDatabase={sourceDatabase}
            targetDatabase={targetDatabase}
          />
        ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ComparisonPage() {
  const [sourceConn, setSourceConn] = useState<Connection | null>(null);
  const [targetConn, setTargetConn] = useState<Connection | null>(null);
  const [sourceSchema, setSourceSchema] = useState("dbo");
  const [targetSchema, setTargetSchema] = useState("public");
  const [sourceSchemas, setSourceSchemas] = useState<string[]>([]);
  const [targetSchemas, setTargetSchemas] = useState<string[]>([]);
  const [schemaMismatchWarning, setSchemaMismatchWarning] = useState<string | null>(null);
  const [targetEmptyWarning, setTargetEmptyWarning] = useState<string | null>(null);
  const [compareError, setCompareError] = useState<{ title: string; detail: string } | null>(null);
  const [comparing, setComparing] = useState(false);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [detailsOpen, setDetailsOpen] = useState<string | null>(null);
  const [sourceHealth, setSourceHealth] = useState<ConnectionHealth>({ status: "unknown", message: "" });
  const [targetHealth, setTargetHealth] = useState<ConnectionHealth>({ status: "unknown", message: "" });
  const [sourceConnError, setSourceConnError] = useState<string | null>(null);
  const [targetConnError, setTargetConnError] = useState<string | null>(null);

  const { sourceConnections, targetConnections } = useConnections();

  useEffect(() => {
    if (sourceConn && !sourceConnections.find((c) => c.id === sourceConn.id)) setSourceConn(null);
    if (targetConn && !targetConnections.find((c) => c.id === targetConn.id)) setTargetConn(null);
  }, [sourceConnections, targetConnections]);

  useEffect(() => {
    if (!sourceConn) {
      setSourceSchemas([]);
      setSourceHealth({ status: "unknown", message: "" });
      setSourceConnError(null);
      return;
    }

    let cancelled = false;
    setSourceHealth({ status: "checking", message: "Checking source connection…", host: sourceConn.host, database: sourceConn.database });
    setSourceConnError(null);
    setSourceSchemas([]);

    (async () => {
      const health = await probeConnection(sourceConn.id, { host: sourceConn.host, database: sourceConn.database });
      if (cancelled) return;
      setSourceHealth(health);
      if (health.status !== "reachable") {
        setSourceConnError(formatUnreachableMessage(`Source "${sourceConn.name}"`, health));
        return;
      }
      try {
        const schemas = await listSchemas(sourceConn.id, sourceConn);
        if (!cancelled) {
          setSourceSchemas(schemas);
          if (schemas.length > 0 && !schemas.includes(sourceSchema)) setSourceSchema(schemas[0]);
        }
      } catch (err) {
        if (!cancelled) {
          setSourceConnError(err instanceof Error ? err.message : "Failed to list source schemas");
        }
      }
    })();

    return () => { cancelled = true; };
  }, [sourceConn]);

  useEffect(() => {
    if (!targetConn) {
      setTargetSchemas([]);
      setTargetEmptyWarning(null);
      setTargetHealth({ status: "unknown", message: "" });
      setTargetConnError(null);
      return;
    }

    let cancelled = false;
    setTargetHealth({ status: "checking", message: "Checking target connection…", host: targetConn.host, database: targetConn.database });
    setTargetConnError(null);
    setTargetEmptyWarning(null);
    setTargetSchemas([]);

    (async () => {
      const health = await probeConnection(targetConn.id, { host: targetConn.host, database: targetConn.database });
      if (cancelled) return;
      setTargetHealth(health);
      if (health.status !== "reachable") {
        setTargetConnError(formatUnreachableMessage(`Target "${targetConn.name}"`, health));
        return;
      }
      try {
        const schemas = await listSchemas(targetConn.id, targetConn);
        if (!cancelled) {
          setTargetSchemas(schemas);
          if (schemas.length > 0 && !schemas.includes(targetSchema)) setTargetSchema(schemas[0]);
          if (schemas.length === 0) {
            setTargetEmptyWarning(
              `Target database "${targetConn.database}" on ${targetConn.host} has no schemas. ` +
              `Run a migration first to populate the PostgreSQL schema before comparing.`
            );
          }
        }
      } catch (err) {
        if (!cancelled) {
          setTargetConnError(err instanceof Error ? err.message : "Failed to list target schemas");
        }
      }
    })();

    return () => { cancelled = true; };
  }, [targetConn]);

  useEffect(() => {
    if (!sourceSchema || targetSchemas.length === 0) {
      setSchemaMismatchWarning(null);
      return;
    }
    if (sourceSchema !== targetSchema) {
      setSchemaMismatchWarning(
        `Comparing source schema "${sourceSchema}" against target schema "${targetSchema}". ` +
          `Migrated tables are matched by name across these schemas.`
      );
    } else {
      setSchemaMismatchWarning(null);
    }
  }, [sourceSchema, targetSchema, targetSchemas]);

  const toggleNode = (key: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const handleCompare = useCallback(async () => {
    if (!sourceConn || !targetConn) {
      toast.info("Configure source and target connections in Settings first");
      return;
    }
    if (sourceHealth.status === "unreachable") {
      toast.error(sourceConnError ?? "Source database is not reachable");
      return;
    }
    if (targetHealth.status === "unreachable") {
      toast.error(targetConnError ?? "Target database is not reachable");
      return;
    }
    setComparing(true);
    setResult(null);
    setDetailsOpen(null);
    setCompareError(null);
    try {
      const res = (await compareDatabases({
        source_connection_id: sourceConn.id,
        target_connection_id: targetConn.id,
        source_schema: sourceSchema,
        target_schema: targetSchema,
      })) as unknown as CompareResult;
      setResult({
        ...res,
        source_tree: (res.source_tree ?? res.tree) as CompareTreeItem[],
        target_tree: (res.target_tree ?? []) as CompareTreeItem[],
      });
      const keys = new Set<string>();
      (res.source_tree ?? []).forEach((t) => keys.add(`0-${t.name}`));
      (res.target_tree ?? []).forEach((t) => keys.add(`0-${t.name}`));
      setExpandedNodes(keys);

      if (
        (res.summary.total_source_objects ?? 0) > 0 &&
        (res.summary.total_target_objects ?? 0) === 0
      ) {
        setTargetEmptyWarning(
          `No objects found in target schema "${targetSchema}". ` +
          `If migration completed, confirm tables were written to "${targetSchema}" (source was "${sourceSchema}").`
        );
      } else {
        setTargetEmptyWarning(null);
      }

      toast.success(`Comparison completed in ${fmtMs(res.duration_ms)}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 422) {
          setCompareError({
            title: "Connection not configured",
            detail: err.message + " — go to Settings to add your source and target connections.",
          });
        } else if (err.status === 502) {
          setCompareError({
            title: "Cannot reach database",
            detail: "Could not connect to one or both databases. Verify the host, port, and credentials in Settings.",
          });
        } else if (err.status === 404) {
          setCompareError({
            title: "API not found",
            detail: "The comparison API endpoint was not found. Make sure the backend server is running on port 8508.",
          });
        } else {
          setCompareError({ title: "Comparison failed", detail: err.message });
        }
        toast.error(err.status === 422 ? "Connection not configured" : err.status === 502 ? "Cannot reach database" : "Comparison failed");
      } else {
        const msg = err instanceof Error ? err.message : "Comparison failed";
        setCompareError({ title: "Comparison failed", detail: msg });
        toast.error(msg);
      }
    } finally {
      setComparing(false);
    }
  }, [sourceConn, targetConn, sourceSchema, targetSchema, sourceHealth, targetHealth, sourceConnError, targetConnError]);

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
        toast.error(`Source: ${src.message}, Target: ${tgt.message}`);
      }
    } catch {
      toast.dismiss();
      toast.error("Could not test connections");
    }
  }, [sourceConn, targetConn]);

  const sourceDatabase =
    result?.summary.source_database || sourceConn?.database || "SQL Server";
  const targetDatabase =
    result?.summary.target_database || targetConn?.database || "PostgreSQL";

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Schema Comparison</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Compare tables, columns, indexes, stored procedures, and functions between SQL Server and PostgreSQL
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleTestConnections}>
            Test Connections
          </Button>
          <Button
            onClick={handleCompare}
            disabled={
              comparing ||
              !sourceConn ||
              !targetConn ||
              sourceHealth.status === "checking" ||
              targetHealth.status === "checking" ||
              sourceHealth.status === "unreachable" ||
              targetHealth.status === "unreachable"
            }
          >
            {comparing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            {comparing ? "Comparing..." : "Compare"}
          </Button>
        </div>
      </div>

      {(sourceConnError || targetConnError) && (
        <div className="space-y-2">
          {sourceConnError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-start gap-2">
              <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Source SQL Server unreachable</p>
                <p>{sourceConnError}</p>
                {sourceConn && (
                  <p className="text-xs mt-1 opacity-80">
                    Endpoint: {sourceConn.host}:{sourceConn.port}/{sourceConn.database}
                  </p>
                )}
              </div>
            </div>
          )}
          {targetConnError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-start gap-2">
              <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Target PostgreSQL unreachable</p>
                <p>{targetConnError}</p>
                {targetConn && (
                  <p className="text-xs mt-1 opacity-80">
                    Endpoint: {targetConn.host}:{targetConn.port}/{targetConn.database}
                  </p>
                )}
              </div>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            <a href="/settings" className="underline">Update connections in Settings</a> or start the database containers with{" "}
            <code className="text-[10px]">docker-compose up</code>.
          </p>
        </div>
      )}

      {(sourceHealth.status === "checking" || targetHealth.status === "checking") && !sourceConnError && !targetConnError && (
        <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Verifying database connections…
        </div>
      )}

      {/* Connection + schema selectors */}
      <div className="space-y-1.5">
      <div className="flex flex-wrap gap-x-6 gap-y-3 items-end">
        {/* Source side */}
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground flex items-center gap-1">
            <Server className="h-3 w-3" /> Source (SQL Server only)
            {sourceConnections.length === 0 && (
              <span className="text-amber-400 text-[10px] ml-1">— no source connections (add in Settings)</span>
            )}
          </Label>
          <select
            value={sourceConn?.id || ""}
            onChange={(e) => {
              const c = sourceConnections.find((c) => c.id === e.target.value);
              setSourceConn(c ?? null);
            }}
            className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm min-w-[200px]"
          >
            {sourceConnections.length === 0
              ? <option value="">— no SQL Server connections —</option>
              : <option value="">— select source —</option>
            }
            {sourceConnections.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.database} on {c.host})</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Source Schema</Label>
          {sourceSchemas.length > 0 ? (
            <select
              value={sourceSchema}
              onChange={(e) => setSourceSchema(e.target.value)}
              className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm min-w-[120px]"
            >
              {sourceSchemas.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (
            <input
              value={sourceSchema}
              onChange={(e) => setSourceSchema(e.target.value)}
              placeholder="dbo"
              className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm w-28"
            />
          )}
        </div>

        <ArrowRight className="h-4 w-4 text-muted-foreground mb-2" />

        {/* Target side */}
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground flex items-center gap-1">
            <Database className="h-3 w-3" /> Target (PostgreSQL only)
            {targetConnections.length === 0 && (
              <span className="text-amber-400 text-[10px] ml-1">— no target connections (add in Settings)</span>
            )}
          </Label>
          <select
            value={targetConn?.id || ""}
            onChange={(e) => {
              const c = targetConnections.find((c) => c.id === e.target.value);
              setTargetConn(c ?? null);
            }}
            className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm min-w-[200px]"
          >
            {targetConnections.length === 0
              ? <option value="">— no PostgreSQL connections —</option>
              : <option value="">— select target —</option>
            }
            {targetConnections.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.database} on {c.host})</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Target Schema</Label>
          {targetSchemas.length > 0 ? (
            <select
              value={targetSchema}
              onChange={(e) => setTargetSchema(e.target.value)}
              className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm min-w-[120px]"
            >
              {targetSchemas.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (
            <input
              value={targetSchema}
              onChange={(e) => setTargetSchema(e.target.value)}
              placeholder="public"
              className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm w-28"
            />
          )}
        </div>
        <Button
          onClick={handleCompare}
          disabled={
            comparing ||
            !sourceConn ||
            !targetConn ||
            sourceHealth.status !== "reachable" ||
            targetHealth.status !== "reachable"
          }
        >
          {comparing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <GitCompare className="h-4 w-4 mr-2" />}
          {comparing ? "Comparing..." : "Compare Schemas"}
        </Button>
      </div>
      {targetSchemas.length > 0 && (
        <p className="text-[10px] text-muted-foreground">
          {targetSchemas.length} PostgreSQL schema(s) loaded for target
        </p>
      )}
      </div>

      {/* Inline compare error */}
      {compareError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 flex items-start gap-3">
          <XCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-red-400">{compareError.title}</p>
            <p className="text-sm text-red-300 mt-0.5">{compareError.detail}</p>
          </div>
          <button onClick={() => setCompareError(null)} className="text-red-400 hover:text-red-300 shrink-0">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Schema mismatch warning */}
      {schemaMismatchWarning && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-400 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {schemaMismatchWarning}
        </div>
      )}

      {/* Target empty warning */}
      {targetEmptyWarning && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm flex items-start gap-2">
          <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-red-400 mb-0.5">Target schema appears empty</p>
            <p className="text-red-300">{targetEmptyWarning}</p>
            <a href="/migrations" className="text-xs text-blue-400 underline underline-offset-2 mt-1 inline-block">Go to Migrations →</a>
          </div>
        </div>
      )}

      {/* No connections hint */}
      {(sourceConnections.length === 0 || targetConnections.length === 0) && (
        <p className="text-xs text-muted-foreground">
          {sourceConnections.length === 0 && "Add a source (SQL Server) connection. "}
          {targetConnections.length === 0 && "Add a target (PostgreSQL) connection. "}
          <a href="/settings" className="underline">Configure connections</a> to enable comparison.
        </p>
      )}

      {/* Summary stats */}
      {result && (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Matched</CardTitle></CardHeader>
              <CardContent><div className="text-2xl font-bold text-emerald-500">{result.summary.matched}</div></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Source Only</CardTitle></CardHeader>
              <CardContent><div className="text-2xl font-bold text-destructive">{result.summary.source_only}</div></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Target Only</CardTitle></CardHeader>
              <CardContent><div className="text-2xl font-bold text-amber-500">{result.summary.target_only}</div></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Partial Match</CardTitle></CardHeader>
              <CardContent><div className="text-2xl font-bold text-orange-500">{result.summary.partial_match}</div></CardContent>
            </Card>
          </div>
          {result.summary.object_counts && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
              {([
                ["tables", "Tables", Table2],
                ["procedures", "Stored Procedures", FileCode2],
                ["functions", "Functions", FunctionSquare],
                ["indexes", "Indexes", ListOrdered],
              ] as const).map(([key, label, Icon]) => {
                const counts = result.summary.object_counts?.[key];
                if (!counts) return null;
                return (
                  <div key={key} className="rounded-md border border-border px-3 py-2 flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="font-medium">{label}</span>
                    <span className="ml-auto text-muted-foreground font-mono">
                      {counts.source} → {counts.target}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* Legend */}
      {result && (
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Exact match</span>
          <span className="flex items-center gap-1"><XCircle className="h-3.5 w-3.5 text-red-500" /> Source only</span>
          <span className="flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5 text-amber-500" /> Target only</span>
          <span className="flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5 text-orange-500" /> Partial match</span>
          <span className="flex items-center gap-1 ml-auto text-blue-400">
            <Info className="h-3.5 w-3.5" /> <strong>Details</strong> = show diff on mismatched source objects
          </span>
        </div>
      )}

      {/* Split comparison pane */}
      {result && (
        <div className="grid grid-cols-2 gap-0 border border-border rounded-lg overflow-hidden">
          {/* Source panel */}
          <div>
            <div className="flex items-center gap-2 px-4 py-2.5 bg-muted/40 border-b border-border">
              <Server className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold">
                Source — {sourceDatabase}
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                  ({result.summary.source_schema || sourceSchema})
                </span>
              </span>
              <Badge variant="outline" className="ml-auto text-[10px]">{result.summary.total_source_objects} objects</Badge>
            </div>
            <div className="overflow-y-auto max-h-[560px]">
              {(result.source_tree.length > 0 ? result.source_tree : result.tree).map((item, i) => (
                <SideTreeNode
                  key={i}
                  item={item}
                  depth={0}
                  side="source"
                  expandedNodes={expandedNodes}
                  toggleNode={toggleNode}
                  detailsOpen={detailsOpen}
                  toggleDetails={setDetailsOpen}
                  sourceSchema={sourceSchema}
                  targetSchema={targetSchema}
                  sourceDatabase={sourceDatabase}
                  targetDatabase={targetDatabase}
                />
              ))}
            </div>
          </div>

          {/* Target panel */}
          <div className="border-l border-border">
            <div className="flex items-center gap-2 px-4 py-2.5 bg-muted/40 border-b border-border">
              <Database className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold">
                Target — {targetDatabase}
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                  ({result.summary.target_schema || targetSchema})
                </span>
              </span>
              <Badge variant="outline" className="ml-auto text-[10px]">{result.summary.total_target_objects} objects</Badge>
            </div>
            <div className="overflow-y-auto max-h-[560px]">
              {result.target_tree.length > 0 ? (
                result.target_tree.map((item, i) => (
                  <SideTreeNode
                    key={i}
                    item={item}
                    depth={0}
                    side="target"
                    expandedNodes={expandedNodes}
                    toggleNode={toggleNode}
                    detailsOpen={detailsOpen}
                    toggleDetails={setDetailsOpen}
                    sourceSchema={sourceSchema}
                    targetSchema={targetSchema}
                    sourceDatabase={sourceDatabase}
                    targetDatabase={targetDatabase}
                  />
                ))
              ) : (
                <p className="px-4 py-6 text-sm text-muted-foreground text-center">
                  No objects found in target schema &quot;{result.summary.target_schema || targetSchema}&quot; on PostgreSQL.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Duration */}
      {result && (
        <p className="text-xs text-muted-foreground text-right">
          Completed in {fmtMs(result.duration_ms)} · comparison ID: {result.comparison_id.slice(0, 8)}…
        </p>
      )}

      {!result && !comparing && !compareError && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Database className="h-16 w-16 text-muted-foreground/30 mb-4" />
            <h2 className="text-xl font-semibold text-muted-foreground mb-2">No Comparison Data</h2>
            <p className="text-sm text-muted-foreground/70 text-center max-w-md">
              Select a SQL Server source connection and a PostgreSQL target connection, choose schemas, then run Compare.
            </p>
            <div className="flex gap-3 mt-6">
              <Button variant="default" asChild><a href="/settings">Configure Connections</a></Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
