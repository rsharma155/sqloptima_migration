"use client";

/**
 * User-approved PostgreSQL target type picker for unsupported SQL Server columns.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { getColumnTypeOverrideOptions, type TableAssessment } from "@/lib/api";
import {
  listTypeOverrideColumns,
  overrideKey,
} from "@/lib/migration-readiness";

export interface ColumnTypeOverridePanelProps {
  selectedTables: Set<string>;
  tableAssessments: Record<string, TableAssessment>;
  columnTypeOverrides: Record<string, string>;
  onChange: (overrides: Record<string, string>) => void;
}

export function ColumnTypeOverridePanel({
  selectedTables,
  tableAssessments,
  columnTypeOverrides,
  onChange,
}: ColumnTypeOverridePanelProps) {
  const columns = listTypeOverrideColumns(selectedTables, tableAssessments);
  const { data: catalog } = useQuery({
    queryKey: ["column-type-override-options"],
    queryFn: getColumnTypeOverrideOptions,
    staleTime: 60_000,
  });

  if (columns.length === 0) return null;

  const handleSelect = (key: string, optionId: string) => {
    onChange({ ...columnTypeOverrides, [key]: optionId });
  };

  return (
    <Card className="border-amber-500/40 bg-amber-500/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2 text-amber-300">
          <AlertTriangle className="h-4 w-4" />
          Unsupported SQL Server types — choose PostgreSQL targets
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          These columns have no automatic mapping. Pick a target PostgreSQL type for each column.
          The migration will apply an approved source cast during extraction — no silent conversion.
        </p>
        <div className="space-y-3">
          {columns.map(({ tableName, columnName, sourceType, overrideKey: key }) => {
            const options = catalog?.source_types?.[sourceType] ?? [];
            const selected = columnTypeOverrides[key] ?? "";
            const selectedOption = options.find((o) => o.option_id === selected);
            return (
              <div
                key={key}
                className="grid gap-2 rounded-md border border-border/60 bg-background/40 p-3 sm:grid-cols-[1fr_minmax(200px,280px)] sm:items-start"
              >
                <div className="space-y-1 min-w-0">
                  <p className="font-mono text-xs truncate">
                    {tableName}.{columnName}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    SQL Server: <span className="text-foreground/80">{sourceType}</span>
                  </p>
                  {selectedOption && (
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                      {selectedOption.description}
                      {selectedOption.requires_extension && (
                        <span className="block text-amber-400/90 mt-0.5">
                          Requires extension: {selectedOption.requires_extension}
                        </span>
                      )}
                    </p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`override-${key}`} className="text-[11px] text-muted-foreground">
                    PostgreSQL type
                  </Label>
                  <select
                    id={`override-${key}`}
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={selected}
                    onChange={(e) => handleSelect(key, e.target.value)}
                  >
                    <option value="">Select target type…</option>
                    {options.map((opt) => (
                      <option key={opt.option_id} value={opt.option_id}>
                        {opt.label} → {opt.pg_ddl_type}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            );
          })}
        </div>
        {columns.some((c) => !columnTypeOverrides[c.overrideKey]) && (
          <p className="text-[11px] text-amber-400/90">
            Select a target type for every column above before starting migration.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export { overrideKey };
