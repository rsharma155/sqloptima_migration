"use client";

/**
 * Custom React Flow node for database object dependency graphs.
 * Kept in a separate module so nodeTypes stays referentially stable (React Flow #002).
 */

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { cn } from "@/lib/utils";

const TYPE_COLOR: Record<string, { bg: string; dot: string; label: string }> = {
  SQL_STORED_PROCEDURE: { bg: "bg-amber-500/10 border-amber-500/40", dot: "bg-amber-500", label: "Procedure" },
  SQL_SCALAR_FUNCTION: { bg: "bg-purple-500/10 border-purple-500/40", dot: "bg-purple-500", label: "Function" },
  SQL_INLINE_TABLE_VALUED_FUNCTION: { bg: "bg-purple-500/10 border-purple-500/40", dot: "bg-purple-500", label: "iTVF" },
  SQL_TABLE_VALUED_FUNCTION: { bg: "bg-purple-500/10 border-purple-500/40", dot: "bg-purple-500", label: "TVF" },
  SQL_TRIGGER: { bg: "bg-red-500/10 border-red-500/40", dot: "bg-red-500", label: "Trigger" },
  VIEW: { bg: "bg-cyan-500/10 border-cyan-500/40", dot: "bg-cyan-500", label: "View" },
  USER_TABLE: { bg: "bg-blue-500/10 border-blue-500/40", dot: "bg-blue-500", label: "Table" },
  UNKNOWN: { bg: "bg-muted border-border", dot: "bg-muted-foreground", label: "?" },
};

function typeStyle(typeDesc: string) {
  return TYPE_COLOR[typeDesc] ?? TYPE_COLOR.UNKNOWN;
}

function DbObjectNodeComponent({
  data,
}: NodeProps<{ label: string; schema: string; typeDesc: string }>) {
  const style = typeStyle(data.typeDesc);
  return (
    <div className={cn("rounded-lg border px-3 py-2 w-44 relative text-[11px]", style.bg)}>
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground !w-2 !h-2" />
      <div className="flex items-center gap-1.5 mb-1">
        <div className={cn("h-2 w-2 rounded-full shrink-0", style.dot)} />
        <span className="font-semibold truncate text-foreground">{data.label}</span>
      </div>
      <div className="flex justify-between text-muted-foreground">
        <span>{data.schema}</span>
        <span className="font-mono">{style.label}</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground !w-2 !h-2" />
    </div>
  );
}

export const DbObjectNode = memo(DbObjectNodeComponent);

/** Stable nodeTypes map — must not be recreated per render. */
export const DEPENDENCY_GRAPH_NODE_TYPES = {
  dbObject: DbObjectNode,
} as const;
