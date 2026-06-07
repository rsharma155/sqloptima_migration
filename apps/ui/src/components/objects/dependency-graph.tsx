"use client";

/**
 * Module: dependency-graph.tsx
 * Purpose: Interactive dependency graph using React Flow.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  MarkerType,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "reactflow";
import "reactflow/dist/style.css";
import { cn } from "@/lib/utils";
import type { GraphNode, GraphEdge } from "@/lib/api";
import { DEPENDENCY_GRAPH_NODE_TYPES } from "@/components/objects/dependency-graph-node";

const DEFAULT_EDGE_OPTIONS = {
  style: { stroke: "hsl(var(--border))", strokeWidth: 1 },
  markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(var(--border))" },
} as const;

const PRO_OPTIONS = { hideAttribution: true } as const;

// ---------------------------------------------------------------------------
// Layout: topological levels → grid positions
// ---------------------------------------------------------------------------

const NODE_W = 200;
const NODE_H = 80;
const H_GAP = 60;
const V_GAP = 80;

function computeLayout(nodes: GraphNode[], edges: GraphEdge[]): Node[] {
  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();

  for (const n of nodes) {
    inDegree.set(n.id, 0);
    adj.set(n.id, []);
  }
  for (const e of edges) {
    adj.get(e.source)?.push(e.target);
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
  }

  const levels = new Map<string, number>();
  let frontier = nodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0).map((n) => n.id);
  const visited = new Set<string>();
  let level = 0;

  while (frontier.length > 0) {
    const next: string[] = [];
    for (const id of frontier) {
      if (visited.has(id)) continue;
      visited.add(id);
      levels.set(id, level);
      for (const neighbor of adj.get(id) ?? []) {
        inDegree.set(neighbor, (inDegree.get(neighbor) ?? 1) - 1);
        if ((inDegree.get(neighbor) ?? 0) === 0) next.push(neighbor);
      }
    }
    level++;
    frontier = next;
  }

  for (const n of nodes) {
    if (!levels.has(n.id)) levels.set(n.id, level);
  }

  const byLevel = new Map<number, string[]>();
  for (const [id, l] of levels) {
    if (!byLevel.has(l)) byLevel.set(l, []);
    byLevel.get(l)!.push(id);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [l, ids] of byLevel) {
    const totalW = ids.length * NODE_W + (ids.length - 1) * H_GAP;
    const startX = -totalW / 2;
    ids.forEach((id, i) => {
      positions.set(id, {
        x: startX + i * (NODE_W + H_GAP),
        y: l * (NODE_H + V_GAP),
      });
    });
  }

  return nodes.map((n) => ({
    id: n.id,
    type: "dbObject",
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: { label: n.label, schema: n.schema, typeDesc: n.type },
  }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface DependencyGraphProps {
  className?: string;
  apiNodes?: GraphNode[];
  apiEdges?: GraphEdge[];
}

export function DependencyGraph({ className, apiNodes = [], apiEdges = [] }: DependencyGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node[]>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge[]>([]);

  // React Flow #002: nodeTypes must keep the same reference across renders.
  const nodeTypes = useMemo(() => DEPENDENCY_GRAPH_NODE_TYPES, []);
  const defaultEdgeOptions = useMemo(
    () => ({
      style: { ...DEFAULT_EDGE_OPTIONS.style },
      markerEnd: { ...DEFAULT_EDGE_OPTIONS.markerEnd },
    }),
    [],
  );

  useEffect(() => {
    setNodes(computeLayout(apiNodes, apiEdges));
    setEdges(
      apiEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        ...defaultEdgeOptions,
      })),
    );
  }, [apiNodes, apiEdges, setNodes, setEdges, defaultEdgeOptions]);

  return (
    <div className={cn("h-full w-full", className)}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        attributionPosition="bottom-left"
        proOptions={PRO_OPTIONS}
      >
        <Background color="hsl(var(--border))" gap={20} size={1} />
        <Controls className="[&>button]:border [&>button]:bg-card [&>button]:text-muted-foreground [&>button]:hover:bg-accent" />
        <MiniMap
          nodeStrokeColor="hsl(var(--muted-foreground))"
          nodeColor="hsl(var(--card))"
          maskColor="hsl(var(--background))"
          className="border rounded-md"
          style={{ background: "hsl(var(--card))" }}
        />
      </ReactFlow>
    </div>
  );
}
