"use client";

/**
 * Module: procedural-migration-panel.tsx
 * Purpose: Select and preview stored procedures / functions for PostgreSQL migration.
 */

import { useCallback, useMemo, useState } from "react";
import { Code2, Eye, Loader2, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  previewProceduralMigration,
  type ProceduralPreviewItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export interface ProceduralDiscoveredObject {
  name: string;
  type: string;
  schema: string;
}

interface ProceduralMigrationPanelProps {
  sourceConnectionId: string | null;
  sourceSchema: string;
  targetSchema: string;
  objects: ProceduralDiscoveredObject[];
  selectedProcedures: Set<string>;
  selectedFunctions: Set<string>;
  onToggleProcedure: (name: string) => void;
  onToggleFunction: (name: string) => void;
  onSelectAllProcedures: () => void;
  onClearProcedures: () => void;
  onSelectAllFunctions: () => void;
  onClearFunctions: () => void;
  disabled?: boolean;
}

function normalizeType(type: string): "procedure" | "function" | null {
  const t = type.toLowerCase();
  if (t === "procedure" || t === "stored_procedure" || t === "sp") return "procedure";
  if (t === "function" || t.includes("function")) return "function";
  return null;
}

function PreviewStatus({ item }: { item: ProceduralPreviewItem }) {
  if (item.success && !item.manual_review_required) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-600 text-[10px]">
        <CheckCircle2 className="h-3 w-3" /> Ready
      </span>
    );
  }
  if (item.manual_review_required) {
    return (
      <span className="inline-flex items-center gap-1 text-amber-600 text-[10px]">
        <AlertTriangle className="h-3 w-3" /> Review
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-destructive text-[10px]">
      <XCircle className="h-3 w-3" /> Failed
    </span>
  );
}

export function ProceduralMigrationPanel({
  sourceConnectionId,
  sourceSchema,
  targetSchema,
  objects,
  selectedProcedures,
  selectedFunctions,
  onToggleProcedure,
  onToggleFunction,
  onSelectAllProcedures,
  onClearProcedures,
  onSelectAllFunctions,
  onClearFunctions,
  disabled = false,
}: ProceduralMigrationPanelProps) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [previewItems, setPreviewItems] = useState<ProceduralPreviewItem[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const { procedures, functions } = useMemo(() => {
    const proc: ProceduralDiscoveredObject[] = [];
    const func: ProceduralDiscoveredObject[] = [];
    for (const obj of objects) {
      const kind = normalizeType(obj.type);
      if (kind === "procedure") proc.push(obj);
      else if (kind === "function") func.push(obj);
    }
    proc.sort((a, b) => a.name.localeCompare(b.name));
    func.sort((a, b) => a.name.localeCompare(b.name));
    return { procedures: proc, functions: func };
  }, [objects]);

  const selectedCount = selectedProcedures.size + selectedFunctions.size;

  const handlePreview = useCallback(async () => {
    if (!sourceConnectionId || selectedCount === 0) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const previewObjects = [
        ...Array.from(selectedProcedures).map((name) => ({
          name,
          object_type: "procedure" as const,
        })),
        ...Array.from(selectedFunctions).map((name) => ({
          name,
          object_type: "function" as const,
        })),
      ];
      const result = await previewProceduralMigration({
        source_connection_id: sourceConnectionId,
        schema: sourceSchema,
        target_schema: targetSchema,
        objects: previewObjects,
      });
      setPreviewItems(result.items);
      setPreviewOpen(true);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setPreviewing(false);
    }
  }, [
    sourceConnectionId,
    selectedCount,
    selectedProcedures,
    selectedFunctions,
    sourceSchema,
    targetSchema,
  ]);

  const renderList = (
    title: string,
    items: ProceduralDiscoveredObject[],
    selected: Set<string>,
    onToggle: (name: string) => void,
    onSelectAll: () => void,
    onClear: () => void,
  ) => (
    <div className="space-y-2 min-h-0 flex flex-col">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-sm flex items-center gap-1.5">
          <Code2 className="h-3.5 w-3.5" />
          {title}
          <Badge variant="outline" className="text-[10px] h-5">{items.length}</Badge>
        </Label>
        {items.length > 0 && (
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2" onClick={onSelectAll} disabled={disabled}>
              All
            </Button>
            <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2" onClick={onClear} disabled={disabled}>
              Clear
            </Button>
          </div>
        )}
      </div>
      <div className="flex-1 border rounded-lg overflow-hidden bg-muted/10 min-h-[140px] max-h-[180px] overflow-y-auto">
        {items.length === 0 ? (
          <p className="text-xs text-muted-foreground italic p-4 text-center">
            No {title.toLowerCase()} found in schema {sourceSchema}
          </p>
        ) : (
          <div className="divide-y">
            {items.map((obj) => (
              <label
                key={obj.name}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/30 text-sm",
                  disabled && "opacity-50 cursor-not-allowed",
                )}
              >
                <input
                  type="checkbox"
                  checked={selected.has(obj.name)}
                  onChange={() => onToggle(obj.name)}
                  disabled={disabled}
                  className="rounded border-border"
                />
                <span className="font-mono text-xs truncate">{obj.name}</span>
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      <div className="rounded-lg border border-border/80 bg-muted/5 p-4 space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm font-semibold">Stored Procedures &amp; Functions</p>
            <p className="text-xs text-muted-foreground max-w-xl">
              Selected routines are converted from T-SQL to PL/pgSQL and created on{" "}
              <code className="text-[10px]">{targetSchema}</code> after table migration completes.
              Zero-argument routines get a runtime smoke call on PostgreSQL; others are compile-checked only.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-8 shrink-0"
            onClick={handlePreview}
            disabled={disabled || previewing || selectedCount === 0 || !sourceConnectionId}
          >
            {previewing ? (
              <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            ) : (
              <Eye className="h-3.5 w-3.5 mr-1.5" />
            )}
            Preview conversion ({selectedCount})
          </Button>
        </div>
        {previewError && (
          <p className="text-xs text-destructive">{previewError}</p>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {renderList(
            "Stored Procedures",
            procedures,
            selectedProcedures,
            onToggleProcedure,
            onSelectAllProcedures,
            onClearProcedures,
          )}
          {renderList(
            "Functions",
            functions,
            selectedFunctions,
            onToggleFunction,
            onSelectAllFunctions,
            onClearFunctions,
          )}
        </div>
      </div>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Conversion preview</DialogTitle>
            <DialogDescription>
              PL/pgSQL output for selected routines ({sourceSchema} → {targetSchema}). Review warnings before migrating.
            </DialogDescription>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto space-y-4 pr-1">
            {previewItems.map((item) => (
              <div key={`${item.object_type}-${item.name}`} className="rounded-md border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-sm">
                    {item.object_type} {item.schema_name}.{item.name}
                  </p>
                  <PreviewStatus item={item} />
                </div>
                {item.warnings.length > 0 && (
                  <p className="text-xs text-amber-600">
                    {item.warnings.join(" · ")}
                  </p>
                )}
                {item.errors.length > 0 && (
                  <p className="text-xs text-destructive">
                    {item.errors.join(" · ")}
                  </p>
                )}
                <pre className="text-[11px] font-mono bg-muted/40 rounded p-2 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {item.converted_sql || "-- no output"}
                </pre>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
