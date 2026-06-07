/**
 * Module: app/admin/settings/page.tsx
 * Purpose: Platform configuration page — API endpoint, theme, log level,
 *          retention policy trigger, and ODBC driver check.  Admin access
 *          required for destructive actions; all users can update UI prefs.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
"use client";

import { useState, useEffect } from "react";
import {
  Settings,
  Save,
  Loader2,
  Trash2,
  CheckCircle2,
  XCircle,
  Database,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { getApiBase, refreshApiBase } from "@/lib/api";

// ---------------------------------------------------------------------------
// Retention trigger
// ---------------------------------------------------------------------------

async function triggerRetention(
  maxAgeDays: number,
  keepFailed: boolean,
  dryRun: boolean,
): Promise<{ deleted: number; scanned: number; dry_run: boolean }> {
  const base = getApiBase();
  const token = localStorage.getItem("auth_token");
  const res = await fetch(`${base}/admin/retention/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      max_age_days: maxAgeDays,
      keep_failed: keepFailed,
      dry_run: dryRun,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function checkOdbc(): Promise<{
  available: boolean;
  drivers: string[];
  message: string;
}> {
  const base = getApiBase();
  const token = localStorage.getItem("auth_token");
  const res = await fetch(`${base}/admin/odbc/check`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Theme = "dark" | "light" | "system";

export default function AdminSettingsPage() {
  // UI preferences
  const [apiEndpoint, setApiEndpoint] = useState("");
  const [theme, setTheme] = useState<Theme>("dark");

  // Retention settings
  const [maxAgeDays, setMaxAgeDays] = useState(90);
  const [keepFailed, setKeepFailed] = useState(false);
  const [retentionRunning, setRetentionRunning] = useState(false);
  const [retentionResult, setRetentionResult] = useState<{
    deleted: number; scanned: number; dry_run: boolean;
  } | null>(null);

  // ODBC check
  const [odbcResult, setOdbcResult] = useState<{
    available: boolean; drivers: string[]; message: string;
  } | null>(null);
  const [odbcChecking, setOdbcChecking] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("api_endpoint") || "http://localhost:8508";
    setApiEndpoint(saved);
    const savedTheme = (localStorage.getItem("theme") as Theme) || "dark";
    setTheme(savedTheme);
  }, []);

  const savePreferences = () => {
    localStorage.setItem("api_endpoint", apiEndpoint);
    refreshApiBase();
    document.documentElement.className = theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
      : theme;
    localStorage.setItem("theme", theme);
    toast.success("Preferences saved");
  };

  const handleRetention = async (dryRun: boolean) => {
    setRetentionRunning(true);
    setRetentionResult(null);
    try {
      const result = await triggerRetention(maxAgeDays, keepFailed, dryRun);
      setRetentionResult(result);
      toast.success(
        dryRun
          ? `Dry run: would delete ${result.deleted} of ${result.scanned} jobs`
          : `Deleted ${result.deleted} of ${result.scanned} jobs`,
      );
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Retention failed");
    } finally {
      setRetentionRunning(false);
    }
  };

  const handleOdbcCheck = async () => {
    setOdbcChecking(true);
    try {
      const result = await checkOdbc();
      setOdbcResult(result);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "ODBC check failed");
    } finally {
      setOdbcChecking(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Platform Settings"
        description="Configure API endpoint, appearance, and admin maintenance tasks"
      />

      {/* ---- UI Preferences ---- */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Settings className="h-4 w-4" /> UI Preferences
          </CardTitle>
          <CardDescription>Stored in localStorage — no server required</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="api-url">API Base URL</Label>
            <Input
              id="api-url"
              value={apiEndpoint}
              onChange={(e) => setApiEndpoint(e.target.value)}
              placeholder="http://localhost:8508"
            />
          </div>
          <div className="space-y-1">
            <Label>Theme</Label>
            <div className="flex gap-2">
              {(["dark", "light", "system"] as Theme[]).map((t) => (
                <Button
                  key={t}
                  size="sm"
                  variant={theme === t ? "default" : "outline"}
                  className="capitalize"
                  onClick={() => setTheme(t)}
                >
                  {t}
                </Button>
              ))}
            </div>
          </div>
          <Button onClick={savePreferences}>
            <Save className="h-4 w-4 mr-1" /> Save Preferences
          </Button>
        </CardContent>
      </Card>

      {/* ---- Job Retention ---- */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-red-400" /> Job Retention
          </CardTitle>
          <CardDescription>
            Remove old migration job records. Admin access required.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="max-age">Max age (days)</Label>
              <Input
                id="max-age"
                type="number"
                min={1}
                max={3650}
                value={maxAgeDays}
                onChange={(e) => setMaxAgeDays(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1 flex flex-col justify-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={keepFailed}
                  onChange={(e) => setKeepFailed(e.target.checked)}
                  className="rounded border-input"
                />
                Keep failed jobs
              </label>
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={retentionRunning}
              onClick={() => handleRetention(true)}
            >
              {retentionRunning ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Dry Run
            </Button>
            <Button
              variant="destructive"
              disabled={retentionRunning}
              onClick={() => handleRetention(false)}
            >
              {retentionRunning ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Run Now
            </Button>
          </div>
          {retentionResult && (
            <div className="rounded border border-border bg-muted/20 px-4 py-3 text-sm">
              {retentionResult.dry_run && (
                <Badge variant="secondary" className="mb-2">Dry Run</Badge>
              )}
              <p>Scanned: <strong>{retentionResult.scanned}</strong></p>
              <p className="text-red-400">
                {retentionResult.dry_run ? "Would delete" : "Deleted"}:{" "}
                <strong>{retentionResult.deleted}</strong>
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- ODBC Driver Check ---- */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Database className="h-4 w-4" /> ODBC Driver Check
          </CardTitle>
          <CardDescription>
            Verify that the SQL Server ODBC driver is installed on the host
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button
            variant="outline"
            onClick={handleOdbcCheck}
            disabled={odbcChecking}
          >
            {odbcChecking ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Database className="h-4 w-4 mr-1" />
            )}
            Check Drivers
          </Button>
          {odbcResult && (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                {odbcResult.available ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                ) : (
                  <XCircle className="h-4 w-4 text-red-400" />
                )}
                <span>{odbcResult.message}</span>
              </div>
              {odbcResult.drivers.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Installed drivers:</p>
                  <ul className="space-y-0.5">
                    {odbcResult.drivers.map((d) => (
                      <li key={d} className="text-xs font-mono text-muted-foreground">
                        {d}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
