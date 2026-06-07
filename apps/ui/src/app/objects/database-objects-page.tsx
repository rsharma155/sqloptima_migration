"use client";

/**
 * Module: page.tsx
 * Purpose: Discovered objects — tree view with schema explorer and dependency graph.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Search,
  Database,
  FolderTree,
  Loader2,
  Table2,
  Columns3,
  Server,
  Code2,
  ChevronRight,
  ChevronDown,
  Key,
  Link2,
  Zap,
  List,
  RefreshCw,
  AlertTriangle,
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
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
  discoverSchema,
  listSchemas,
  getObjectDefinition,
  getDependencyGraph,
  type DiscoveryResult,
  type ObjectDefinitionResult,
  type DependencyGraphResponse,
} from "@/lib/api";
import { useConnections, type Connection } from "@/lib/ConnectionContext";
import {
  probeConnection,
  formatUnreachableMessage,
  type ConnectionHealth,
} from "@/lib/connection-health";
import { DependencyGraph } from "@/components/objects/dependency-graph";

interface DiscoveredObject {
  name: string;
  type: string;
  schema: string;
}

interface TableDetails {
  columns: string[];
  keys: string[];
  constraints: string[];
  triggers: string[];
  indexes: string[];
}

type ConnectorType = "source" | "target";
type ActiveTab = "objects" | "graph";

// ---------------------------------------------------------------------------
// DDL parser
// ---------------------------------------------------------------------------

function parseTableDetails(ddl: string): TableDetails {
  const columns: string[] = [];
  const keys: string[] = [];
  const constraints: string[] = [];
  const indexes: string[] = [];
  const triggers: string[] = [];

  const lines = ddl.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  let inBody = false;
  let depth = 0;

  for (const line of lines) {
    const upper = line.toUpperCase();
    if (/CREATE\s+TABLE/i.test(line)) inBody = true;
    if (inBody) {
      depth += (line.match(/\(/g) || []).length;
      depth -= (line.match(/\)/g) || []).length;
    }
    if (/CREATE\s+(UNIQUE\s+)?INDEX/i.test(line)) { indexes.push(line.replace(/,$/, "")); continue; }
    if (/CREATE\s+(OR\s+REPLACE\s+)?TRIGGER/i.test(line)) { triggers.push(line.replace(/,$/, "")); continue; }
    if (!inBody || depth <= 0) continue;
    const clean = line.replace(/,$/, "").trim();
    if (!clean || clean === "(") continue;
    if (/^(PRIMARY\s+KEY|FOREIGN\s+KEY|CONSTRAINT\s+\S+\s+(PRIMARY|FOREIGN|UNIQUE|CHECK))/i.test(clean)) {
      keys.push(clean);
    } else if (/^CONSTRAINT/i.test(clean)) {
      constraints.push(clean);
    } else if (/^(UNIQUE|CHECK)\s*\(/i.test(clean)) {
      constraints.push(clean);
    } else if (/^INDEX/i.test(clean)) {
      indexes.push(clean);
    } else if (!/^(CREATE|ALTER|GO|--)/i.test(upper)) {
      const parts = clean.split(/\s+/);
      if (parts.length >= 2) {
        const colName = parts[0].replace(/[[\]`"]/g, "");
        const colType = parts.slice(1).join(" ").replace(/,$/, "");
        if (colName) columns.push(`${colName}  ${colType}`);
      }
    }
  }
  return { columns, keys, constraints, triggers, indexes };
}

// ---------------------------------------------------------------------------
// Sub-section
// ---------------------------------------------------------------------------

function TreeSubSection({
  title, items, icon: Icon, emptyLabel,
}: {
  title: string; items: string[]; icon: React.ComponentType<{ className?: string }>; emptyLabel: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="ml-4">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground w-full text-left"
      >
        {open ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
        <Icon className="h-3 w-3 shrink-0" />
        <span className="font-medium">{title}</span>
        <Badge variant="outline" className="ml-1 text-[10px] px-1 py-0">{items.length}</Badge>
      </button>
      {open && (
        <div className="ml-5 space-y-0.5 py-1">
          {items.length === 0 ? (
            <p className="text-[11px] text-muted-foreground/60 italic">{emptyLabel}</p>
          ) : (
            items.map((item, i) => (
              <p key={i} className="text-[11px] font-mono text-muted-foreground truncate" title={item}>{item}</p>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Object row
// ---------------------------------------------------------------------------

function ObjectRow({
  obj, connectionId, isSelected, onSelect,
}: {
  obj: DiscoveredObject; connectionId: string; isSelected: boolean; onSelect: (obj: DiscoveredObject) => void;
}) {
  const isTable = obj.type.toLowerCase() === "table";
  const [expanded, setExpanded] = useState(false);
  const [details, setDetails] = useState<TableDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);

  const typeIcon = (type: string) => {
    const t = type.toLowerCase();
    if (t === "table") return <Table2 className="h-3.5 w-3.5 text-blue-400 shrink-0" />;
    if (t === "view") return <Columns3 className="h-3.5 w-3.5 text-purple-400 shrink-0" />;
    return <Code2 className="h-3.5 w-3.5 text-amber-400 shrink-0" />;
  };

  const handleExpand = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!expanded && !details) {
      setLoadingDetails(true);
      try {
        const def: ObjectDefinitionResult = await getObjectDefinition(connectionId, obj.schema, obj.name, obj.type);
        setDetails(parseTableDetails(def.definition));
      } catch {
        toast.error(`Failed to load details for ${obj.name}`);
      } finally {
        setLoadingDetails(false);
      }
    }
    setExpanded((v) => !v);
  };

  return (
    <div>
      <div
        className={`flex items-center gap-2 pl-8 pr-3 py-1.5 cursor-pointer hover:bg-muted/40 transition-colors ${isSelected ? "bg-primary/5 border-l-2 border-primary" : ""}`}
        onClick={() => onSelect(obj)}
      >
        {isTable ? (
          <button
            onClick={handleExpand}
            className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
          >
            {loadingDetails ? <Loader2 className="h-3 w-3 animate-spin" /> : expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        {typeIcon(obj.type)}
        <span className="text-sm flex-1 truncate">{obj.name}</span>
        <Badge variant="outline" className="text-[10px] shrink-0 capitalize">{obj.type.toLowerCase()}</Badge>
      </div>
      {expanded && details && (
        <div className="pl-12 pb-2 space-y-1 bg-muted/10">
          <TreeSubSection title="Columns" items={details.columns} icon={Columns3} emptyLabel="no columns" />
          <TreeSubSection title="Keys" items={details.keys} icon={Key} emptyLabel="no keys" />
          <TreeSubSection title="Constraints" items={details.constraints} icon={Link2} emptyLabel="no constraints" />
          <TreeSubSection title="Triggers" items={details.triggers} icon={Zap} emptyLabel="no triggers" />
          <TreeSubSection title="Indexes" items={details.indexes} icon={List} emptyLabel="no indexes" />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schema group
// ---------------------------------------------------------------------------

const TYPE_ORDER = ["table", "view", "procedure", "function"];

function TypeGroup({
  type, label, objects, connectionId, selectedObject, onSelect,
}: {
  type: string; label: string; objects: DiscoveredObject[]; connectionId: string;
  selectedObject: DiscoveredObject | null; onSelect: (obj: DiscoveredObject) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const typeIcon = () => {
    if (type === "table") return <Table2 className="h-3.5 w-3.5 text-blue-400" />;
    if (type === "view") return <Columns3 className="h-3.5 w-3.5 text-purple-400" />;
    return <Code2 className="h-3.5 w-3.5 text-amber-400" />;
  };
  return (
    <div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 pl-6 pr-3 py-1.5 hover:bg-muted/30 transition-colors text-xs text-muted-foreground"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {typeIcon()}
        <span className="flex-1 text-left font-medium">{label}</span>
        <Badge variant="outline" className="text-[10px] px-1 py-0">{objects.length}</Badge>
      </button>
      {expanded && objects.map((obj) => (
        <ObjectRow
          key={`${obj.schema}.${obj.name}`}
          obj={obj}
          connectionId={connectionId}
          isSelected={selectedObject?.name === obj.name && selectedObject?.schema === obj.schema}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

function SchemaGroup({
  schema, objects, connectionId, selectedObject, onSelect,
}: {
  schema: string; objects: DiscoveredObject[]; connectionId: string;
  selectedObject: DiscoveredObject | null; onSelect: (obj: DiscoveredObject) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const byType = useMemo(() => {
    const map = new Map<string, DiscoveredObject[]>();
    for (const obj of objects) {
      const key = obj.type.toLowerCase();
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(obj);
    }
    const sorted = new Map<string, DiscoveredObject[]>();
    for (const t of TYPE_ORDER) if (map.has(t)) sorted.set(t, map.get(t)!);
    for (const [k, v] of map) if (!sorted.has(k)) sorted.set(k, v);
    return sorted;
  }, [objects]);

  const typeLabel: Record<string, string> = {
    table: "Tables", view: "Views", procedure: "Stored Procedures", function: "Functions",
  };

  return (
    <div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 bg-muted/20 hover:bg-muted/40 transition-colors border-b border-border text-sm font-semibold"
      >
        {expanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
        <Database className="h-4 w-4 text-blue-400" />
        <span className="flex-1 text-left">{schema}</span>
        <Badge variant="secondary" className="text-[10px]">{objects.length}</Badge>
      </button>
      {expanded && (
        <div>
          {Array.from(byType.entries()).map(([type, objs]) => (
            <TypeGroup
              key={type}
              type={type}
              label={typeLabel[type] ?? (type.charAt(0).toUpperCase() + type.slice(1) + "s")}
              objects={objs}
              connectionId={connectionId}
              selectedObject={selectedObject}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ObjectsPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("objects");
  const [search, setSearch] = useState("");
  const [objects, setObjects] = useState<DiscoveredObject[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeConn, setActiveConn] = useState<Connection | null>(null);
  const [connType, setConnType] = useState<ConnectorType>("source");
  const [availableSchemas, setAvailableSchemas] = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<string>("__ALL__");
  const [selectedObject, setSelectedObject] = useState<DiscoveredObject | null>(null);
  const [definition, setDefinition] = useState<ObjectDefinitionResult | null>(null);
  const [defLoading, setDefLoading] = useState(false);

  // Dependency graph state
  const [graphData, setGraphData] = useState<DependencyGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [graphSchema, setGraphSchema] = useState("dbo");
  const [connHealth, setConnHealth] = useState<ConnectionHealth>({ status: "unknown", message: "" });
  const [schemaLoadError, setSchemaLoadError] = useState<string | null>(null);

  const { sourceConnections, targetConnections } = useConnections();
  const allConns = connType === "source" ? sourceConnections : targetConnections;

  useEffect(() => {
    if (allConns.length > 0) {
      const match = activeConn && allConns.find((c) => c.id === activeConn.id);
      if (!match) setActiveConn(allConns[0]);
    } else {
      setActiveConn(null);
    }
  }, [connType, allConns]);

  useEffect(() => {
    if (!activeConn) {
      setAvailableSchemas([]);
      setSelectedSchema("__ALL__");
      setConnHealth({ status: "unknown", message: "" });
      setSchemaLoadError(null);
      return;
    }

    let cancelled = false;
    setConnHealth({ status: "checking", message: "Checking connection…", host: activeConn.host, database: activeConn.database });
    setSchemaLoadError(null);
    setAvailableSchemas([]);

    (async () => {
      const health = await probeConnection(activeConn.id, {
        host: activeConn.host,
        database: activeConn.database,
      });
      if (cancelled) return;
      setConnHealth(health);

      if (health.status !== "reachable") {
        setSchemaLoadError(formatUnreachableMessage(activeConn.name, health));
        return;
      }

      try {
        const schemas = await listSchemas(activeConn.id, activeConn);
        if (!cancelled) {
          setAvailableSchemas(schemas);
          setSelectedSchema("__ALL__");
        }
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Failed to list schemas";
          setSchemaLoadError(msg);
        }
      }
    })();

    return () => { cancelled = true; };
  }, [activeConn]);

  const handleRescan = useCallback(async () => {
    if (!activeConn) {
      toast.info(`Configure a ${connType === "source" ? "SQL Server" : "PostgreSQL"} connection in Settings first`);
      return;
    }
    if (connHealth.status === "unreachable") {
      toast.error(schemaLoadError ?? formatUnreachableMessage(activeConn.name, connHealth));
      return;
    }
    setLoading(true);
    try {
      let schemas = availableSchemas;
      if (selectedSchema === "__ALL__" && schemas.length === 0) {
        try {
          schemas = await listSchemas(activeConn.id, activeConn);
          setAvailableSchemas(schemas);
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Failed to list schemas";
          setSchemaLoadError(msg);
          toast.error(msg);
          return;
        }
      }
      const schemasToScan =
        selectedSchema === "__ALL__" && schemas.length > 0
          ? schemas
          : [selectedSchema === "__ALL__" ? (connType === "source" ? "dbo" : "public") : selectedSchema];

      const results = await Promise.allSettled(
        schemasToScan.map((s) => discoverSchema(activeConn.id, s, connType)),
      );
      const succeeded = results.filter((r): r is PromiseFulfilledResult<DiscoveryResult> => r.status === "fulfilled");
      const failed = results.filter((r) => r.status === "rejected");
      if (failed.length > 0 && succeeded.length === 0) {
        const firstErr = failed[0].reason;
        const msg = firstErr instanceof Error ? firstErr.message : "Discovery failed";
        setSchemaLoadError(msg);
        toast.error(msg);
        return;
      }
      const allItems = succeeded.flatMap((r) => r.value.items as DiscoveredObject[]);
      const totalObjects = succeeded.reduce((sum, r) => sum + r.value.objects, 0);
      setObjects(allItems);

      if (failed.length > 0) {
        toast.warning(`Discovered ${totalObjects} objects from ${succeeded.length} schema${succeeded.length !== 1 ? "s" : ""} — ${failed.length} failed`);
      } else {
        toast.success(`Discovered ${totalObjects} objects across ${schemasToScan.length} schema${schemasToScan.length !== 1 ? "s" : ""}`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Discovery failed");
    } finally {
      setLoading(false);
    }
  }, [activeConn, connType, selectedSchema, availableSchemas, connHealth, schemaLoadError]);

  const handleSelectObject = useCallback(async (obj: DiscoveredObject) => {
    setSelectedObject(obj);
    setDefinition(null);
    if (!activeConn) return;
    setDefLoading(true);
    try {
      setDefinition(await getObjectDefinition(activeConn.id, obj.schema, obj.name, obj.type));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load definition");
    } finally {
      setDefLoading(false);
    }
  }, [activeConn]);

  const handleLoadGraph = useCallback(async () => {
    if (!activeConn) {
      toast.info("Select a SQL Server (source) connection first");
      return;
    }
    if (connType !== "source") {
      toast.info("Dependency graph is only available for SQL Server (source) connections");
      return;
    }
    setGraphLoading(true);
    setGraphError(null);
    setGraphData(null);
    try {
      const data = await getDependencyGraph(activeConn.id, graphSchema);
      setGraphData(data);
      if (data.node_count === 0) {
        setGraphError(`No objects found in schema "${graphSchema}". Try a different schema or rescan objects first.`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load dependency graph";
      setGraphError(msg);
      toast.error(msg);
    } finally {
      setGraphLoading(false);
    }
  }, [activeConn, connType, graphSchema]);

  const bySchema = useMemo(() => {
    const map = new Map<string, DiscoveredObject[]>();
    for (const obj of objects) {
      const matchSearch =
        !search ||
        obj.name.toLowerCase().includes(search.toLowerCase()) ||
        obj.schema.toLowerCase().includes(search.toLowerCase()) ||
        obj.type.toLowerCase().includes(search.toLowerCase());
      if (!matchSearch) continue;
      if (!map.has(obj.schema)) map.set(obj.schema, []);
      map.get(obj.schema)!.push(obj);
    }
    return map;
  }, [objects, search]);

  const totalFiltered = Array.from(bySchema.values()).reduce((sum, arr) => sum + arr.length, 0);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Discovered Objects</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Browse schemas, tables, and columns · Explore object dependencies
          </p>
        </div>
        <div className="flex items-center gap-2">
          {activeTab === "objects" && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleRescan}
              disabled={loading || connHealth.status === "checking" || connHealth.status === "unreachable"}
            >
              {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Database className="h-4 w-4 mr-2" />}
              {loading ? "Scanning..." : "Rescan"}
            </Button>
          )}
          {activeTab === "graph" && (
            <Button variant="outline" size="sm" onClick={handleLoadGraph} disabled={graphLoading}>
              {graphLoading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
              {graphLoading ? "Loading..." : "Load Graph"}
            </Button>
          )}
        </div>
      </div>

      {(schemaLoadError || connHealth.status === "checking") && (
        <div
          className={`rounded-lg border px-4 py-3 text-sm flex items-start gap-2 ${
            connHealth.status === "checking"
              ? "border-border bg-muted/30 text-muted-foreground"
              : "border-red-500/30 bg-red-500/10 text-red-400"
          }`}
        >
          {connHealth.status === "checking" ? (
            <>
              <Loader2 className="h-4 w-4 shrink-0 mt-0.5 animate-spin" />
              <p>Checking connection to {activeConn?.name ?? "database"}…</p>
            </>
          ) : (
            <>
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold mb-0.5">Database server not reachable</p>
                <p>{schemaLoadError}</p>
                {activeConn && (
                  <p className="text-xs mt-1 opacity-80">
                    Configured endpoint: {activeConn.host}:{activeConn.port}/{activeConn.database}
                  </p>
                )}
                <a href="/settings" className="text-xs underline underline-offset-2 mt-1 inline-block">
                  Update connection in Settings
                </a>
              </div>
            </>
          )}
        </div>
      )}

      {/* Top controls */}
      <div className="flex items-center gap-4 flex-wrap">
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as ActiveTab)} className="h-8">
          <TabsList className="h-8">
            <TabsTrigger value="objects" className="h-7 text-xs gap-1.5 px-2.5">
              <Database className="h-3.5 w-3.5" /> Object Tree
            </TabsTrigger>
            <TabsTrigger value="graph" className="h-7 text-xs gap-1.5 px-2.5">
              <FolderTree className="h-3.5 w-3.5" /> Dependency Graph
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <Tabs value={connType} onValueChange={(v) => setConnType(v as ConnectorType)} className="h-8">
          <TabsList className="h-8">
            <TabsTrigger value="source" className="h-7 text-xs gap-1.5 px-2.5">
              <Server className="h-3.5 w-3.5" /> SQL Server
            </TabsTrigger>
            <TabsTrigger value="target" className="h-7 text-xs gap-1.5 px-2.5">
              <Database className="h-3.5 w-3.5" /> PostgreSQL
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {allConns.length > 0 && (
          <select
            value={activeConn?.id || ""}
            onChange={(e) => {
              const c = allConns.find((c) => c.id === e.target.value);
              if (c) setActiveConn(c);
            }}
            className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
          >
            {allConns.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.host}:{c.port}/{c.database})</option>
            ))}
          </select>
        )}

        {activeTab === "objects" && availableSchemas.length > 0 && (
          <select
            value={selectedSchema}
            onChange={(e) => setSelectedSchema(e.target.value)}
            className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
          >
            <option value="__ALL__">All Schemas ({availableSchemas.length})</option>
            {availableSchemas.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}

        {activeTab === "graph" && connType === "source" && (
          <select
            value={graphSchema}
            onChange={(e) => setGraphSchema(e.target.value)}
            className="flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
          >
            {availableSchemas.length > 0
              ? availableSchemas.map((s) => <option key={s} value={s}>{s}</option>)
              : <option value="dbo">dbo</option>}
          </select>
        )}
      </div>

      {/* Object Tree Tab */}
      {activeTab === "objects" && (
        <>
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search objects..."
                className="pl-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            {objects.length > 0 && (
              <p className="text-sm text-muted-foreground">
                {totalFiltered} of {objects.length} objects
              </p>
            )}
          </div>

          {loading && (
            <Card>
              <CardContent className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </CardContent>
            </Card>
          )}

          {!loading && objects.length === 0 && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Database className="h-16 w-16 text-muted-foreground/30 mb-4" />
                <h2 className="text-xl font-semibold text-muted-foreground mb-2">No Objects Discovered</h2>
                <p className="text-sm text-muted-foreground/70 text-center max-w-md">
                  {schemaLoadError
                    ? schemaLoadError
                    : activeConn
                      ? `Click Rescan to discover objects from ${activeConn.name}.`
                      : `Configure a ${connType === "source" ? "SQL Server" : "PostgreSQL"} connection in Settings first.`}
                </p>
                <div className="flex gap-3 mt-6">
                  {activeConn && !schemaLoadError ? (
                    <Button variant="default" onClick={handleRescan} disabled={connHealth.status !== "reachable"}>
                      <Database className="h-4 w-4 mr-2" /> Rescan Now
                    </Button>
                  ) : (
                    <Button variant="default" asChild><a href="/settings">Configure Connections</a></Button>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {!loading && objects.length > 0 && (
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Object Tree</CardTitle>
                    <CardDescription>
                      {bySchema.size} schema{bySchema.size !== 1 ? "s" : ""} · {objects.length} objects
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="p-0 overflow-y-auto max-h-[600px]">
                    {bySchema.size === 0 ? (
                      <p className="text-sm text-muted-foreground text-center py-8">No objects match your search.</p>
                    ) : (
                      Array.from(bySchema.entries()).map(([schema, objs]) => (
                        <SchemaGroup
                          key={schema}
                          schema={schema}
                          objects={objs}
                          connectionId={activeConn?.id ?? ""}
                          selectedObject={selectedObject}
                          onSelect={handleSelectObject}
                        />
                      ))
                    )}
                  </CardContent>
                </Card>
              </div>

              <div>
                <Card className="h-full">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Code2 className="h-4 w-4" />
                      {selectedObject ? `${selectedObject.schema}.${selectedObject.name}` : "Object Definition"}
                    </CardTitle>
                    {selectedObject && (
                      <CardDescription>
                        <Badge variant="outline" className="text-[10px] mt-1 capitalize">{selectedObject.type.toLowerCase()}</Badge>
                      </CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="p-0">
                    {!selectedObject && (
                      <p className="text-sm text-muted-foreground text-center py-8 px-4">
                        Click an object to view its DDL definition.
                      </p>
                    )}
                    {selectedObject && defLoading && (
                      <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                      </div>
                    )}
                    {selectedObject && !defLoading && definition && (
                      <pre className="text-xs font-mono overflow-auto max-h-[520px] p-4 bg-muted/30 rounded-b-lg whitespace-pre-wrap break-words">
                        {definition.definition}
                      </pre>
                    )}
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </>
      )}

      {/* Dependency Graph Tab */}
      {activeTab === "graph" && (
        <div className="space-y-4">
          {connType !== "source" && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-400 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Dependency graph is only available for SQL Server (source) connections. Switch to the SQL Server tab.
            </div>
          )}

          {connType === "source" && !graphData && !graphLoading && !graphError && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <FolderTree className="h-16 w-16 text-muted-foreground/30 mb-4" />
                <h2 className="text-xl font-semibold text-muted-foreground mb-2">Dependency Graph</h2>
                <p className="text-sm text-muted-foreground/70 text-center max-w-md">
                  Visualize object dependencies (stored procedures, functions, views, tables) from your SQL Server database.
                  Select a schema and click <strong>Load Graph</strong> to start.
                </p>
                <Button className="mt-6" onClick={handleLoadGraph} disabled={!activeConn}>
                  <FolderTree className="h-4 w-4 mr-2" /> Load Graph
                </Button>
              </CardContent>
            </Card>
          )}

          {graphLoading && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Loader2 className="h-10 w-10 animate-spin text-muted-foreground mb-4" />
                <p className="text-sm text-muted-foreground">Querying dependency catalog…</p>
              </CardContent>
            </Card>
          )}

          {graphError && !graphLoading && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold mb-1">Failed to load dependency graph</p>
                <p>{graphError}</p>
              </div>
            </div>
          )}

          {graphData && !graphLoading && graphData.node_count > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">
                    Dependency Graph — {graphData.schema}
                  </CardTitle>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{graphData.node_count} objects</span>
                    <span>{graphData.edge_count} dependencies</span>
                  </div>
                </div>
                <CardDescription>
                  Arrows point from dependent object → dependency. Nodes at the top have no dependents.
                </CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <div className="h-[600px] rounded-b-lg overflow-hidden">
                  <DependencyGraph apiNodes={graphData.nodes} apiEdges={graphData.edges} />
                </div>
              </CardContent>
            </Card>
          )}

          {graphData && !graphLoading && graphData.node_count === 0 && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <FolderTree className="h-12 w-12 text-muted-foreground/30 mb-3" />
                <p className="text-muted-foreground">No objects with dependencies found in schema &quot;{graphData.schema}&quot;.</p>
                <p className="text-sm text-muted-foreground/70 mt-1">Try a different schema or run a discovery scan first.</p>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
