/**
 * Module: app/discovery/[projectId]/page.tsx
 * Purpose: Per-project discovery results page.  Runs schema discovery against
 *          the project's source connection and presents a filterable,
 *          searchable object list (tables, views, procedures, functions).
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
"use client";

import { useState, useCallback, useEffect } from "react";
import { useParams } from "next/navigation";
import {
  Database,
  Eye,
  Code,
  Table2,
  Loader2,
  Search,
  ArrowLeft,
  Play,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { discoverSchema, listSchemas, getProjects, type DiscoveryResult } from "@/lib/api";

// ---------------------------------------------------------------------------
// Type icon
// ---------------------------------------------------------------------------

const TYPE_CONFIG: Record<string, { icon: React.ComponentType<{ className?: string }>; color: string }> = {
  table:     { icon: Table2, color: "text-blue-400" },
  view:      { icon: Eye,    color: "text-purple-400" },
  procedure: { icon: Code,   color: "text-amber-400" },
  function:  { icon: Code,   color: "text-emerald-400" },
};

function ObjectTypeBadge({ type }: { type: string }) {
  const lower = type.toLowerCase();
  const config = TYPE_CONFIG[lower] ?? { icon: Database, color: "text-slate-400" };
  const Icon = config.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${config.color}`}>
      <Icon className="h-3.5 w-3.5" />
      {type}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type DiscoveredObject = { name: string; type: string; schema: string };

export default function DiscoveryPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [connectionId] = useState(projectId);
  const [projectName, setProjectName] = useState<string>("");
  const [schema, setSchema] = useState("__ALL__");
  const [availableSchemas, setAvailableSchemas] = useState<string[]>([]);
  const [items, setItems] = useState<DiscoveredObject[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("ALL");

  useEffect(() => {
    if (!projectId) return;
    getProjects()
      .then((ps) => {
        const p = ps.find((p) => p.id === projectId);
        if (p) setProjectName(p.name);
      })
      .catch(() => {});
    listSchemas(projectId)
      .then((schemas) => {
        setAvailableSchemas(schemas);
        // Trigger initial discovery automatically once schemas are known.
        setSchema("__ALL__");
      })
      .catch(() => setAvailableSchemas([]));
  }, [projectId]);

  const [autoDiscovered, setAutoDiscovered] = useState(false);

  const run = useCallback(async () => {
    if (!connectionId) return;
    setLoading(true);
    try {
      const schemasToScan =
        schema === "__ALL__" && availableSchemas.length > 0
          ? availableSchemas
          : [schema === "__ALL__" ? "dbo" : schema];

      const results = await Promise.all(
        schemasToScan.map((s) => discoverSchema(connectionId, s))
      );
      const discovered = results.flatMap((r) => (r.items as DiscoveredObject[]) ?? []);
      const total = results.reduce((sum, r) => sum + r.objects, 0);
      setItems(discovered);
      toast.success(`Discovered ${total} objects across ${schemasToScan.length} schema${schemasToScan.length !== 1 ? "s" : ""}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Discovery failed");
    } finally {
      setLoading(false);
    }
  }, [connectionId, schema, availableSchemas]);

  // Auto-run discovery when schemas finish loading on first mount.
  useEffect(() => {
    if (!autoDiscovered && !loading && connectionId && availableSchemas.length > 0) {
      setAutoDiscovered(true);
      run();
    }
  }, [availableSchemas, autoDiscovered, loading, connectionId, run]);

  const allTypes = Array.from(new Set(items.map((i) => i.type)));
  const filtered = items.filter((item) => {
    const matchType = typeFilter === "ALL" || item.type.toLowerCase() === typeFilter.toLowerCase();
    const matchText =
      !filter ||
      item.name.toLowerCase().includes(filter.toLowerCase()) ||
      item.schema.toLowerCase().includes(filter.toLowerCase());
    return matchType && matchText;
  });

  const countByType = allTypes.reduce<Record<string, number>>((acc, t) => {
    acc[t] = items.filter((i) => i.type === t).length;
    return acc;
  }, {});

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Schema Discovery" description={`Project: ${projectName || (projectId?.slice(0, 8) + "…")}`}>
        <Button variant="outline" size="sm" asChild>
          <Link href="/projects"><ArrowLeft className="h-4 w-4 mr-1" /> Projects</Link>
        </Button>
      </PageHeader>

      {/* Config */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-3 items-end">
            <div className="space-y-1 flex-1">
              <label className="text-xs text-muted-foreground">Schema</label>
              {availableSchemas.length > 0 ? (
                <select
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                  className="flex h-10 rounded-md border border-input bg-background px-3 py-1 text-sm max-w-xs w-full"
                >
                  <option value="__ALL__">All Schemas ({availableSchemas.length})</option>
                  {availableSchemas.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              ) : (
                <Input
                  value={schema === "__ALL__" ? "" : schema}
                  onChange={(e) => setSchema(e.target.value || "__ALL__")}
                  placeholder="dbo (leave empty for all)"
                  className="max-w-xs"
                />
              )}
            </div>
            <Button onClick={run} disabled={loading}>
              {loading ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <Play className="h-4 w-4 mr-1" />
              )}
              {items.length > 0 ? "Rescan" : loading ? "Scanning…" : "Discover"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {items.length > 0 && (
        <>
          {/* Summary */}
          <div className="flex flex-wrap gap-3">
            {Object.entries(countByType).map(([type, count]) => (
              <Badge key={type} variant="outline" className="gap-1 capitalize">
                {type}: {count}
              </Badge>
            ))}
          </div>

          {/* Filter bar */}
          <div className="flex gap-3">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by name…"
                className="pl-8"
              />
            </div>
            <div className="flex gap-1">
              {["ALL", ...allTypes].map((t) => (
                <Button
                  key={t}
                  size="sm"
                  variant={typeFilter === t ? "default" : "outline"}
                  className="text-xs capitalize"
                  onClick={() => setTypeFilter(t)}
                >
                  {t}
                </Button>
              ))}
            </div>
          </div>

          {/* Object table */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                {filtered.length} of {items.length} objects
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Schema</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Name</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((obj, i) => (
                      <tr key={i} className="border-b border-border hover:bg-muted/20">
                        <td className="px-3 py-2 text-xs text-muted-foreground font-mono">{obj.schema}</td>
                        <td className="px-3 py-2 font-medium">{obj.name}</td>
                        <td className="px-3 py-2"><ObjectTypeBadge type={obj.type} /></td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-3 py-8 text-center text-sm text-muted-foreground">
                          No objects match your filter
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {!loading && items.length === 0 && (
        <EmptyState
          icon={Database}
          title="No objects discovered yet"
          description={autoDiscovered ? "No objects found in this schema. Try selecting a different schema above." : "Loading schema…"}
          actionLabel={autoDiscovered ? "Rescan" : undefined}
          onAction={autoDiscovered ? run : undefined}
        />
      )}
    </div>
  );
}
