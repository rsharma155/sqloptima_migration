"use client";

/**
 * Module: page.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useCallback, useRef, useEffect, type ComponentProps } from "react";
import {
  ArrowRightLeft,
  AlertTriangle,
  Copy,
  FileCode,
  GitCompare,
  Loader2,
  CheckCircle2,
  XCircle,
  Braces,
  FunctionSquare,
  Settings2,
  Wrench,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import dynamic from "next/dynamic";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import {
  convertSql,
  type AppliedRepair,
  type DboSchemaStrategy,
  type PostgresSyntaxIssue,
} from "@/lib/api";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
});

const MonacoDiffEditor = dynamic(
  () => import("@monaco-editor/react").then((mod) => ({ default: mod.DiffEditor })),
  { ssr: false, loading: () => <Skeleton className="h-full w-full rounded-none" /> },
);

const SQL_KEYWORDS = [
  "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
  "DELETE", "CREATE", "TABLE", "ALTER", "DROP", "INDEX", "VIEW", "PROCEDURE",
  "FUNCTION", "TRIGGER", "BEGIN", "END", "IF", "ELSE", "WHILE", "CASE",
  "WHEN", "THEN", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AND",
  "OR", "NOT", "IN", "EXISTS", "LIKE", "BETWEEN", "IS", "NULL", "AS",
  "ORDER", "BY", "GROUP", "HAVING", "TOP", "DISTINCT", "UNION", "ALL",
  "DECLARE", "SET", "PRINT", "RETURN", "EXEC", "EXECUTE", "GO", "WITH",
  "GRANT", "REVOKE", "MERGE", "TRUNCATE", "USE", "DBCC", "CHECK", "CONSTRAINT",
  "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "CASCADE", "DEFAULT", "IDENTITY",
];

function validateSqlInput(text: string): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  const trimmed = text.trim();
  if (!trimmed) {
    errors.push("SQL input is empty");
    return { valid: false, errors };
  }

  if (trimmed.length < 6) {
    errors.push("Input is too short to be valid SQL");
    return { valid: false, errors };
  }

  const containsOnlySpecialChars = /^[\s\-\/\\|!@#$%^&*()_+=\[\]{};:'"<>,.?~`0-9]+$/.test(trimmed);
  if (containsOnlySpecialChars) {
    errors.push("Input contains only special characters, numbers, or symbols — not valid SQL");
    return { valid: false, errors };
  }

  const containsOnlyNumbers = /^\d+$/.test(trimmed);
  if (containsOnlyNumbers) {
    errors.push("Input is a numeric value, not valid SQL");
    return { valid: false, errors };
  }

  const upper = trimmed.toUpperCase();
  const hasKeyword = SQL_KEYWORDS.some((kw) => {
    const regex = new RegExp(`\\b${kw}\\b`);
    return regex.test(upper);
  });

  if (!hasKeyword) {
    const semicolons = (trimmed.match(/;/g) || []).length;
    const hasSqlishChars = /[=<>]/.test(trimmed);
    if (semicolons === 0 && !hasSqlishChars) {
      errors.push("Input does not contain any SQL keywords, operators, or statements");
      return { valid: false, errors };
    }
  }

  const commentOnly = /^\s*(\/\/|--|\/\*|\*\/|#)/.test(trimmed) &&
    !/\b(SELECT|FROM|WHERE|INSERT|CREATE|ALTER|DROP|UPDATE|DELETE|EXEC|WITH|DECLARE)\b/i.test(trimmed);
  if (commentOnly) {
    errors.push("Input contains only comments, not valid SQL statements");
    return { valid: false, errors };
  }

  if ((trimmed.match(/\(/g) || []).length !== (trimmed.match(/\)/g) || []).length) {
    errors.push("Mismatched parentheses in SQL input");
    return { valid: false, errors };
  }

  const quoteCount = (trimmed.match(/'/g) || []).length;
  if (quoteCount % 2 !== 0) {
    errors.push("Unclosed single-quoted string in SQL input");
    return { valid: false, errors };
  }

  const words = upper.split(/\s+/).filter(Boolean);
  if (words.length <= 2) {
    const incomplete = ["SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "BEGIN", "END", "DECLARE", "SET", "EXEC", "EXECUTE", "TRUNCATE", "MERGE", "WITH"];
    if (words.length === 1 && incomplete.includes(words[0])) {
      errors.push(`Incomplete SQL: "${words[0]}" alone is not a valid statement`);
      return { valid: false, errors };
    }
    if (words.length === 2) {
      const onlyKeywords = words.every(w => incomplete.includes(w));
      if (onlyKeywords) {
        errors.push(`Incomplete SQL: "${trimmed}" does not form a complete SQL statement`);
        return { valid: false, errors };
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

function formatPipelineStep(step: string): string {
  return step
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

const OBJECT_TYPE_OPTIONS = [
  { value: "auto", label: "Auto Detect", icon: Zap, description: "Automatically detect SQL type (recommended)" },
  { value: "raw", label: "Ad-hoc SQL", icon: Braces, description: "Convert without wrapping in a routine" },
  { value: "procedure", label: "Procedure", icon: Settings2, description: "CREATE PROCEDURE → PL/pgSQL PROCEDURE" },
  { value: "function", label: "Function", icon: FunctionSquare, description: "CREATE FUNCTION → PL/pgSQL FUNCTION" },
  { value: "trigger", label: "Trigger", icon: Settings2, description: "CREATE TRIGGER → PL/pgSQL TRIGGER" },
];

export default function SqlPage() {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [postgresSyntaxValid, setPostgresSyntaxValid] = useState<boolean | null>(null);
  const [postgresSyntaxErrors, setPostgresSyntaxErrors] = useState<PostgresSyntaxIssue[]>([]);
  const [postgresSyntaxWarnings, setPostgresSyntaxWarnings] = useState<string[]>([]);
  const [repairsApplied, setRepairsApplied] = useState<AppliedRepair[]>([]);
  const [repairExhausted, setRepairExhausted] = useState(false);
  const [parseUnblockersApplied, setParseUnblockersApplied] = useState<string[]>([]);
  const [bodyTransformFallback, setBodyTransformFallback] = useState(false);
  const [manualReviewRequired, setManualReviewRequired] = useState(false);
  const [converting, setConverting] = useState(false);
  const [viewMode, setViewMode] = useState<"editor" | "diff">("editor");
  const [hasConverted, setHasConverted] = useState(false);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; errors: string[] } | null>(null);
  const [objectType, setObjectType] = useState("auto");
  const [dboSchemaStrategy, setDboSchemaStrategy] = useState<DboSchemaStrategy>("map_to_public");
  const validDismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monaco source editor ref for jump-to-line on issue click
  type MonacoEditorType = NonNullable<ComponentProps<typeof MonacoEditor>["onMount"]> extends (e: infer E, ...rest: unknown[]) => unknown ? E : never;
  const sourceEditorRef = useRef<MonacoEditorType | null>(null);

  useEffect(() => {
    if (validationResult?.valid) {
      validDismissTimer.current = setTimeout(() => setValidationResult(null), 1000);
    }
    return () => {
      if (validDismissTimer.current) clearTimeout(validDismissTimer.current);
    };
  }, [validationResult]);

  const handleConvert = useCallback(async () => {
    if (!source.trim()) {
      toast.error("Please enter SQL to convert");
      return;
    }

    const validation = validateSqlInput(source);
    setValidationResult(validation);
    if (!validation.valid) {
      toast.error(`Validation failed: ${validation.errors[0]}`);
      return;
    }

    setConverting(true);
    setValidationResult(null);
    try {
      const result = await convertSql({
        sql: source,
        object_type: objectType,
        object_name: "usp_converted",
        schema: "dbo",
        dbo_schema_strategy: dboSchemaStrategy,
      });
      setTarget(result.converted_sql);
      setWarnings(result.warnings);
      setErrors(result.errors);
      setPostgresSyntaxValid(result.postgres_syntax_valid);
      setPostgresSyntaxErrors(result.postgres_syntax_errors ?? []);
      setPostgresSyntaxWarnings(result.postgres_syntax_warnings ?? []);
      setRepairsApplied(result.repairs_applied ?? []);
      setRepairExhausted(result.repair_exhausted ?? false);
      setParseUnblockersApplied(result.parse_unblockers_applied ?? []);
      setBodyTransformFallback(result.body_transform_fallback ?? false);
      setManualReviewRequired(result.manual_review_required ?? false);
      setHasConverted(true);
      if (result.success && result.postgres_syntax_valid) {
        toast.success("SQL converted and PostgreSQL syntax validated");
      } else if (result.success && !result.postgres_syntax_valid) {
        toast.warning("Converted, but PostgreSQL syntax validation found issues");
      } else if (result.errors.length > 0) {
        toast.error(`Conversion failed: ${result.errors[0]}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Conversion failed";
      toast.error(msg);
    } finally {
      setConverting(false);
    }
  }, [source, objectType, dboSchemaStrategy]);

  const handleValidate = useCallback(() => {
    if (!source.trim()) {
      toast.error("Nothing to validate");
      return;
    }
    const result = validateSqlInput(source);
    setValidationResult(result);
    if (result.valid) {
      toast.success("SQL input looks valid");
    } else {
      toast.error(`Validation: ${result.errors[0]}`);
    }
  }, [source]);

  const handleCopyTarget = useCallback(() => {
    if (!target) return;
    navigator.clipboard.writeText(target);
    if (postgresSyntaxValid === false) {
      toast.warning("Copied with syntax issues — validate on your PostgreSQL server before use");
      return;
    }
    toast.success("Copied to clipboard");
  }, [target, postgresSyntaxValid]);

  // Jump to the first match of a keyword from the issue message in the source editor
  const handleIssueClick = useCallback((message: string) => {
    const editor = sourceEditorRef.current;
    if (!editor || !source) return;
    const wordMatch = message.match(/\b([A-Z_]{3,})\b/);
    if (wordMatch) {
      const model = (editor as unknown as { getModel: () => { findMatches: (s: string, ...a: unknown[]) => Array<{ range: { startLineNumber: number } }> } | null }).getModel();
      if (model) {
        const matches = model.findMatches(wordMatch[1], false, false, false, null, false);
        if (matches.length > 0) {
          const line = matches[0].range.startLineNumber;
          (editor as unknown as { revealLineInCenter: (l: number) => void }).revealLineInCenter(line);
          (editor as unknown as { setPosition: (p: { lineNumber: number; column: number }) => void }).setPosition({ lineNumber: line, column: 1 });
          (editor as unknown as { focus: () => void }).focus();
          return;
        }
      }
    }
    (editor as unknown as { revealLine: (l: number) => void }).revealLine(1);
    (editor as unknown as { focus: () => void }).focus();
  }, [source]);

  const handleSourceChange = useCallback((val: string | undefined) => {
    setSource(val ?? "");
    setValidationResult(null);
    if (hasConverted) {
      setHasConverted(false);
      setTarget("");
      setWarnings([]);
      setErrors([]);
      setPostgresSyntaxValid(null);
      setPostgresSyntaxErrors([]);
      setPostgresSyntaxWarnings([]);
      setRepairsApplied([]);
      setRepairExhausted(false);
      setParseUnblockersApplied([]);
      setBodyTransformFallback(false);
      setManualReviewRequired(false);
    }
  }, [hasConverted]);

  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbers: "on" as const,
    scrollBeyondLastLine: false,
    wordWrap: "on" as const,
    padding: { top: 8 },
  };

  // Keep a ref to the DiffEditor instance so we can dispose it safely before
  // React unmounts the component. Without this, Monaco throws
  // "TextModel got disposed before DiffEditorWidget model got reset" on navigation.
  const diffEditorRef = useRef<Parameters<NonNullable<React.ComponentProps<typeof MonacoDiffEditor>["onMount"]>>[0] | null>(null);
  useEffect(() => {
    return () => {
      try { diffEditorRef.current?.dispose(); } catch { /* suppress disposal race */ }
      diffEditorRef.current = null;
    };
  }, []);

  const autoFixCount = repairsApplied.length + parseUnblockersApplied.length;
  const showConversionReport =
    hasConverted &&
    (autoFixCount > 0 ||
      manualReviewRequired ||
      repairExhausted ||
      bodyTransformFallback ||
      warnings.length > 0 ||
      errors.length > 0 ||
      postgresSyntaxErrors.length > 0 ||
      postgresSyntaxWarnings.length > 0);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">SQL Converter</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Convert SQL Server T-SQL to PostgreSQL-compatible syntax
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.accept = ".sql,.txt";
              input.onchange = async (e) => {
                const file = (e.target as HTMLInputElement).files?.[0];
                if (file) {
                  const text = await file.text();
                  setSource(text);
                  toast.success(`Loaded "${file.name}"`);
                }
              };
              input.click();
            }}
          >
            Load File
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleValidate}
            disabled={!source.trim()}
          >
            Validate
          </Button>
          <Button size="sm" onClick={handleConvert} disabled={converting || !source.trim()}>
            {converting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <ArrowRightLeft className="h-4 w-4 mr-2" />
            )}
            {converting ? "Converting..." : "Convert"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">dbo schema:</span>
        <Button
          variant={dboSchemaStrategy === "map_to_public" ? "default" : "outline"}
          size="sm"
          className="h-7 text-xs"
          onClick={() => setDboSchemaStrategy("map_to_public")}
          title="Map SQL Server dbo to PostgreSQL public (default)"
        >
          dbo → public
        </Button>
        <Button
          variant={dboSchemaStrategy === "preserve_dbo" ? "default" : "outline"}
          size="sm"
          className="h-7 text-xs"
          onClick={() => setDboSchemaStrategy("preserve_dbo")}
          title="Keep dbo schema on PostgreSQL so schema-qualified references resolve"
        >
          Keep dbo
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">Convert as:</span>
        {OBJECT_TYPE_OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const isActive = objectType === opt.value;
          return (
            <Button
              key={opt.value}
              variant={isActive ? "default" : "outline"}
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={() => setObjectType(opt.value)}
              title={opt.description}
            >
              <Icon className="h-3.5 w-3.5" />
              {opt.label}
            </Button>
          );
        })}
      </div>

      {validationResult && !validationResult.valid && (
        <Card className="border-destructive/50">
          <CardContent className="py-3">
            <div className="flex items-start gap-2">
              <XCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-destructive">Invalid SQL Input</p>
                <ul className="list-disc list-inside mt-1">
                  {validationResult.errors.map((e, i) => (
                    <li key={i} className="text-xs text-muted-foreground">{e}</li>
                  ))}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {validationResult && validationResult.valid && (
        <Card className="border-emerald-500/50">
          <CardContent className="py-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              <p className="text-sm font-medium text-emerald-500">SQL input looks valid</p>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base">SQL Editor</CardTitle>
                <CardDescription>
                  Paste SQL Server T-SQL, convert it, and review the diff
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Tabs
                  value={viewMode}
                  onValueChange={(v) => setViewMode(v as "editor" | "diff")}
                  className="h-8"
                >
                  <TabsList className="h-8">
                    <TabsTrigger value="editor" className="h-7 text-xs gap-1.5 px-2.5">
                      <FileCode className="h-3.5 w-3.5" />
                      Editor
                    </TabsTrigger>
                    <TabsTrigger value="diff" className="h-7 text-xs gap-1.5 px-2.5">
                      <GitCompare className="h-3.5 w-3.5" />
                      Diff View
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
                {target && viewMode === "editor" && (
                  <Button variant="outline" size="sm" onClick={handleCopyTarget}>
                    <Copy className="h-4 w-4 mr-2" />
                    Copy Result
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {viewMode === "editor" && (
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                      <Badge variant="outline" className="text-[10px] px-1 py-0">
                        SQL Server
                      </Badge>
                      Source
                    </span>
                    <span className="text-xs text-muted-foreground font-mono">
                      {source ? `${source.split("\n").length} lines · ${source.length.toLocaleString()} chars` : "0 lines"}
                    </span>
                  </div>
                  <div className="h-[400px] rounded-lg border overflow-hidden">
                    <MonacoEditor
                      language="sql"
                      theme="vs-dark"
                      value={source}
                      onChange={handleSourceChange}
                      onMount={(editor) => { sourceEditorRef.current = editor as unknown as MonacoEditorType; }}
                      options={editorOptions}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                      <Badge variant="secondary" className="text-[10px] px-1 py-0">
                        PostgreSQL
                      </Badge>
                      Target
                      {hasConverted && postgresSyntaxValid === true && (
                        <Badge className="text-[10px] px-1.5 py-0 bg-emerald-500/15 text-emerald-600 border-emerald-500/30">
                          Syntax OK
                        </Badge>
                      )}
                      {hasConverted && postgresSyntaxValid === false && (
                        <Badge variant="destructive" className="text-[10px] px-1.5 py-0">
                          Syntax Issues
                        </Badge>
                      )}
                    </span>
                    {target && (
                      <span className="text-xs text-muted-foreground">
                        {target.split("\n").length} lines
                      </span>
                    )}
                  </div>
                  <div className="h-[400px] rounded-lg border overflow-hidden">
                    <MonacoEditor
                      language="sql"
                      theme="vs-dark"
                      value={target || '-- Click "Convert" to see the result'}
                      options={{ ...editorOptions, readOnly: true }}
                    />
                  </div>
                </div>
              </div>
            )}

            {viewMode === "diff" && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                    <Badge variant="outline" className="text-[10px] px-1 py-0">SQL Server</Badge>
                    Source
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {target ? `${source.split("\n").length} \u2192 ${target.split("\n").length} lines` : "Convert first"}
                  </span>
                </div>
                <div className="h-[450px] rounded-lg border overflow-hidden">
                  <MonacoDiffEditor
                    original={source || " "}
                    modified={target || " "}
                    language="sql"
                    theme="vs-dark"
                    onMount={(editor) => { diffEditorRef.current = editor; }}
                    options={{
                      ...editorOptions,
                      readOnly: true,
                      renderSideBySide: true,
                      originalEditable: false,
                      diffWordWrap: "on",
                    }}
                  />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {showConversionReport && (
          <Card className="lg:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-3">
                <CardTitle className="text-base flex items-center gap-2">
                  {manualReviewRequired ? (
                    <AlertTriangle className="h-4 w-4 text-amber-500" />
                  ) : autoFixCount > 0 ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-amber-500" />
                  )}
                  Conversion Report
                </CardTitle>
                <div className="flex gap-2 ml-auto flex-wrap justify-end">
                  {manualReviewRequired && (
                    <Badge variant="destructive" className="text-xs">
                      Manual review required
                    </Badge>
                  )}
                  {autoFixCount > 0 && (
                    <Badge className="text-xs bg-emerald-500/15 text-emerald-600 border-emerald-500/30">
                      Auto-fixed {autoFixCount} issue{autoFixCount !== 1 ? "s" : ""}
                    </Badge>
                  )}
                  {repairExhausted && (
                    <Badge className="text-xs bg-amber-500/15 text-amber-600 border-amber-500/30">
                      Repair limit reached
                    </Badge>
                  )}
                  {bodyTransformFallback && (
                    <Badge className="text-xs bg-amber-500/15 text-amber-600 border-amber-500/30">
                      Body-transform fallback
                    </Badge>
                  )}
                  {postgresSyntaxValid === false && (
                    <Badge variant="destructive" className="text-xs">
                      PostgreSQL syntax failed
                    </Badge>
                  )}
                  {postgresSyntaxValid === true && !manualReviewRequired && (
                    <Badge className="text-xs bg-emerald-500/15 text-emerald-600 border-emerald-500/30">
                      PostgreSQL syntax passed
                    </Badge>
                  )}
                  {errors.length > 0 && (
                    <Badge variant="destructive" className="text-xs">
                      {errors.length} error{errors.length !== 1 ? "s" : ""}
                    </Badge>
                  )}
                  {warnings.length > 0 && (
                    <Badge className="text-xs bg-amber-500/15 text-amber-500 border-amber-500/30">
                      {warnings.length} warning{warnings.length !== 1 ? "s" : ""}
                    </Badge>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {(repairsApplied.length > 0 || parseUnblockersApplied.length > 0) && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-emerald-600 flex items-center gap-1.5">
                    <Wrench className="h-3.5 w-3.5" />
                    Auto-fixes applied
                  </p>
                  {parseUnblockersApplied.map((step) => (
                    <div
                      key={`unblock-${step}`}
                      className="w-full text-left border-l-2 border-emerald-500 bg-emerald-500/5 rounded-r px-3 py-2"
                    >
                      <p className="text-xs font-medium text-emerald-600 mb-0.5">
                        T-SQL parse unblocker
                      </p>
                      <p className="text-xs text-muted-foreground">{formatPipelineStep(step)}</p>
                    </div>
                  ))}
                  {repairsApplied.map((repair, i) => (
                    <div
                      key={`repair-${repair.fixer}-${i}`}
                      className="w-full text-left border-l-2 border-emerald-500 bg-emerald-500/5 rounded-r px-3 py-2"
                    >
                      <p className="text-xs font-medium text-emerald-600 mb-0.5">
                        pgparse repair{repair.line ? ` (line ${repair.line})` : ""}
                      </p>
                      <p className="text-xs text-muted-foreground">{repair.description}</p>
                    </div>
                  ))}
                </div>
              )}

              {manualReviewRequired && (
                <div className="border-l-2 border-destructive bg-destructive/5 rounded-r px-3 py-2">
                  <p className="text-xs font-medium text-destructive mb-0.5">Manual review required</p>
                  <p className="text-xs text-muted-foreground">
                    {repairExhausted
                      ? "Automatic repair reached its limit; remaining issues need human review before production use."
                      : bodyTransformFallback
                        ? "Conversion used the body-transform fallback path — verify logic and syntax on your PostgreSQL server."
                        : "Conversion completed with errors or failed PostgreSQL syntax validation — review the items below."}
                  </p>
                </div>
              )}

              {postgresSyntaxErrors.map((issue, i) => (
                <div
                  key={`pg-${i}`}
                  className="w-full text-left border-l-2 border-destructive bg-destructive/5 rounded-r px-3 py-2"
                >
                  <p className="text-xs font-medium text-destructive mb-0.5">
                    PostgreSQL Syntax{issue.line ? ` (line ${issue.line})` : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">{issue.message}</p>
                </div>
              ))}
              {postgresSyntaxWarnings.map((w, i) => (
                <div
                  key={`pgw-${i}`}
                  className="w-full text-left border-l-2 border-amber-500 bg-amber-500/5 rounded-r px-3 py-2"
                >
                  <p className="text-xs font-medium text-amber-500 mb-0.5">Parser Notice</p>
                  <p className="text-xs text-muted-foreground">{w}</p>
                </div>
              ))}
              {/* Errors first — highest severity */}
              {errors.map((e, i) => (
                <button
                  key={`e-${i}`}
                  className="w-full text-left border-l-2 border-destructive bg-destructive/5 rounded-r px-3 py-2 hover:bg-destructive/10 transition-colors cursor-pointer"
                  onClick={() => handleIssueClick(e)}
                  title="Click to jump to related code in editor"
                >
                  <p className="text-xs font-medium text-destructive mb-0.5">Error</p>
                  <p className="text-xs text-muted-foreground">{e}</p>
                </button>
              ))}
              {/* Warnings after */}
              {warnings.map((w, i) => (
                <button
                  key={`w-${i}`}
                  className="w-full text-left border-l-2 border-amber-500 bg-amber-500/5 rounded-r px-3 py-2 hover:bg-amber-500/10 transition-colors cursor-pointer"
                  onClick={() => handleIssueClick(w)}
                  title="Click to jump to related code in editor"
                >
                  <p className="text-xs font-medium text-amber-500 mb-0.5">Warning</p>
                  <p className="text-xs text-muted-foreground">{w}</p>
                </button>
              ))}
            </CardContent>
          </Card>
        )}

        <Card className="lg:col-span-2 border-muted">
          <CardContent className="py-4 space-y-2">
            {hasConverted && target && (
              <p className="text-xs text-muted-foreground leading-relaxed">
                Converted PostgreSQL output is automatically parsed for syntax errors and common
                unconverted T-SQL patterns before it is shown here. This check does not guarantee
                runtime correctness — please run the script on your target PostgreSQL server
                (ideally in a transaction you can roll back) to confirm it compiles and behaves as
                expected before using it in production.
              </p>
            )}
            <p className="text-xs text-muted-foreground leading-relaxed">
              PostgreSQL syntax validation uses{" "}
              <a
                href="https://github.com/gmr/pgparse"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-foreground"
              >
                pgparse
              </a>{" "}
              by Gavin M. Roy, AWeber.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
