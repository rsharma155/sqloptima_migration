"use client";

/**
 * Module: page.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useTheme } from "next-themes";
import {
  Sun,
  Moon,
  Monitor,
  Database,
  Plus,
  Trash2,
  Plug,
  Cpu,
  Save,
  AlertCircle,
  X,
  Eye,
  EyeOff,
  Loader2,
  Bell,
  Mail,
  Webhook,
  TriangleAlert,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
  ApiError,
  createConnection as apiCreateConnection,
  updateConnection as apiUpdateConnection,
  testConnection as apiTestConnection,
  testRawConnection as apiTestRawConnection,
  refreshApiBase,
  getAlertConfig,
  testAlertChannels,
  type AlertConfigResponse,
} from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import {
  type Connection,
  CONNECTIONS_UPDATED_EVENT,
  clearConnectionTombstone,
  dedupeConnections,
  fetchAndSyncConnections,
  loadConnections,
  removeConnection,
  saveConnections,
} from "@/lib/connection-store";
import {
  findDuplicateName,
  findSimilarConnections,
} from "@/lib/connection-dedupe";
import {
  loadMigrationEnvironment,
  saveMigrationEnvironment,
  type MigrationEnvironment,
} from "@/lib/migration-snapshot";

type Theme = "dark" | "light" | "system";

interface FormErrors {
  [key: string]: string;
}

let connectionCounter = 0;
function generateId() {
  connectionCounter++;
  return `conn-${Date.now()}-${connectionCounter}`;
}

export default function SettingsPage() {
  const { theme: currentTheme, setTheme: setNextTheme } = useTheme();
  const theme = (currentTheme as Theme) ?? "dark";
  const [mounted, setMounted] = useState(false);
  const [apiEndpoint, setApiEndpoint] = useState("http://localhost:8508");
  const [migrationEnv, setMigrationEnv] = useState<MigrationEnvironment>("development");
  const [errors, setErrors] = useState<FormErrors>({});
  const [saving, setSaving] = useState(false);
  const [connections, setConnections] = useState<Connection[]>([]);

  const [showDialog, setShowDialog] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<Connection>>({
    type: "source",
    port: 1433,
    trust_server_certificate: false,
  });
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [showPassword, setShowPassword] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dialogTesting, setDialogTesting] = useState(false);
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());
  const [testOnSave, setTestOnSave] = useState(false);
  const [similarConfirm, setSimilarConfirm] = useState(false);
  const [testingAlerts, setTestingAlerts] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  const { data: alertConfig } = useQuery<AlertConfigResponse>({
    queryKey: ["alert-config"],
    queryFn: getAlertConfig,
    staleTime: 60_000,
  });

  const similarConnections = useMemo(
    () =>
      findSimilarConnections(
        connections,
        form.host ?? "",
        form.database ?? "",
        editingId,
      ),
    [connections, form.host, form.database, editingId],
  );

  useEffect(() => {
    setMounted(true);
    const storedEndpoint = localStorage.getItem("api_endpoint");
    if (storedEndpoint) setApiEndpoint(storedEndpoint);
    setMigrationEnv(loadMigrationEnvironment());
    fetchAndSyncConnections().then(setConnections).catch(() => setConnections(loadConnections()));
  }, []);

  useEffect(() => {
    const refresh = () => {
      fetchAndSyncConnections()
        .then(setConnections)
        .catch(() => setConnections(loadConnections()));
    };
    window.addEventListener(CONNECTIONS_UPDATED_EVENT, refresh);
    return () => window.removeEventListener(CONNECTIONS_UPDATED_EVENT, refresh);
  }, []);

  const handleThemeChange = (t: Theme) => {
    setNextTheme(t);
  };

  const validateEndpoint = (url: string): string | null => {
    try {
      new URL(url);
      return null;
    } catch {
      return "Invalid URL format";
    }
  };

  const handleSaveApi = async () => {
    const newErrors: FormErrors = {};
    const urlErr = validateEndpoint(apiEndpoint);
    if (urlErr) newErrors.apiEndpoint = urlErr;

    setErrors(newErrors);
    if (Object.keys(newErrors).length > 0) return;

    setSaving(true);
    localStorage.setItem("api_endpoint", apiEndpoint);
    saveMigrationEnvironment(migrationEnv);
    refreshApiBase();
    setSaving(false);
    toast.success("Settings saved successfully");
  };

  const handleTestConnection = async () => {
    toast.loading("Testing connection...");
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      const res = await fetch(`${apiEndpoint}/health`, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        toast.dismiss();
        toast.success("API connection successful");
      } else {
        toast.dismiss();
        toast.error("API connection failed");
      }
    } catch {
      toast.dismiss();
      toast.error("Could not reach API endpoint");
    }
  };

  const handleTestAlerts = async () => {
    setTestingAlerts(true);
    try {
      const res = await testAlertChannels("all");
      const lines = Object.entries(res.results).map(([k, v]) => `${k}: ${v}`);
      toast.success("Alert test complete", { description: lines.join(" · ") });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Alert test failed (admin role required)");
    } finally {
      setTestingAlerts(false);
    }
  };

  const openAddDialog = () => {
    setEditingId(null);
    setForm({ type: "source", port: 1433, trust_server_certificate: false });
    setFormErrors({});
    setShowPassword(false);
    setShowDialog(true);
  };

  const openEditDialog = (conn: Connection) => {
    setEditingId(conn.id);
    setForm({ ...conn });
    setFormErrors({});
    setShowPassword(false);
    setShowDialog(true);
  };

  useEffect(() => {
    if (!showDialog) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDialog();
      if (e.key === "Tab") {
        const dialog = dialogRef.current;
        if (!dialog) return;
        const focusable = dialog.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };
    const timer = setTimeout(() => {
      const first = dialogRef.current?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      first?.focus();
    }, 50);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [showDialog]);

  const closeDialog = () => {
    setShowDialog(false);
    setEditingId(null);
    setForm({});
    setFormErrors({});
    setSimilarConfirm(false);
  };

  const validateConnectionForm = (data: Partial<Connection>): FormErrors => {
    const errs: FormErrors = {};

    if (!data.name?.trim()) {
      errs.name = "Connection name is required";
    } else if (data.name.trim().length < 2) {
      errs.name = "Name must be at least 2 characters";
    } else if (data.name.trim().length > 100) {
      errs.name = "Name must be under 100 characters";
    } else {
      const dup = findDuplicateName(connections, data.name, editingId);
      if (dup) {
        errs.name = `A connection named "${dup.name}" already exists`;
      }
    }

    if (!data.type) {
      errs.type = "Connection type is required";
    } else if (!["source", "target"].includes(data.type)) {
      errs.type = "Invalid connection type";
    }

    if (!data.host?.trim()) {
      errs.host = "Host is required";
    } else {
      const hostRegex = /^([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$|^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$|^localhost$|^[a-zA-Z][a-zA-Z0-9-]{0,15}$/;
      if (!hostRegex.test(data.host.trim())) {
        errs.host = "Enter a valid hostname or IP address";
      }
    }

    if (data.port === undefined || data.port === null || data.port === 0) {
      errs.port = "Port is required";
    } else if (data.port < 1 || data.port > 65535) {
      errs.port = "Port must be between 1 and 65535";
    }

    if (!data.database?.trim()) {
      errs.database = "Database name is required";
    }

    if (!data.username?.trim()) {
      errs.username = "Username is required";
    }

    if (!editingId) {
      if (!data.password) {
        errs.password = "Password is required";
      } else if (data.password.length < 4) {
        errs.password = "Password must be at least 4 characters";
      }
    }

    return errs;
  };

  const persistConnection = async (trimmed: Connection) => {
    try {
      if (editingId) {
        await apiUpdateConnection(editingId, {
          name: trimmed.name,
          type: trimmed.type,
          host: trimmed.host,
          port: trimmed.port,
          database: trimmed.database,
          username: trimmed.username,
          password: trimmed.password,
          trust_server_certificate: trimmed.trust_server_certificate,
        });
      } else {
        const resp = await apiCreateConnection({
          name: trimmed.name,
          type: trimmed.type,
          host: trimmed.host,
          port: trimmed.port,
          database: trimmed.database,
          username: trimmed.username,
          password: trimmed.password,
          trust_server_certificate: trimmed.trust_server_certificate,
        });
        trimmed.id = resp.id;
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setFormErrors((prev) => ({
          ...prev,
          name: err.message || "A connection with this name already exists",
        }));
        toast.error(err.message || "A connection with this name already exists");
        return false;
      }
      toast.warning(
        "Connection saved locally only — could not sync to the API. Re-save from Settings after the API is available.",
      );
    }
    return true;
  };

  const handleSaveConnection = async (skipSimilarCheck = false) => {
    const errs = validateConnectionForm(form);
    setFormErrors(errs);
    if (Object.keys(errs).length > 0) return;

    if (!skipSimilarCheck && similarConnections.length > 0) {
      setSimilarConfirm(true);
      return;
    }

    const existing = editingId ? connections.find((c) => c.id === editingId) : null;
    const trimmed: Connection = {
      id: editingId || generateId(),
      name: form.name!.trim(),
      type: form.type as "source" | "target",
      host: form.host!.trim(),
      port: Number(form.port),
      database: form.database!.trim(),
      username: form.username!.trim(),
      password: form.password || (existing ? existing.password : ""),
      trust_server_certificate:
        form.type === "source" ? Boolean(form.trust_server_certificate) : false,
      status: existing?.status || "disconnected",
    };

    clearConnectionTombstone(trimmed);

    const synced = await persistConnection(trimmed);
    if (!synced) return;

    // Test-on-Save: verify connectivity before persisting
    if (testOnSave && trimmed.id) {
      setTestingIds((prev) => new Set(prev).add(trimmed.id));
      try {
        const result = await apiTestConnection(trimmed.id);
        if (result.status !== "connected") {
          toast.error(`Connection test failed: ${result.message ?? "could not connect"}. Fix the details and try again.`);
          setTestingIds((prev) => { const next = new Set(prev); next.delete(trimmed.id); return next; });
          return;
        }
        trimmed.status = "connected";
      } catch {
        toast.error("Could not reach API to test connection.");
        setTestingIds((prev) => { const next = new Set(prev); next.delete(trimmed.id); return next; });
        return;
      } finally {
        setTestingIds((prev) => { const next = new Set(prev); next.delete(trimmed.id); return next; });
      }
    }

    let updated: Connection[];
    if (editingId) {
      updated = connections.map((c) => (c.id === editingId ? trimmed : c));
      toast.success(`Connection "${trimmed.name}" updated`);
    } else {
      const duplicateIdx = connections.findIndex(
        (c) =>
          c.type === trimmed.type &&
          c.host === trimmed.host &&
          c.database === trimmed.database &&
          c.name.trim().toLowerCase() === trimmed.name.trim().toLowerCase(),
      );
      if (duplicateIdx >= 0) {
        updated = connections.map((c, i) =>
          i === duplicateIdx ? { ...trimmed, id: c.id, status: c.status } : c,
        );
        toast.success(`Connection "${trimmed.name}" updated`);
      } else {
        updated = [...connections, trimmed];
        toast.success(`Connection "${trimmed.name}" added`);
      }
    }

    updated = dedupeConnections(updated);

    setConnections(updated);
    saveConnections(updated);
    closeDialog();
  };

  const handleDeleteConnection = (id: string) => {
    setDeleteTargetId(id);
  };

  const deleteTarget = deleteTargetId
    ? connections.find((c) => c.id === deleteTargetId)
    : undefined;

  const confirmDelete = async () => {
    if (!deleteTargetId || !deleteTarget) return;
    setDeleting(true);
    try {
      const updated = await removeConnection(deleteTargetId, deleteTarget);
      setConnections(updated);
      toast.success(`Connection "${deleteTarget.name}" deleted`);
      setDeleteTargetId(null);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Could not delete connection";
      toast.error(msg);
    } finally {
      setDeleting(false);
    }
  };

  const handleToggleConnection = async (id: string) => {
    const conn = connections.find((c) => c.id === id);
    if (!conn) return;
    if (conn.status === "connected") {
      setConnections((prev) => {
        const updated = prev.map((c) =>
          c.id === id ? { ...c, status: "disconnected" as const } : c
        );
        saveConnections(updated);
        return updated;
      });
      toast.success(`Disconnected from "${conn.name}"`);
      return;
    }
    setTestingIds((prev) => new Set(prev).add(id));
    try {
      toast.loading(`Connecting to "${conn.name}"...`);
      const synced = await fetchAndSyncConnections();
      const resolved =
        synced.find((c) => c.id === id) ??
        synced.find(
          (c) =>
            c.name === conn.name &&
            c.host === conn.host &&
            c.database === conn.database &&
            c.type === conn.type,
        );
      if (resolved) setConnections(dedupeConnections(synced));

      const testId = resolved?.id ?? id;
      const testConn = resolved ?? conn;
      let result;
      try {
        result = await apiTestConnection(testId);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404 && testConn.password) {
          result = await apiTestRawConnection({
            name: testConn.name,
            type: testConn.type,
            host: testConn.host,
            port: testConn.port,
            database: testConn.database,
            username: testConn.username,
            password: testConn.password,
            trust_server_certificate: testConn.trust_server_certificate,
          });
        } else {
          throw err;
        }
      }
      toast.dismiss();
      const newStatus = result.status === "connected" ? "connected" : "error";
      setConnections((prev) => {
        const withoutStale =
          testId !== id ? prev.filter((c) => c.id !== id) : prev;
        const updated = withoutStale.map((c) =>
          c.id === testId ? { ...c, status: newStatus as "connected" | "disconnected" | "error" } : c,
        );
        const deduped = dedupeConnections(updated);
        saveConnections(deduped);
        return deduped;
      });
      if (newStatus === "connected") {
        toast.success(`Connected to "${conn.name}"`);
      } else {
        toast.error(`Connection failed: ${result.message}`);
      }
    } catch {
      toast.dismiss();
      toast.error("Could not reach API endpoint");
    } finally {
      setTestingIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
    }
  };

  const handleDialogTestConnection = async () => {
    if (!form.host || !form.database || !form.username) {
      toast.error("Fill in host, database, and username first");
      return;
    }
    setDialogTesting(true);
    try {
      const result = await apiTestRawConnection({
        name: form.name || "test",
        type: (form.type as "source" | "target") || "source",
        host: form.host,
        port: Number(form.port) || 1433,
        database: form.database,
        username: form.username,
        password: form.password || "",
        trust_server_certificate: form.type === "source" ? Boolean(form.trust_server_certificate) : false,
      });
      toast.dismiss();
      if (result.status === "connected") {
        toast.success("Connection successful");
      } else {
        toast.error(`Connection failed: ${result.message}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Test failed";
      toast.error(msg);
    } finally {
      setDialogTesting(false);
    }
  };

  const updateFormField = <K extends keyof Connection>(field: K, value: Connection[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    if (field === "name") {
      const name = String(value).trim();
      if (!name) {
        setFormErrors((prev) => ({ ...prev, name: "Connection name is required" }));
      } else if (name.length < 2) {
        setFormErrors((prev) => ({ ...prev, name: "Name must be at least 2 characters" }));
      } else {
        const dup = findDuplicateName(connections, name, editingId);
        if (dup) {
          setFormErrors((prev) => ({
            ...prev,
            name: `A connection named "${dup.name}" already exists`,
          }));
        } else {
          setFormErrors((prev) => { const next = { ...prev }; delete next.name; return next; });
        }
      }
    } else if (field === "host") {
      const host = String(value).trim();
      if (host && !/^[a-zA-Z0-9.\-_]+$/.test(host)) {
        setFormErrors((prev) => ({ ...prev, host: "Invalid hostname or IP address" }));
      } else {
        setFormErrors((prev) => { const next = { ...prev }; delete next.host; return next; });
      }
    } else if (field === "port") {
      const port = Number(value);
      if (value !== "" && (isNaN(port) || port < 1 || port > 65535)) {
        setFormErrors((prev) => ({ ...prev, port: "Port must be between 1 and 65535" }));
      } else {
        setFormErrors((prev) => { const next = { ...prev }; delete next.port; return next; });
      }
    } else if (formErrors[field as string]) {
      setFormErrors((prev) => { const next = { ...prev }; delete next[field as string]; return next; });
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configure your migration platform preferences
        </p>
      </div>

      <Tabs defaultValue="general" className="space-y-4">
        <TabsList aria-label="Settings tabs">
          <TabsTrigger value="general" className="flex items-center gap-2">
            <Cpu className="h-4 w-4" aria-hidden="true" />
            General
          </TabsTrigger>
          <TabsTrigger value="connections" className="flex items-center gap-2">
            <Database className="h-4 w-4" aria-hidden="true" />
            Connections
          </TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="space-y-4" role="tabpanel">
          <Card>
            <CardHeader>
              <CardTitle>Appearance</CardTitle>
              <CardDescription>
                Choose your preferred theme for the dashboard
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex gap-3" role="radiogroup" aria-label="Theme selection">
                {([["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]] as const).map(([value, Icon, label]) => (
                  <button
                    key={value}
                    onClick={() => handleThemeChange(value)}
                    role="radio"
                    aria-checked={mounted ? theme === value : false}
                    aria-label={`${label} theme`}
                    className={`flex flex-col items-center gap-2 rounded-lg border-2 p-4 transition-all ${
                      mounted && theme === value
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-muted-foreground/30"
                    }`}
                  >
                    <Icon className="h-6 w-6" aria-hidden="true" />
                    <span className="text-xs font-medium">{label}</span>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>API Configuration</CardTitle>
              <CardDescription>
                Set the backend API endpoint for the migration platform
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="api-endpoint">API Endpoint URL</Label>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <Input
                      id="api-endpoint"
                      value={apiEndpoint}
                      onChange={(e) => {
                        setApiEndpoint(e.target.value);
                        if (errors.apiEndpoint) {
                          setErrors((prev) => {
                            const next = { ...prev };
                            delete next.apiEndpoint;
                            return next;
                          });
                        }
                      }}
                      className="font-mono text-sm"
                      aria-invalid={!!errors.apiEndpoint}
                      aria-describedby={errors.apiEndpoint ? "api-endpoint-error" : undefined}
                    />
                    {errors.apiEndpoint && (
                      <p id="api-endpoint-error" className="text-xs text-destructive mt-1 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" aria-hidden="true" />
                        {errors.apiEndpoint}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="outline"
                    onClick={handleTestConnection}
                    aria-label="Test API connection"
                  >
                    Test Connection
                  </Button>
                  <Button onClick={handleSaveApi} disabled={saving}>
                    <Save className="h-4 w-4 mr-2" aria-hidden="true" />
                    {saving ? "Saving..." : "Save"}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  The base URL for the migration platform REST API
                </p>
              </div>

              <div className="space-y-2 pt-2 border-t">
                <Label htmlFor="migration-env">Migration environment</Label>
                <select
                  id="migration-env"
                  value={migrationEnv}
                  onChange={(e) => setMigrationEnv(e.target.value as MigrationEnvironment)}
                  className="flex h-9 w-full max-w-md rounded-md border border-input bg-background px-3 py-1 text-sm"
                >
                  <option value="development">Development — skip target snapshot (require_target_snapshot=false)</option>
                  <option value="production">Production — require pg_dump snapshot before migrate</option>
                </select>
                <p className="text-xs text-muted-foreground">
                  Controls whether migrations require a verified PostgreSQL backup before starting.
                  Use <strong>Development</strong> for local/docker work; use <strong>Production</strong> for live cutover targets.
                  Saved with API settings — applies to this browser only.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                Alerting &amp; Notifications
              </CardTitle>
              <CardDescription>
                External alerts for migration failures — configured via server environment variables
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-3 text-sm">
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <Webhook className="h-4 w-4 text-muted-foreground" />
                  <span>Webhook</span>
                  <Badge variant={alertConfig?.webhook_configured ? "default" : "secondary"}>
                    {alertConfig?.webhook_configured ? "Configured" : "Not set"}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <span>Email</span>
                  <Badge variant={alertConfig?.email_configured ? "default" : "secondary"}>
                    {alertConfig?.email_configured
                      ? `→ ${alertConfig.email_to}`
                      : "Not set"}
                  </Badge>
                </div>
              </div>

              <div className="rounded-md border bg-muted/30 p-4 space-y-2 text-xs font-mono text-muted-foreground">
                <p className="font-sans text-sm font-medium text-foreground">Webhook (Slack / Teams / PagerDuty)</p>
                <p>MIGRATION_WEBHOOK_URL=https://hooks.slack.com/services/…</p>
                <p className="font-sans text-sm font-medium text-foreground pt-2">Email (SMTP)</p>
                <p>MIGRATION_SMTP_HOST=smtp.example.com</p>
                <p>MIGRATION_SMTP_PORT=587</p>
                <p>MIGRATION_SMTP_USER=alerts@example.com</p>
                <p>MIGRATION_SMTP_PASSWORD=…</p>
                <p>MIGRATION_ALERT_EMAIL_TO=dba-team@example.com</p>
                <p>MIGRATION_ALERT_EMAIL_FROM=alerts@example.com</p>
              </div>

              <p className="text-xs text-muted-foreground">
                The in-app alert banner polls <code className="text-[10px]">GET /api/v1/alerts</code> every 30s on all pages.
                Webhook/email fire automatically on migration start, complete, and fail.
              </p>

              <Button
                variant="outline"
                size="sm"
                onClick={handleTestAlerts}
                disabled={testingAlerts || !alertConfig?.channels_active}
              >
                {testingAlerts ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Bell className="h-4 w-4 mr-2" />
                )}
                Send test alert
              </Button>
              {!alertConfig?.channels_active && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  Configure at least one channel in <code className="text-[10px]">.env</code> and restart the API to enable test sends.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="connections" className="space-y-4" role="tabpanel">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-medium">Database Connections</h3>
              <p className="text-sm text-muted-foreground">
                Manage source (SQL Server) and target (PostgreSQL) connections
              </p>
            </div>
            <Button onClick={openAddDialog} aria-label="Add new database connection">
              <Plus className="h-4 w-4 mr-2" aria-hidden="true" />
              Add Connection
            </Button>
          </div>

          {connections.length === 0 && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <Database className="h-12 w-12 text-muted-foreground/50 mb-4" aria-hidden="true" />
                <p className="text-muted-foreground font-medium">No connections configured</p>
                <p className="text-sm text-muted-foreground/70 mt-1">
                  Add a connection to get started with migrations
                </p>
              </CardContent>
            </Card>
          )}

          {connections.map((conn) => (
            <Card key={conn.id}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                        conn.type === "source"
                          ? "bg-blue-500/10 text-blue-500"
                          : "bg-emerald-500/10 text-emerald-500"
                      }`}
                      aria-hidden="true"
                    >
                      <Database className="h-5 w-5" />
                    </div>
                    <div>
                      <CardTitle className="text-base">{conn.name}</CardTitle>
                      <CardDescription>
                        {conn.type === "source" ? "Source" : "Target"} &mdash;{" "}
                        {conn.host}:{conn.port}/{conn.database}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={
                        testingIds.has(conn.id) ? "secondary"
                          : conn.status === "connected" ? "secondary"
                          : conn.status === "disconnected" ? "outline"
                          : "destructive"
                      }
                      className={
                        testingIds.has(conn.id) ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                          : conn.status === "connected" ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                          : ""
                      }
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full mr-1 ${
                          testingIds.has(conn.id) ? "bg-amber-500 animate-pulse"
                            : conn.status === "connected" ? "bg-emerald-500"
                            : conn.status === "disconnected" ? "bg-muted-foreground"
                            : "bg-red-500"
                        }`}
                        aria-hidden="true"
                      />
                      {testingIds.has(conn.id) ? "Testing…"
                        : conn.status.charAt(0).toUpperCase() + conn.status.slice(1)}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleDeleteConnection(conn.id)}
                      aria-label={`Delete ${conn.name}`}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground text-xs">Host</span>
                    <p className="font-mono">{conn.host}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Port</span>
                    <p className="font-mono">{conn.port}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Database</span>
                    <p className="font-mono">{conn.database}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Username</span>
                    <p className="font-mono">{conn.username}</p>
                  </div>
                </div>
                <div className="flex gap-2 mt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleToggleConnection(conn.id)}
                    aria-label={conn.status === "connected" ? `Disconnect ${conn.name}` : `Connect to ${conn.name}`}
                  >
                    <Plug className="h-4 w-4 mr-2" aria-hidden="true" />
                    {conn.status === "connected" ? "Disconnect" : "Connect"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openEditDialog(conn)}
                    aria-label={`Edit ${conn.name}`}
                  >
                    Edit
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>

      {showDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={closeDialog}
        >
          <div
            ref={dialogRef}
            className="bg-background rounded-lg border shadow-lg w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={editingId ? "Edit connection" : "Add connection"}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="text-lg font-semibold">
                {editingId ? "Edit Connection" : "Add Connection"}
              </h2>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={closeDialog}
                aria-label="Close dialog"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="px-6 py-4 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="conn-name">Connection Name</Label>
                <Input
                  id="conn-name"
                  value={form.name || ""}
                  onChange={(e) => updateFormField("name", e.target.value)}
                  placeholder="e.g. SQL Server Production"
                  aria-invalid={!!formErrors.name}
                  aria-describedby={formErrors.name ? "conn-name-error" : undefined}
                />
                {formErrors.name && (
                  <p id="conn-name-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.name}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-type">Connection Type</Label>
                <select
                  id="conn-type"
                  value={form.type || "source"}
                  onChange={(e) => updateFormField("type", e.target.value as "source" | "target")}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  aria-invalid={!!formErrors.type}
                  aria-describedby={formErrors.type ? "conn-type-error" : undefined}
                >
                  <option value="source">Source (SQL Server)</option>
                  <option value="target">Target (PostgreSQL)</option>
                </select>
                {formErrors.type && (
                  <p id="conn-type-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.type}
                  </p>
                )}
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2 space-y-2">
                  <Label htmlFor="conn-host">Host</Label>
                  <Input
                    id="conn-host"
                    value={form.host || ""}
                    onChange={(e) => updateFormField("host", e.target.value)}
                    placeholder="hostname or IP"
                    aria-invalid={!!formErrors.host}
                    aria-describedby={formErrors.host ? "conn-host-error" : undefined}
                  />
                  {formErrors.host && (
                    <p id="conn-host-error" className="text-xs text-destructive flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      {formErrors.host}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="conn-port">Port</Label>
                  <Input
                    id="conn-port"
                    type="number"
                    value={form.port || ""}
                    onChange={(e) => updateFormField("port", Number(e.target.value))}
                    placeholder="1433"
                    min={1}
                    max={65535}
                    aria-invalid={!!formErrors.port}
                    aria-describedby={formErrors.port ? "conn-port-error" : undefined}
                  />
                  {formErrors.port && (
                    <p id="conn-port-error" className="text-xs text-destructive flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      {formErrors.port}
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-db">Database Name</Label>
                <Input
                  id="conn-db"
                  value={form.database || ""}
                  onChange={(e) => updateFormField("database", e.target.value)}
                  placeholder="e.g. ProductionDB"
                  aria-invalid={!!formErrors.database}
                  aria-describedby={formErrors.database ? "conn-db-error" : undefined}
                />
                {formErrors.database && (
                  <p id="conn-db-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.database}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-user">Username</Label>
                <Input
                  id="conn-user"
                  value={form.username || ""}
                  onChange={(e) => updateFormField("username", e.target.value)}
                  placeholder="database user"
                  aria-invalid={!!formErrors.username}
                  aria-describedby={formErrors.username ? "conn-user-error" : undefined}
                />
                {formErrors.username && (
                  <p id="conn-user-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.username}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-password">Password</Label>
                <div className="relative">
                  <Input
                    id="conn-password"
                    type={showPassword ? "text" : "password"}
                    value={form.password || ""}
                    onChange={(e) => updateFormField("password", e.target.value)}
                    placeholder={editingId ? "Leave blank to keep current" : "Enter password"}
                    className="pr-10"
                    autoComplete="new-password"
                    aria-invalid={!!formErrors.password}
                    aria-describedby={formErrors.password ? "conn-password-error" : undefined}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {formErrors.password && (
                  <p id="conn-password-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.password}
                  </p>
                )}
              </div>

              {form.type === "source" && (
                <label
                  htmlFor="conn-trust-cert"
                  className="flex items-start gap-3 rounded-md border border-border bg-muted/20 px-3 py-3 cursor-pointer select-none"
                >
                  <input
                    id="conn-trust-cert"
                    type="checkbox"
                    checked={Boolean(form.trust_server_certificate)}
                    onChange={(e) => updateFormField("trust_server_certificate", e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded"
                  />
                  <span className="space-y-1">
                    <span className="block text-sm font-medium">Trust Server Certificate</span>
                    <span className="block text-xs text-muted-foreground">
                      Enable for SQL Server instances with self-signed TLS certificates (common in dev/test).
                      Leave unchecked in production.
                    </span>
                  </span>
                </label>
              )}

              {similarConnections.length > 0 && (
                <div
                  role="alert"
                  className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-3 text-sm text-amber-900 dark:text-amber-100"
                >
                  <div className="flex items-start gap-2">
                    <TriangleAlert className="h-4 w-4 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                    <div className="space-y-1">
                      <p className="font-medium">
                        {similarConnections.length === 1
                          ? "A similar connection already exists"
                          : "Similar connections already exist"}
                      </p>
                      <p className="text-xs text-amber-800/90 dark:text-amber-200/90">
                        The same host and database are already configured:
                      </p>
                      <ul className="text-xs list-disc pl-4 space-y-0.5">
                        {similarConnections.map((c) => (
                          <li key={c.id}>
                            <span className="font-medium">{c.name}</span>
                            {" "}
                            ({c.host} / {c.database})
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between px-6 py-4 border-t">
              <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={testOnSave}
                  onChange={(e) => setTestOnSave(e.target.checked)}
                  className="h-3.5 w-3.5 rounded"
                />
                Test before saving
              </label>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={handleDialogTestConnection}
                  disabled={dialogTesting}
                >
                  {dialogTesting ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
                  ) : (
                    <Plug className="h-4 w-4 mr-2" aria-hidden="true" />
                  )}
                  {dialogTesting ? "Testing..." : "Test Connection"}
                </Button>
                <Button variant="outline" onClick={closeDialog}>
                  Cancel
                </Button>
                <Button onClick={() => handleSaveConnection(false)}>
                  {editingId ? "Update Connection" : "Add Connection"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {similarConfirm && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50"
          onClick={() => setSimilarConfirm(false)}
        >
          <div
            className="bg-background rounded-lg border shadow-lg w-full max-w-md mx-4 p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-modal="true"
            aria-label="Confirm similar connection"
          >
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600">
                <TriangleAlert className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="space-y-2">
                <h3 className="text-lg font-semibold">Similar connection exists</h3>
                <p className="text-sm text-muted-foreground">
                  A connection with the same host and database is already saved. Add another anyway?
                </p>
                <ul className="text-sm list-disc pl-4 space-y-1">
                  {similarConnections.map((c) => (
                    <li key={c.id}>
                      <span className="font-medium">{c.name}</span>
                      {" "}
                      ({c.host} / {c.database})
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setSimilarConfirm(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setSimilarConfirm(false);
                  void handleSaveConnection(true);
                }}
              >
                {editingId ? "Update anyway" : "Add anyway"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {deleteTargetId && deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => !deleting && setDeleteTargetId(null)}
        >
          <div
            className="bg-background rounded-lg border shadow-lg w-full max-w-sm mx-4 p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-modal="true"
            aria-label="Confirm deletion"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
                <TriangleAlert className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Delete Connection</h2>
                <p className="text-sm text-muted-foreground">
                  Are you sure you want to delete <strong>{deleteTarget.name}</strong>? This action cannot be undone.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteTargetId(null)} disabled={deleting}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
                {deleting ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
                ) : (
                  <Trash2 className="h-4 w-4 mr-2" aria-hidden="true" />
                )}
                {deleting ? "Deleting..." : "Delete"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
