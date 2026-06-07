"use client";

/**
 * Module: app/admin/page.tsx
 * Purpose: Combined admin page — User Management and Platform Settings in tabs.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback } from "react";
import {
  Users,
  Plus,
  Trash2,
  Loader2,
  Shield,
  Eye,
  RefreshCw,
  Settings,
  Save,
  Database,
  CheckCircle2,
  XCircle,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { CreateUserDialog } from "@/components/admin/create-user-dialog";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getUsers,
  updateUserRole,
  deleteUser,
  getApiBase,
  refreshApiBase,
  type UserRecord,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Role = "admin" | "operator" | "viewer";
type Theme = "dark" | "light" | "system";

// ---------------------------------------------------------------------------
// User management helpers
// ---------------------------------------------------------------------------

const ROLE_CONFIG: Record<Role, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  admin:    { label: "Admin",    color: "text-red-400 border-red-500/30 bg-red-500/10",    icon: Shield },
  operator: { label: "Operator", color: "text-blue-400 border-blue-500/30 bg-blue-500/10", icon: Shield },
  viewer:   { label: "Viewer",   color: "text-slate-400 border-slate-500/30 bg-slate-500/10", icon: Eye },
};

function RoleBadge({ role }: { role: Role }) {
  const cfg = ROLE_CONFIG[role] ?? ROLE_CONFIG.viewer;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${cfg.color}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Admin retention / ODBC helpers
// ---------------------------------------------------------------------------

async function triggerRetention(maxAgeDays: number, keepFailed: boolean, dryRun: boolean) {
  const base = getApiBase();
  const token = localStorage.getItem("auth_token");
  const res = await fetch(`${base}/admin/retention/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ max_age_days: maxAgeDays, keep_failed: keepFailed, dry_run: dryRun }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ deleted: number; scanned: number; dry_run: boolean }>;
}

async function checkOdbc() {
  const base = getApiBase();
  const token = localStorage.getItem("auth_token");
  const res = await fetch(`${base}/admin/odbc/check`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ available: boolean; drivers: string[]; message: string }>;
}

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------

function UsersTab() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserRecord | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getUsers();
      setUsers(data);
    } catch {
      toast.error("Failed to load users — Admin role required");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRoleChange = async (user: UserRecord, role: Role) => {
    if (role === user.role) return;
    setUpdatingId(user.id);
    try {
      await updateUserRole(user.id, role);
      toast.success(`Role updated to ${role}`);
      load();
    } catch {
      toast.error("Role update failed");
    } finally {
      setUpdatingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteUser(deleteTarget.id);
      toast.success(`User ${deleteTarget.username} deleted`);
      setDeleteTarget(null);
      load();
    } catch {
      toast.error("Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          {(["admin", "operator", "viewer"] as Role[]).map((r) => (
            <span key={r} className="flex items-center gap-1">
              <RoleBadge role={r} />
              {r === "admin" && "— full platform access"}
              {r === "operator" && "— run migrations, view all"}
              {r === "viewer" && "— read-only access"}
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4 mr-1" /> New User
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-16" role="status" aria-label="Loading">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : users.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No users found"
          description="Create the first user or check that you are authenticated as an Admin."
          actionLabel="Create User"
          onAction={() => setShowCreate(true)}
        />
      ) : (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{users.length} users</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Username</th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Email</th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Role</th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Status</th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Created</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-b border-border hover:bg-muted/20 transition-colors">
                      <td className="px-4 py-2 font-medium">{u.username}</td>
                      <td className="px-4 py-2 text-muted-foreground">{u.email}</td>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <RoleBadge role={u.role as Role} />
                          <select
                            value={u.role}
                            onChange={(e) => handleRoleChange(u, e.target.value as Role)}
                            disabled={updatingId === u.id}
                            className="text-xs rounded border border-input bg-background px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-ring"
                          >
                            <option value="viewer">viewer</option>
                            <option value="operator">operator</option>
                            <option value="admin">admin</option>
                          </select>
                          {updatingId === u.id && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
                        </div>
                      </td>
                      <td className="px-4 py-2">
                        <Badge
                          variant={u.is_active ? "default" : "secondary"}
                          className={u.is_active ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : ""}
                        >
                          {u.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-muted-foreground text-xs">
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-2">
                        <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive hover:text-destructive" onClick={() => setDeleteTarget(u)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <CreateUserDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        onCreated={load}
      />

      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>Delete <strong>{deleteTarget?.username}</strong>? This cannot be undone.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Platform Settings tab
// ---------------------------------------------------------------------------

function PlatformSettingsTab() {
  const [apiEndpoint, setApiEndpoint] = useState("");
  const [theme, setTheme] = useState<Theme>("dark");
  const [maxAgeDays, setMaxAgeDays] = useState(90);
  const [keepFailed, setKeepFailed] = useState(false);
  const [retentionRunning, setRetentionRunning] = useState(false);
  const [retentionResult, setRetentionResult] = useState<{ deleted: number; scanned: number; dry_run: boolean } | null>(null);
  const [odbcResult, setOdbcResult] = useState<{ available: boolean; drivers: string[]; message: string } | null>(null);
  const [odbcChecking, setOdbcChecking] = useState(false);

  useEffect(() => {
    setApiEndpoint(localStorage.getItem("api_endpoint") || "http://localhost:8508");
    setTheme((localStorage.getItem("theme") as Theme) || "dark");
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
      toast.success(dryRun ? `Dry run: would delete ${result.deleted} of ${result.scanned} jobs` : `Deleted ${result.deleted} of ${result.scanned} jobs`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Retention failed");
    } finally {
      setRetentionRunning(false);
    }
  };

  const handleOdbcCheck = async () => {
    setOdbcChecking(true);
    try {
      setOdbcResult(await checkOdbc());
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "ODBC check failed");
    } finally {
      setOdbcChecking(false);
    }
  };

  return (
    <div className="space-y-6">
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
            <Input id="api-url" value={apiEndpoint} onChange={(e) => setApiEndpoint(e.target.value)} placeholder="http://localhost:8508" />
          </div>
          <div className="space-y-1">
            <Label>Theme</Label>
            <div className="flex gap-2">
              {(["dark", "light", "system"] as Theme[]).map((t) => (
                <Button key={t} size="sm" variant={theme === t ? "default" : "outline"} className="capitalize" onClick={() => setTheme(t)}>{t}</Button>
              ))}
            </div>
          </div>
          <Button onClick={savePreferences}>
            <Save className="h-4 w-4 mr-1" /> Save Preferences
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-red-400" /> Job Retention
          </CardTitle>
          <CardDescription>Remove old migration job records. Admin access required.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="max-age">Max age (days)</Label>
              <Input id="max-age" type="number" min={1} max={3650} value={maxAgeDays} onChange={(e) => setMaxAgeDays(Number(e.target.value))} />
            </div>
            <div className="space-y-1 flex flex-col justify-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={keepFailed} onChange={(e) => setKeepFailed(e.target.checked)} className="rounded border-input" />
                Keep failed jobs
              </label>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={retentionRunning} onClick={() => handleRetention(true)}>
              {retentionRunning ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null} Dry Run
            </Button>
            <Button variant="destructive" disabled={retentionRunning} onClick={() => handleRetention(false)}>
              {retentionRunning ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null} Run Now
            </Button>
          </div>
          {retentionResult && (
            <div className="rounded border border-border bg-muted/20 px-4 py-3 text-sm">
              {retentionResult.dry_run && <Badge variant="secondary" className="mb-2">Dry Run</Badge>}
              <p>Scanned: <strong>{retentionResult.scanned}</strong></p>
              <p className="text-red-400">{retentionResult.dry_run ? "Would delete" : "Deleted"}: <strong>{retentionResult.deleted}</strong></p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Database className="h-4 w-4" /> ODBC Driver Check
          </CardTitle>
          <CardDescription>Verify that the SQL Server ODBC driver is installed on the host</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button variant="outline" onClick={handleOdbcCheck} disabled={odbcChecking}>
            {odbcChecking ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Database className="h-4 w-4 mr-1" />}
            Check Drivers
          </Button>
          {odbcResult && (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                {odbcResult.available ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <XCircle className="h-4 w-4 text-red-400" />}
                <span>{odbcResult.message}</span>
              </div>
              {odbcResult.drivers.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Installed drivers:</p>
                  <ul className="space-y-0.5">
                    {odbcResult.drivers.map((d) => (
                      <li key={d} className="text-xs font-mono text-muted-foreground">{d}</li>
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminPage() {
  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Admin"
        description="User management and platform configuration"
      />
      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users" className="gap-2">
            <Users className="h-4 w-4" /> Users
          </TabsTrigger>
          <TabsTrigger value="platform" className="gap-2">
            <Settings className="h-4 w-4" /> Platform Settings
          </TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="mt-6">
          <UsersTab />
        </TabsContent>
        <TabsContent value="platform" className="mt-6">
          <PlatformSettingsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
