"use client";

/**
 * Module: tree-view.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useCallback } from "react";
import {
  ChevronRight,
  ChevronDown,
  Database,
  Folder,
  Table,
  Code,
  Eye,
  Workflow,
  Braces,
  Columns3,
  Key,
  GripVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { TreeNode } from "@/types/comparison";

interface TreeViewProps {
  nodes: TreeNode[];
  onSelect: (node: TreeNode, path: string) => void;
  selectedPath: string | null;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  side: "source" | "target";
  synchronizedExpansion: boolean;
}

const nodeIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  database: Database,
  schema: Folder,
  table: Table,
  view: Eye,
  procedure: Code,
  function: Braces,
  trigger: Workflow,
  column: Columns3,
  index: GripVertical,
  constraint: Key,
};

const statusConfig: Record<string, { label: string; className: string }> = {
  exact: { label: "Exact", className: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20" },
  partial: { label: "Partial", className: "bg-amber-500/10 text-amber-500 border-amber-500/20" },
  source_only: { label: "Source Only", className: "bg-blue-500/10 text-blue-500 border-blue-500/20" },
  target_only: { label: "Target Only", className: "bg-purple-500/10 text-purple-500 border-purple-500/20" },
};

function buildPath(parentPath: string, name: string): string {
  return parentPath ? `${parentPath}.${name}` : name;
}

interface TreeNodeItemProps {
  node: TreeNode;
  depth: number;
  path: string;
  selectedPath: string | null;
  expandedPaths: Set<string>;
  onSelect: (node: TreeNode, path: string) => void;
  onToggle: (path: string) => void;
}

function TreeNodeItem({
  node,
  depth,
  path,
  selectedPath,
  expandedPaths,
  onSelect,
  onToggle,
}: TreeNodeItemProps) {
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedPaths.has(path);
  const isSelected = selectedPath === path;
  const Icon = nodeIcons[node.nodeType] || Folder;

  const handleToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (hasChildren) onToggle(path);
    },
    [hasChildren, path, onToggle]
  );

  const handleSelect = useCallback(() => {
    onSelect(node, path);
  }, [node, path, onSelect]);

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-1 py-1 px-2 rounded-md cursor-pointer text-sm transition-colors group",
          "hover:bg-accent/50",
          isSelected && "bg-accent text-accent-foreground",
          depth > 0 && "ml-0"
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleSelect}
      >
        <button
          onClick={handleToggle}
          className={cn(
            "h-4 w-4 shrink-0 flex items-center justify-center rounded",
            !hasChildren && "invisible"
          )}
        >
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </button>

        <Icon className={cn("h-4 w-4 shrink-0", getIconColor(node.nodeType))} />

        <span className="truncate flex-1">{node.name}</span>

        {node.status && (
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] px-1.5 py-0 h-5 font-normal opacity-0 group-hover:opacity-100 transition-opacity",
              statusConfig[node.status]?.className
            )}
          >
            {statusConfig[node.status]?.label}
          </Badge>
        )}
      </div>

      {hasChildren && isExpanded && (
        <div className="overflow-hidden">
          {node.children.map((child) => {
            const childPath = buildPath(path, child.name);
            return (
              <TreeNodeItem
                key={childPath}
                node={child}
                depth={depth + 1}
                path={childPath}
                selectedPath={selectedPath}
                expandedPaths={expandedPaths}
                onSelect={onSelect}
                onToggle={onToggle}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function getIconColor(nodeType: string): string {
  switch (nodeType) {
    case "database": return "text-cyan-500";
    case "schema": return "text-amber-500";
    case "table": return "text-blue-500";
    case "view": return "text-teal-500";
    case "procedure": return "text-violet-500";
    case "function": return "text-pink-500";
    case "trigger": return "text-orange-500";
    case "column": return "text-muted-foreground";
    case "index": return "text-emerald-500";
    case "constraint": return "text-red-500";
    default: return "text-muted-foreground";
  }
}

export function TreeView({
  nodes,
  onSelect,
  selectedPath,
  expandedPaths,
  onToggle,
  side,
}: TreeViewProps) {
  return (
    <div className="h-full overflow-auto p-2">
      {nodes.length === 0 ? (
        <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
          No objects found
        </div>
      ) : (
        nodes.map((node) => {
          const path = buildPath("", node.name);
          return (
            <TreeNodeItem
              key={path}
              node={node}
              depth={0}
              path={path}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={onSelect}
              onToggle={onToggle}
            />
          );
        })
      )}
    </div>
  );
}
