"use client";

/**
 * Module: object-detail-panel.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
} from "lucide-react";
import type { TreeNode, DiffEntry } from "@/types/comparison";

interface ObjectDetailPanelProps {
  sourceObject: TreeNode | null;
  targetObject: TreeNode | null;
  differences: DiffEntry[];
  sourceDDL?: string;
  targetDDL?: string;
  issues?: { type: "warning" | "error" | "info"; message: string }[];
}

function getSeverityIcon(severity: string) {
  switch (severity) {
    case "error": return <XCircle className="h-4 w-4 text-red-500" />;
    case "warning": return <AlertTriangle className="h-4 w-4 text-amber-500" />;
    default: return <Info className="h-4 w-4 text-blue-500" />;
  }
}

function getStatusBadge(status: string) {
  switch (status) {
    case "exact":
      return <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">Exact Match</Badge>;
    case "partial":
      return <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20">Partial Match</Badge>;
    case "source_only":
      return <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">Source Only</Badge>;
    case "target_only":
      return <Badge variant="outline" className="bg-purple-500/10 text-purple-500 border-purple-500/20">Target Only</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function SchemaTab({ sourceObject, targetObject, differences }: ObjectDetailPanelProps) {
  const allProperties = new Set<string>();
  if (sourceObject?.properties) Object.keys(sourceObject.properties).forEach((k) => allProperties.add(k));
  if (targetObject?.properties) Object.keys(targetObject.properties).forEach((k) => allProperties.add(k));

  const diffMap = new Map<string, DiffEntry>();
  differences.forEach((d) => diffMap.set(d.propertyName, d));

  const rows = Array.from(allProperties).map((prop) => {
    const diff = diffMap.get(prop);
    const sourceVal = sourceObject?.properties?.[prop];
    const targetVal = targetObject?.properties?.[prop];
    const isDifferent = sourceVal !== targetVal;
    return { property: prop, sourceVal, targetVal, isDifferent, severity: diff?.severity };
  });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[200px]">Property</TableHead>
          <TableHead>Source Value</TableHead>
          <TableHead>Target Value</TableHead>
          <TableHead className="w-[100px]">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={4} className="text-center text-muted-foreground">
              No properties to compare
            </TableCell>
          </TableRow>
        ) : (
          rows.map((row) => (
            <TableRow key={row.property}>
              <TableCell className="font-medium">{row.property}</TableCell>
              <TableCell className={cn("font-mono text-sm", !row.isDifferent && "text-muted-foreground")}>
                {row.sourceVal ?? <span className="text-muted-foreground italic">N/A</span>}
              </TableCell>
              <TableCell className={cn("font-mono text-sm", !row.isDifferent && "text-muted-foreground")}>
                {row.targetVal ?? <span className="text-muted-foreground italic">N/A</span>}
              </TableCell>
              <TableCell>
                {row.isDifferent ? (
                  <div className="flex items-center gap-1">
                    {row.severity === "error" ? (
                      <XCircle className="h-4 w-4 text-red-500" />
                    ) : row.severity === "warning" ? (
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                    ) : (
                      <Info className="h-4 w-4 text-blue-500" />
                    )}
                    <span className="text-xs text-muted-foreground">
                      {row.severity === "error" ? "Incompatible" : row.severity === "warning" ? "Review" : "Info"}
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1">
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    <span className="text-xs text-muted-foreground">Match</span>
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}

function ColumnsTab({ sourceObject, targetObject }: ObjectDetailPanelProps) {
  const sourceCols = sourceObject?.children?.filter((c) => c.nodeType === "column") ?? [];
  const targetCols = targetObject?.children?.filter((c) => c.nodeType === "column") ?? [];

  const allColNames = new Set<string>();
  sourceCols.forEach((c) => allColNames.add(c.name));
  targetCols.forEach((c) => allColNames.add(c.name));

  const colMap = new Map<string, { source?: TreeNode; target?: TreeNode }>();
  sourceCols.forEach((c) => {
    if (!colMap.has(c.name)) colMap.set(c.name, {});
    colMap.get(c.name)!.source = c;
  });
  targetCols.forEach((c) => {
    if (!colMap.has(c.name)) colMap.set(c.name, {});
    colMap.get(c.name)!.target = c;
  });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Column Name</TableHead>
          <TableHead>Source Type</TableHead>
          <TableHead>Target Type</TableHead>
          <TableHead>Nullable (S)</TableHead>
          <TableHead>Nullable (T)</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {allColNames.size === 0 ? (
          <TableRow>
            <TableCell colSpan={6} className="text-center text-muted-foreground">
              No columns to compare
            </TableCell>
          </TableRow>
        ) : (
          Array.from(allColNames).map((name) => {
            const { source, target } = colMap.get(name) ?? {};
            const sourceType = source?.properties?.dataType ?? "--";
            const targetType = target?.properties?.dataType ?? "--";
            const sourceNullable = source?.properties?.nullable;
            const targetNullable = target?.properties?.nullable;
            const isMatch = source && target && sourceType === targetType;
            const isOnlySource = source && !target;
            const isOnlyTarget = !source && target;

            return (
              <TableRow key={name}>
                <TableCell className="font-medium">{name}</TableCell>
                <TableCell className="font-mono text-sm">{sourceType}</TableCell>
                <TableCell className="font-mono text-sm">{targetType}</TableCell>
                <TableCell>{sourceNullable !== undefined ? String(sourceNullable) : <span className="text-muted-foreground">--</span>}</TableCell>
                <TableCell>{targetNullable !== undefined ? String(targetNullable) : <span className="text-muted-foreground">--</span>}</TableCell>
                <TableCell>
                  {isMatch && (
                    <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">Match</Badge>
                  )}
                  {source && target && !isMatch && (
                    <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20">Differs</Badge>
                  )}
                  {isOnlySource && (
                    <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">Source Only</Badge>
                  )}
                  {isOnlyTarget && (
                    <Badge variant="outline" className="bg-purple-500/10 text-purple-500 border-purple-500/20">Target Only</Badge>
                  )}
                </TableCell>
              </TableRow>
            );
          })
        )}
      </TableBody>
    </Table>
  );
}

function IndexesTab({ sourceObject, targetObject }: ObjectDetailPanelProps) {
  const sourceIdxs = sourceObject?.children?.filter((c) => c.nodeType === "index") ?? [];
  const targetIdxs = targetObject?.children?.filter((c) => c.nodeType === "index") ?? [];

  const allIdxNames = new Set<string>();
  sourceIdxs.forEach((c) => allIdxNames.add(c.name));
  targetIdxs.forEach((c) => allIdxNames.add(c.name));

  const idxMap = new Map<string, { source?: TreeNode; target?: TreeNode }>();
  sourceIdxs.forEach((c) => {
    if (!idxMap.has(c.name)) idxMap.set(c.name, {});
    idxMap.get(c.name)!.source = c;
  });
  targetIdxs.forEach((c) => {
    if (!idxMap.has(c.name)) idxMap.set(c.name, {});
    idxMap.get(c.name)!.target = c;
  });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Index Name</TableHead>
          <TableHead>Source Columns</TableHead>
          <TableHead>Target Columns</TableHead>
          <TableHead>Unique (S)</TableHead>
          <TableHead>Unique (T)</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {allIdxNames.size === 0 ? (
          <TableRow>
            <TableCell colSpan={6} className="text-center text-muted-foreground">
              No indexes to compare
            </TableCell>
          </TableRow>
        ) : (
          Array.from(allIdxNames).map((name) => {
            const { source, target } = idxMap.get(name) ?? {};
            const isMatch = !!(source && target);
            const isOnlySource = !!source && !target;
            const isOnlyTarget = !source && !!target;

            return (
              <TableRow key={name}>
                <TableCell className="font-medium">{name}</TableCell>
                <TableCell className="font-mono text-sm">{source?.properties?.columns ?? "--"}</TableCell>
                <TableCell className="font-mono text-sm">{target?.properties?.columns ?? "--"}</TableCell>
                <TableCell>{source?.properties?.unique !== undefined ? String(source.properties.unique) : "--"}</TableCell>
                <TableCell>{target?.properties?.unique !== undefined ? String(target.properties.unique) : "--"}</TableCell>
                <TableCell>
                  {isMatch && (
                    <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">Match</Badge>
                  )}
                  {isOnlySource && (
                    <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">Source Only</Badge>
                  )}
                  {isOnlyTarget && (
                    <Badge variant="outline" className="bg-purple-500/10 text-purple-500 border-purple-500/20">Target Only</Badge>
                  )}
                </TableCell>
              </TableRow>
            );
          })
        )}
      </TableBody>
    </Table>
  );
}

function DDLTab({ sourceDDL, targetDDL }: ObjectDetailPanelProps) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h4 className="text-sm font-medium mb-2 text-muted-foreground">Source (SQL Server)</h4>
        <pre className="text-xs bg-muted/50 border rounded-lg p-4 overflow-auto max-h-[400px] font-mono">
          <code>{sourceDDL || "-- No DDL available"}</code>
        </pre>
      </div>
      <div>
        <h4 className="text-sm font-medium mb-2 text-muted-foreground">Target (PostgreSQL)</h4>
        <pre className="text-xs bg-muted/50 border rounded-lg p-4 overflow-auto max-h-[400px] font-mono">
          <code>{targetDDL || "-- No DDL available"}</code>
        </pre>
      </div>
    </div>
  );
}

function IssuesTab({ issues }: ObjectDetailPanelProps) {
  if (!issues || issues.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <CheckCircle2 className="h-5 w-5 mr-2 text-emerald-500" />
        No issues detected
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {issues.map((issue, i) => (
        <div
          key={i}
          className={cn(
            "flex items-start gap-3 p-3 rounded-lg border",
            issue.type === "error" && "bg-red-500/5 border-red-500/20",
            issue.type === "warning" && "bg-amber-500/5 border-amber-500/20",
            issue.type === "info" && "bg-blue-500/5 border-blue-500/20"
          )}
        >
          {getSeverityIcon(issue.type)}
          <div>
            <p className="text-sm font-medium capitalize">{issue.type}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{issue.message}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ObjectDetailPanel(props: ObjectDetailPanelProps) {
  const { sourceObject, targetObject } = props;

  if (!sourceObject && !targetObject) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <Info className="h-5 w-5 mr-2" />
        Select an object to view details
      </div>
    );
  }

  const objectName = sourceObject?.name ?? targetObject?.name ?? "Unknown";
  const objectType = sourceObject?.nodeType ?? targetObject?.nodeType ?? "object";
  const status = sourceObject?.status ?? targetObject?.status ?? "exact";

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium capitalize">{objectType}</span>
          <span className="text-sm text-muted-foreground">/</span>
          <span className="text-sm font-semibold">{objectName}</span>
        </div>
        {getStatusBadge(status)}
      </div>
      <div className="flex-1 overflow-auto p-4">
        <Tabs defaultValue="schema" className="h-full flex flex-col">
          <TabsList>
            <TabsTrigger value="schema">Schema</TabsTrigger>
            <TabsTrigger value="columns">Columns</TabsTrigger>
            <TabsTrigger value="indexes">Indexes</TabsTrigger>
            <TabsTrigger value="ddl">DDL</TabsTrigger>
            <TabsTrigger value="issues">Issues</TabsTrigger>
          </TabsList>
          <div className="flex-1 overflow-auto mt-2">
            <TabsContent value="schema" className="mt-0">
              <SchemaTab {...props} />
            </TabsContent>
            <TabsContent value="columns" className="mt-0">
              <ColumnsTab {...props} />
            </TabsContent>
            <TabsContent value="indexes" className="mt-0">
              <IndexesTab {...props} />
            </TabsContent>
            <TabsContent value="ddl" className="mt-0">
              <DDLTab {...props} />
            </TabsContent>
            <TabsContent value="issues" className="mt-0">
              <IssuesTab {...props} />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
