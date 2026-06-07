/**
 * Module: app/schema-compare/[projectId]/page.tsx
 * Purpose: Side-by-side schema comparison: source objects | target objects + diff tree.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import {
  GitCompare,
  Loader2,
  XCircle,
  ChevronDown,
  ChevronRight,
  ArrowLeft,
  RefreshCw,
  Database,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getProjects,
  getConnections,
  compareDatabases,
  discoverSchema,
  listSchemas,
  type Project,
  type CompareResponse,
  type ConnectionResponse,
} from "@/lib/api";
import { CONNECTIONS_UPDATED_EVENT } from "@/lib/connection-store";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function DiffBadge({ status }: { status: string }) {
  if (status === "match")
    return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs">MATCH</Badge>;
  if (status === "missing_target")
    return <Badge variant="destructive" className="text-xs">MISSING IN TARGET</Badge>;
  if (status === "missing_source")
    return <Badge className="bg-slate-500/15 text-slate-400 border-slate-500/30 text-xs">EXTRA IN TARGET</Badge>;
  return <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30 text-xs">MISMATCH</Badge>;
}

// ---------------------------------------------------------------------------
// Tree node rendering
// ---------------------------------------------------------------------------

type TreeNode = {
  name: string;
  status?: string;
  source_type?: string;
  target_type?: string;
  children?: TreeNode[];
  [key: string]: unknown;
};

function TreeNodeRow({ node, depth = 0 }: { node: TreeNode; depth?: number }) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = node.children && node.children.length > 0;
  return (
    <>
      <tr
        className="border-b border-border hover:bg-muted/20 cursor-pointer"
        onClick={() => hasChildren && setOpen(!open)}
      >
        <td className="px-3 py-1.5 text-sm font-mono" style={{ paddingLeft: `${12 + depth * 20}px` }}>
          <span className="flex items-center gap-1.5">
            {hasChildren ? (
              open ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                   : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            ) : <span className="w-3.5" />}
            {node.name}
          </span>
        </td>
        <td className="px-3 py-1.5 text-xs text-muted-foreground">{node.source_type ?? ""}</td>
        <td className="px-3 py-1.5 text-xs text-muted-foreground">{node.target_type ?? ""}</td>
        <td className="px-3 py-1.5">{node.status && <DiffBadge status={node.status} />}</td>
      </tr>
      {open && hasChildren && node.children!.map((child, i) => (
        <TreeNodeRow key={i} node={child} depth={depth + 1} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Object list panel (source or target)
// ---------------------------------------------------------------------------

type DiscoveredObject = { name: string; type: string; schema: string };

function ObjectPanel({
  title,
  icon: Icon,
  dbName,
  connName,
  items,
  loading,
  error,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  dbName: string;
  connName: string;
  items: DiscoveredObject[];
  loading: boolean;
  error?: string | null;
}) {
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [search, setSearch] = useState("");

  const types = Array.from(new Set(items.map((i) => i.type)));
  const filtered = items.filter((item) => {
    const matchType = typeFilter === "ALL" || item.type.toLowerCase() === typeFilter.toLowerCase();
    const matchText = !search || item.name.toLowerCase().includes(search.toLowerCase()) || item.schema.toLowerCase().includes(search.toLowerCase());
    return matchType && matchText;
  });

  const countByType = types.reduce<Record<string, number>>((acc, t) => {
    acc[t] = items.filter((i) => i.type === t).length;
    return acc;
  }, {});

  return (
    <Card className="flex flex-col min-h-0">
      <CardHeader className="pb-2 shrink-0">
        <CardTitle className="text-sm flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
          {title}
        </CardTitle>
        <CardDescription className="text-xs">
          {connName ? <><span className="font-medium text-foreground">{connName}</span> · </> : ""}
          {dbName ? <span className="font-mono">{dbName}</span> : "—"}
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0 flex-1 flex flex-col min-h-0">
        {loading && (
          <div className="flex justify-center items-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}
        {error && !loading && (
          <div className="flex items-center gap-2 px-4 py-3 text-xs text-destructive">
            <XCircle className="h-3.5 w-3.5 shrink-0" />
            {error}
          </div>
        )}
        {!loading && !error && items.length > 0 && (
          <>
            {/* Type counts */}
            <div className="flex flex-wrap gap-1.5 px-3 pb-2">
              {Object.entries(countByType).map(([type, count]) => (
                <Badge key={type} variant="outline" className="text-[10px] capitalize gap-1 cursor-pointer"
                  onClick={() => setTypeFilter(typeFilter === type ? "ALL" : type)}>
                  {type}: {count}
                </Badge>
              ))}
            </div>
            {/* Search */}
            <div className="px-3 pb-2">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter by name…"
                className="w-full h-7 rounded-md border border-input bg-background px-2 text-xs"
              />
            </div>
            {/* List */}
            <div className="overflow-y-auto flex-1" style={{ maxHeight: "320px" }}>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/30 sticky top-0">
                    <th className="px-3 py-1.5 text-left text-[10px] font-semibold text-muted-foreground">Schema</th>
                    <th className="px-3 py-1.5 text-left text-[10px] font-semibold text-muted-foreground">Name</th>
                    <th className="px-3 py-1.5 text-left text-[10px] font-semibold text-muted-foreground">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((obj, i) => (
                    <tr key={i} className="border-b border-border hover:bg-muted/20">
                      <td className="px-3 py-1 text-muted-foreground font-mono">{obj.schema}</td>
                      <td className="px-3 py-1 font-medium truncate max-w-[160px]">{obj.name}</td>
                      <td className="px-3 py-1 capitalize text-muted-foreground">{obj.type}</td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">
                        No objects match filter
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground gap-2">
            <Database className="h-8 w-8 opacity-30" />
            <p className="text-xs">No objects discovered</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SchemaComparePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [comparison, setComparison] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Source and target object lists from discovery
  const [srcItems, setSrcItems] = useState<DiscoveredObject[]>([]);
  const [tgtItems, setTgtItems] = useState<DiscoveredObject[]>([]);
  const [srcLoading, setSrcLoading] = useState(false);
  const [tgtLoading, setTgtLoading] = useState(false);
  const [srcError, setSrcError] = useState<string | null>(null);
  const [tgtError, setTgtError] = useState<string | null>(null);

  const srcConn = connections.find((c) => c.id === project?.source_connection_id);
  const tgtConn = connections.find((c) => c.id === project?.target_connection_id);

  const loadProject = useCallback(async () => {
    if (!projectId) return;
    try {
      const [all, conns] = await Promise.all([getProjects(), getConnections().catch(() => [])]);
      const found = all.find((p) => p.id === projectId);
      setProject(found ?? null);
      setConnections(conns);
    } catch {
      toast.error("Failed to load project");
    } finally {
      setInitialLoading(false);
    }
  }, [projectId]);

  useEffect(() => { loadProject(); }, [loadProject]);

  useEffect(() => {
    window.addEventListener(CONNECTIONS_UPDATED_EVENT, loadProject);
    return () => window.removeEventListener(CONNECTIONS_UPDATED_EVENT, loadProject);
  }, [loadProject]);

  // Auto-discover source + target objects when project loads
  useEffect(() => {
    if (!project?.source_connection_id || !project?.target_connection_id) return;

    const discoverSide = async (connId: string, type: "source" | "target") => {
      const setLoad = type === "source" ? setSrcLoading : setTgtLoading;
      const setErr = type === "source" ? setSrcError : setTgtError;
      const setItems = type === "source" ? setSrcItems : setTgtItems;
      setLoad(true);
      setErr(null);
      try {
        const schemas = await listSchemas(connId).catch(() => [type === "source" ? "dbo" : "public"]);
        const schemasToScan = schemas.length > 0 ? schemas : [type === "source" ? "dbo" : "public"];
        const results = await Promise.all(schemasToScan.map((s) => discoverSchema(connId, s, type)));
        const items = results.flatMap((r) => (r.items as DiscoveredObject[]) ?? []);
        setItems(items);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Discovery failed");
      } finally {
        setLoad(false);
      }
    };

    discoverSide(project.source_connection_id, "source");
    discoverSide(project.target_connection_id, "target");
  }, [project?.source_connection_id, project?.target_connection_id]);

  const runComparison = useCallback(async () => {
    if (!project?.source_connection_id || !project?.target_connection_id) {
      toast.error("Project needs both source and target connections");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await compareDatabases({
        source_connection_id: project.source_connection_id,
        target_connection_id: project.target_connection_id,
      });
      setComparison(result);
      toast.success("Schema comparison complete");
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : "Comparison failed";
      const msg = raw.includes("502") || raw.toLowerCase().includes("connect")
        ? "Could not reach one or both databases. Verify host/port settings and that the databases are running."
        : raw;
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [project]);

  const refreshDiscovery = useCallback(() => {
    if (!project?.source_connection_id || !project?.target_connection_id) return;
    setSrcItems([]);
    setTgtItems([]);
    const discoverSide = async (connId: string, type: "source" | "target") => {
      const setLoad = type === "source" ? setSrcLoading : setTgtLoading;
      const setErr = type === "source" ? setSrcError : setTgtError;
      const setItems = type === "source" ? setSrcItems : setTgtItems;
      setLoad(true);
      setErr(null);
      try {
        const schemas = await listSchemas(connId).catch(() => [type === "source" ? "dbo" : "public"]);
        const schemasToScan = schemas.length > 0 ? schemas : [type === "source" ? "dbo" : "public"];
        const results = await Promise.all(schemasToScan.map((s) => discoverSchema(connId, s, type)));
        setItems(results.flatMap((r) => (r.items as DiscoveredObject[]) ?? []));
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Discovery failed");
      } finally {
        setLoad(false);
      }
    };
    discoverSide(project.source_connection_id, "source");
    discoverSide(project.target_connection_id, "target");
  }, [project]);

  if (initialLoading) {
    return (
      <div className="flex justify-center p-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const tree = (comparison?.tree ?? []) as TreeNode[];
  const summary = comparison?.summary as Record<string, number | string> | undefined;

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Schema Comparison"
        description={project?.name ? `Project: ${project.name}` : ""}
      >
        <Button variant="outline" size="sm" asChild>
          <Link href="/projects">
            <ArrowLeft className="h-4 w-4 mr-1" /> Projects
          </Link>
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={refreshDiscovery}
          disabled={srcLoading || tgtLoading}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${(srcLoading || tgtLoading) ? "animate-spin" : ""}`} />
          Rescan
        </Button>
        <Button
          size="sm"
          onClick={runComparison}
          disabled={loading || !project?.source_connection_id}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <GitCompare className="h-4 w-4 mr-1" />
          )}
          {comparison ? "Re-compare" : "Compare"}
        </Button>
      </PageHeader>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Side-by-side source vs target discovery */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ObjectPanel
          title="Source Database (SQL Server)"
          icon={Server}
          connName={srcConn?.name ?? ""}
          dbName={srcConn?.database ?? project?.source_connection_id?.slice(0, 8) ?? ""}
          items={srcItems}
          loading={srcLoading}
          error={srcError}
        />
        <ObjectPanel
          title="Target Database (PostgreSQL)"
          icon={Database}
          connName={tgtConn?.name ?? ""}
          dbName={tgtConn?.database ?? project?.target_connection_id?.slice(0, 8) ?? ""}
          items={tgtItems}
          loading={tgtLoading}
          error={tgtError}
        />
      </div>

      {/* Summary stats from comparison */}
      {comparison && summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(summary).filter(([k]) => !["source_database", "target_database"].includes(k)).map(([key, val]) => (
            <Card key={key}>
              <CardContent className="pt-4">
                <div className="text-2xl font-bold">{String(val)}</div>
                <div className="text-xs text-muted-foreground capitalize mt-1">
                  {key.replace(/_/g, " ")}
                </div>
              </CardContent>
            </Card>
          ))}
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold">{comparison.duration_ms} ms</div>
              <div className="text-xs text-muted-foreground mt-1">Comparison duration</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Diff tree */}
      {comparison && tree.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Object Differences</CardTitle>
            <CardDescription className="text-xs">
              Expand nodes to see column-level differences between source and target
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Object</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Source Type</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Target Type</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {tree.map((node, i) => (
                    <TreeNodeRow key={i} node={node} depth={0} />
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : !comparison ? (
        <EmptyState
          icon={GitCompare}
          title="No diff comparison yet"
          description={
            project?.source_connection_id && project?.target_connection_id
              ? "Click Compare above to analyse schema differences between source and target."
              : "Assign source and target connections to this project first."
          }
          actionLabel={
            project?.source_connection_id && project?.target_connection_id
              ? "Run Comparison"
              : undefined
          }
          onAction={
            project?.source_connection_id && project?.target_connection_id
              ? runComparison
              : undefined
          }
        />
      ) : null}
    </div>
  );
}
