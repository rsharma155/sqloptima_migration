"use client";

/**
 * Module: connection-privilege-scripts-panel.tsx
 * Purpose: Display least-privilege SQL bootstrap scripts for source/target connections
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, Check, ShieldCheck, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { toast } from "sonner";
import {
  getConnectionPrivilegeScripts,
  type PrivilegeScriptInfo,
} from "@/lib/api";

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(`${label} copied to clipboard`);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy to clipboard");
    }
  }, [text, label]);

  return (
    <Button variant="outline" size="sm" onClick={handleCopy}>
      {copied ? (
        <Check className="h-4 w-4 mr-2 text-emerald-500" />
      ) : (
        <Copy className="h-4 w-4 mr-2" />
      )}
      {copied ? "Copied" : "Copy script"}
    </Button>
  );
}

function ScriptSection({
  script,
  accent,
}: {
  script: PrivilegeScriptInfo;
  accent: "blue" | "emerald";
}) {
  const [expanded, setExpanded] = useState(false);
  const loginHint =
    script.recommended_login ?? script.recommended_role ?? "migration_user";

  const accentClasses =
    accent === "blue"
      ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
      : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";

  return (
    <div className="rounded-lg border">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
        aria-expanded={expanded}
      >
        <div className="space-y-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${accentClasses}`}>
              {script.engine === "sqlserver" ? "SQL Server" : "PostgreSQL"}
            </span>
            <span className="text-sm font-medium">{script.title}</span>
          </div>
          <p className="text-xs text-muted-foreground">{script.purpose}</p>
          <p className="text-xs text-muted-foreground font-mono truncate">
            {script.file}
          </p>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground mt-1" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground mt-1" />
        )}
      </button>

      {expanded && (
        <div className="border-t px-4 py-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Granted
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {script.privileges.map((p) => (
                  <Badge key={p} variant="secondary" className="text-[10px] font-normal">
                    {p}
                  </Badge>
                ))}
              </ul>
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Not granted
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {script.not_granted.map((p) => (
                  <Badge key={p} variant="outline" className="text-[10px] font-normal">
                    {p}
                  </Badge>
                ))}
              </ul>
            </div>
          </div>

          {script.capabilities.length > 0 && (
            <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5">
              {script.capabilities.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}

          <div className="rounded-md bg-muted/40 px-3 py-2 text-xs space-y-1">
            <p>
              <span className="text-muted-foreground">Recommended user: </span>
              <code className="font-mono">{loginHint}</code>
            </p>
            {script.run_example && (
              <p className="font-mono text-[11px] break-all text-muted-foreground">
                {script.run_example}
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <CopyButton text={script.content} label={script.title} />
          </div>

          <pre className="text-[11px] font-mono overflow-auto max-h-[420px] p-4 bg-muted/30 rounded-lg whitespace-pre-wrap break-words border">
            {script.content}
          </pre>
        </div>
      )}
    </div>
  );
}

export function ConnectionPrivilegeScriptsPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["connection-privilege-scripts"],
    queryFn: getConnectionPrivilegeScripts,
    staleTime: 5 * 60_000,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-5 w-5" />
          Least-privilege database users
        </CardTitle>
        <CardDescription>
          Run these scripts as a DBA before adding connections. They create scoped
          users with the minimum permissions the migration platform needs on source
          (read-only SQL Server) and target (PostgreSQL DDL/DML).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading bootstrap scripts…
          </div>
        )}
        {isError && (
          <p className="text-sm text-destructive">
            Could not load privilege scripts from the API. Ensure the backend is running.
          </p>
        )}
        {data && (
          <div className="space-y-3">
            <ScriptSection script={data.source} accent="blue" />
            <ScriptSection script={data.target} accent="emerald" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
