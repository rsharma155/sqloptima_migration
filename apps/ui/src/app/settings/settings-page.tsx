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
  Timer,
  RefreshCw,
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
  saveAlertConfig,
  testAlertChannels,
  getMigrationSettings,
  saveMigrationSettings,
  getReplicationSettings,
  saveReplicationSettings,
  type AlertConfigResponse,
  type AlertConfigUpdateRequest,
  type MigrationSettingsResponse,
  type MigrationSettingsUpdateRequest,
  type ReplicationSettingsResponse,
  type ReplicationSettingsUpdateRequest,
} from "@/lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { ConnectionPrivilegeScriptsPanel } from "@/components/connections/connection-privilege-scripts-panel";
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
  const [activeTab, setActiveTab] = useState("general");
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
  const [testOnSave, setTestOnSave] = useState(() => {
    if (typeof window === "undefined") return true;
    const stored = localStorage.getItem("connection_test_on_save");
    return stored !== "false";
  });
  const [similarConfirm, setSimilarConfirm] = useState(false);
  const [testingAlerts, setTestingAlerts] = useState(false);
  const [savingAlerts, setSavingAlerts] = useState(false);
  const [savingMigration, setSavingMigration] = useState(false);
  const [savingReplication, setSavingReplication] = useState(false);
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);
  const [alertForm, setAlertForm] = useState<AlertConfigUpdateRequest>({
    webhook_enabled: false,
    webhook_url: "",
    email_enabled: false,
    smtp_host: "",
    smtp_port: 587,
    smtp_user: "",
    smtp_password: "",
    alert_email_to: "",
    alert_email_from: "",
  });
  const [migrationForm, setMigrationForm] = useState<MigrationSettingsUpdateRequest>({
    source_throttle_enabled: true,
    small_table_delay_sec: 1,
    large_table_delay_sec: 4,
    large_table_row_threshold: 100_000,
    large_table_size_mb_threshold: 50,
    max_tables_per_job: 25,
  });
  const [replicationForm, setReplicationForm] = useState<ReplicationSettingsUpdateRequest>({
    poll_interval_ms: 1000,
    batch_size: 1000,
  });
  const dialogRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: alertConfig } = useQuery<AlertConfigResponse>({
    queryKey: ["alert-config"],
    queryFn: getAlertConfig,
    staleTime: 60_000,
  });

  const { data: migrationConfig } = useQuery<MigrationSettingsResponse>({
    queryKey: ["migration-settings"],
    queryFn: getMigrationSettings,
    staleTime: 60_000,
  });

  const { data: replicationConfig } = useQuery<ReplicationSettingsResponse>({
    queryKey: ["replication-settings"],
    queryFn: getReplicationSettings,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!migrationConfig) return;
    setMigrationForm({
      source_throttle_enabled: migrationConfig.source_throttle_enabled,
      small_table_delay_sec: migrationConfig.small_table_delay_sec,
      large_table_delay_sec: migrationConfig.large_table_delay_sec,
      large_table_row_threshold: migrationConfig.large_table_row_threshold,
      large_table_size_mb_threshold: migrationConfig.large_table_size_mb_threshold,
      max_tables_per_job: migrationConfig.max_tables_per_job,
    });
  }, [migrationConfig]);

  useEffect(() => {
    if (!replicationConfig) return;
    setReplicationForm({
      poll_interval_ms: replicationConfig.poll_interval_ms,
      batch_size: replicationConfig.batch_size,
    });
  }, [replicationConfig]);

  useEffect(() => {
    if (!alertConfig) return;
    setAlertForm({
      webhook_enabled: alertConfig.webhook_enabled,
      webhook_url: "",
      email_enabled: alertConfig.email_enabled,
      smtp_host: alertConfig.smtp_host,
      smtp_port: alertConfig.smtp_port,
      smtp_user: alertConfig.smtp_user,
      smtp_password: "",
      alert_email_to: alertConfig.alert_email_to || alertConfig.email_to || "",
      alert_email_from: alertConfig.alert_email_from,
    });
  }, [alertConfig]);

  const similarConnections = useMemo(
    () =>
      findSimilarConnections(
        connections,
        (form.type as "source" | "target") ?? "source",
        form.host ?? "",
        form.database ?? "",
        form.port,
        editingId,
      ),
    [connections, form.type, form.host, form.database, form.port, editingId],
  );

  useEffect(() => {
    setMounted(true);
    const storedEndpoint = localStorage.getItem("api_endpoint");
    if (storedEndpoint) setApiEndpoint(storedEndpoint);
    setMigrationEnv(loadMigrationEnvironment());
    fetchAndSyncConnections().then(setConnections).catch(() => setConnections(loadConnections()));

    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get("tab");
      if (tab && ["general", "connections", "notifications", "migration", "replication"].includes(tab)) {
        setActiveTab(tab);
      }
    }
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

  const handleSaveAlerts = async () => {
    if (alertForm.webhook_enabled && !alertForm.webhook_url && !alertConfig?.webhook_configured) {
      toast.error("Enter a webhook URL or disable webhook alerts");
      return;
    }
    if (alertForm.email_enabled) {
      if (!alertForm.smtp_host.trim()) {
        toast.error("SMTP host is required for email alerts");
        return;
      }
      if (!alertForm.alert_email_to.trim()) {
        toast.error("Alert recipient email is required");
        return;
      }
    }
    setSavingAlerts(true);
    try {
      const saved = await saveAlertConfig(alertForm);
      await queryClient.invalidateQueries({ queryKey: ["alert-config"] });
      setAlertForm((prev) => ({ ...prev, webhook_url: "", smtp_password: "" }));
      toast.success("Notification settings saved");
      if (saved.source === "environment") {
        toast.message("Environment variables still provide fallback channels");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save notification settings");
    } finally {
      setSavingAlerts(false);
    }
  };

  const updateAlertField = <K extends keyof AlertConfigUpdateRequest>(
    field: K,
    value: AlertConfigUpdateRequest[K],
  ) => {
    setAlertForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateMigrationField = <K extends keyof MigrationSettingsUpdateRequest>(
    field: K,
    value: MigrationSettingsUpdateRequest[K],
  ) => {
    setMigrationForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateReplicationField = <K extends keyof ReplicationSettingsUpdateRequest>(
    field: K,
    value: ReplicationSettingsUpdateRequest[K],
  ) => {
    setReplicationForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveReplicationSettings = async () => {
    setSavingReplication(true);
    try {
      const saved = await saveReplicationSettings(replicationForm);
      await queryClient.invalidateQueries({ queryKey: ["replication-settings"] });
      const streamsNote =
        saved.active_streams_updated && saved.active_streams_updated > 0
          ? ` Applied to ${saved.active_streams_updated} active stream(s).`
          : "";
      toast.success(`Replication settings saved.${streamsNote}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save replication settings");
    } finally {
      setSavingReplication(false);
    }
  };

  const handleSaveMigrationSettings = async () => {
    if (
      migrationForm.small_table_delay_sec > migrationForm.large_table_delay_sec
    ) {
      toast.error("Small-table delay must not exceed large-table delay");
      return;
    }
    setSavingMigration(true);
    try {
      await saveMigrationSettings(migrationForm);
      await queryClient.invalidateQueries({ queryKey: ["migration-settings"] });
      toast.success("Migration settings saved");
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Failed to save migration settings (admin role required)",
      );
    } finally {
      setSavingMigration(false);
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
          c.port === trimmed.port &&
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

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList aria-label="Settings tabs">
          <TabsTrigger value="general" className="flex items-center gap-2">
            <Cpu className="h-4 w-4" aria-hidden="true" />
            General
          </TabsTrigger>
          <TabsTrigger value="connections" className="flex items-center gap-2">
            <Database className="h-4 w-4" aria-hidden="true" />
            Connections
          </TabsTrigger>
          <TabsTrigger value="notifications" className="flex items-center gap-2">
            <Bell className="h-4 w-4" aria-hidden="true" />
            Notifications
          </TabsTrigger>
          <TabsTrigger value="migration" className="flex items-center gap-2">
            <Timer className="h-4 w-4" aria-hidden="true" />
            Migration
          </TabsTrigger>
          <TabsTrigger value="replication" className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Replication
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
                In-app alerts
              </CardTitle>
              <CardDescription>
                Failed migrations and setup issues appear in the dashboard alert banner (polled every 30s).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Configure external webhook and email channels in the{" "}
                <span className="font-medium text-foreground">Notifications</span> tab to receive
                Slack, Teams, or SMTP alerts when migrations start, complete, or fail.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications" className="space-y-4" role="tabpanel">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                Alerting &amp; Notifications
              </CardTitle>
              <CardDescription>
                Send external alerts on migration start, complete, and failure. Settings are stored
                securely in the platform database (admin only).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex flex-wrap gap-3 text-sm">
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <Webhook className="h-4 w-4 text-muted-foreground" />
                  <span>Webhook</span>
                  <Badge variant={alertConfig?.webhook_configured ? "default" : "secondary"}>
                    {alertConfig?.webhook_configured ? "Active" : "Inactive"}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <span>Email</span>
                  <Badge variant={alertConfig?.email_configured ? "default" : "secondary"}>
                    {alertConfig?.email_configured
                      ? `→ ${alertConfig.email_to}`
                      : "Inactive"}
                  </Badge>
                </div>
                {alertConfig?.source === "environment" && (
                  <Badge variant="outline">Env fallback active</Badge>
                )}
              </div>

              <div className="space-y-4 rounded-md border p-4">
                <label className="flex items-start gap-3 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={alertForm.webhook_enabled}
                    onChange={(e) => updateAlertField("webhook_enabled", e.target.checked)}
                    className="mt-1 h-4 w-4 rounded"
                  />
                  <span>
                    <span className="block text-sm font-medium">Webhook alerts</span>
                    <span className="block text-xs text-muted-foreground">
                      Slack, Microsoft Teams, PagerDuty, or any JSON webhook endpoint
                    </span>
                  </span>
                </label>
                {alertForm.webhook_enabled && (
                  <div className="space-y-2 pl-7">
                    <Label htmlFor="webhook-url">Webhook URL</Label>
                    <Input
                      id="webhook-url"
                      type="url"
                      value={alertForm.webhook_url}
                      onChange={(e) => updateAlertField("webhook_url", e.target.value)}
                      placeholder={
                        alertConfig?.webhook_configured
                          ? `Configured: ${alertConfig.webhook_url || "••••••"} — enter new URL to change`
                          : "https://hooks.slack.com/services/…"
                      }
                      className="font-mono text-sm"
                    />
                  </div>
                )}
              </div>

              <div className="space-y-4 rounded-md border p-4">
                <label className="flex items-start gap-3 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={alertForm.email_enabled}
                    onChange={(e) => updateAlertField("email_enabled", e.target.checked)}
                    className="mt-1 h-4 w-4 rounded"
                  />
                  <span>
                    <span className="block text-sm font-medium">Email alerts (SMTP)</span>
                    <span className="block text-xs text-muted-foreground">
                      TLS on port 587 (STARTTLS) — typical for Office 365, Gmail relay, SendGrid
                    </span>
                  </span>
                </label>
                {alertForm.email_enabled && (
                  <div className="grid gap-4 pl-7 sm:grid-cols-2">
                    <div className="space-y-2 sm:col-span-2">
                      <Label htmlFor="smtp-host">SMTP host</Label>
                      <Input
                        id="smtp-host"
                        value={alertForm.smtp_host}
                        onChange={(e) => updateAlertField("smtp_host", e.target.value)}
                        placeholder="smtp.example.com"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="smtp-port">SMTP port</Label>
                      <Input
                        id="smtp-port"
                        type="number"
                        min={1}
                        max={65535}
                        value={alertForm.smtp_port}
                        onChange={(e) => updateAlertField("smtp_port", Number(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="smtp-user">SMTP username</Label>
                      <Input
                        id="smtp-user"
                        value={alertForm.smtp_user}
                        onChange={(e) => updateAlertField("smtp_user", e.target.value)}
                        placeholder="alerts@example.com"
                      />
                    </div>
                    <div className="space-y-2 sm:col-span-2">
                      <Label htmlFor="smtp-password">SMTP password</Label>
                      <div className="relative">
                        <Input
                          id="smtp-password"
                          type={showSmtpPassword ? "text" : "password"}
                          value={alertForm.smtp_password}
                          onChange={(e) => updateAlertField("smtp_password", e.target.value)}
                          placeholder={
                            alertConfig?.smtp_password_set
                              ? "Leave blank to keep current password"
                              : "App password or SMTP credential"
                          }
                          className="pr-10"
                          autoComplete="new-password"
                        />
                        <button
                          type="button"
                          onClick={() => setShowSmtpPassword(!showSmtpPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          aria-label={showSmtpPassword ? "Hide password" : "Show password"}
                        >
                          {showSmtpPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="alert-email-to">Send alerts to</Label>
                      <Input
                        id="alert-email-to"
                        type="email"
                        value={alertForm.alert_email_to}
                        onChange={(e) => updateAlertField("alert_email_to", e.target.value)}
                        placeholder="dba-team@example.com"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="alert-email-from">From address</Label>
                      <Input
                        id="alert-email-from"
                        type="email"
                        value={alertForm.alert_email_from}
                        onChange={(e) => updateAlertField("alert_email_from", e.target.value)}
                        placeholder="alerts@example.com (optional)"
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                <Button onClick={handleSaveAlerts} disabled={savingAlerts}>
                  {savingAlerts ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4 mr-2" />
                  )}
                  {savingAlerts ? "Saving…" : "Save notification settings"}
                </Button>
                <Button
                  variant="outline"
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
              </div>

              <p className="text-xs text-muted-foreground">
                Requires admin role to save or test. Legacy <code className="text-[10px]">MIGRATION_*</code>{" "}
                environment variables still work as a fallback when app settings are empty.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="migration" className="space-y-4" role="tabpanel">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Timer className="h-5 w-5" />
                Migration job limits
              </CardTitle>
              <CardDescription>
                Control how many tables can be included in one migration job. The Go migration
                engine processes one job at a time and migrates tables sequentially within each job.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2 max-w-xs">
                <Label htmlFor="max-tables-per-job">Maximum tables per job</Label>
                <Input
                  id="max-tables-per-job"
                  type="number"
                  min={1}
                  max={500}
                  value={migrationForm.max_tables_per_job}
                  onChange={(e) =>
                    updateMigrationField("max_tables_per_job", Number(e.target.value))
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Prevents oversized jobs that slow the UI and monopolize the migration worker.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Source read throttle</CardTitle>
              <CardDescription>
                Pause between chunk reads from SQL Server to reduce load on busy source databases.
                A table is treated as &quot;large&quot; when its estimated row count or on-disk size
                exceeds either threshold below.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <label className="flex items-start gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={migrationForm.source_throttle_enabled}
                  onChange={(e) =>
                    updateMigrationField("source_throttle_enabled", e.target.checked)
                  }
                  className="mt-1 h-4 w-4 rounded"
                />
                <span>
                  <span className="block text-sm font-medium">Enable source throttle</span>
                  <span className="block text-xs text-muted-foreground">
                    When disabled, chunks are read back-to-back with no delay
                  </span>
                </span>
              </label>

              {migrationForm.source_throttle_enabled && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="small-table-delay">Small table delay (seconds)</Label>
                    <Input
                      id="small-table-delay"
                      type="number"
                      min={0}
                      max={300}
                      step={0.5}
                      value={migrationForm.small_table_delay_sec}
                      onChange={(e) =>
                        updateMigrationField("small_table_delay_sec", Number(e.target.value))
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="large-table-delay">Large table delay (seconds)</Label>
                    <Input
                      id="large-table-delay"
                      type="number"
                      min={0}
                      max={600}
                      step={0.5}
                      value={migrationForm.large_table_delay_sec}
                      onChange={(e) =>
                        updateMigrationField("large_table_delay_sec", Number(e.target.value))
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="large-row-threshold">Large table row threshold</Label>
                    <Input
                      id="large-row-threshold"
                      type="number"
                      min={1}
                      value={migrationForm.large_table_row_threshold}
                      onChange={(e) =>
                        updateMigrationField(
                          "large_table_row_threshold",
                          Number(e.target.value),
                        )
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="large-size-threshold">Large table size threshold (MB)</Label>
                    <Input
                      id="large-size-threshold"
                      type="number"
                      min={0.1}
                      step={1}
                      value={migrationForm.large_table_size_mb_threshold}
                      onChange={(e) =>
                        updateMigrationField(
                          "large_table_size_mb_threshold",
                          Number(e.target.value),
                        )
                      }
                    />
                  </div>
                </div>
              )}

              <Button onClick={handleSaveMigrationSettings} disabled={savingMigration}>
                {savingMigration ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Save className="h-4 w-4 mr-2" />
                )}
                {savingMigration ? "Saving…" : "Save migration settings"}
              </Button>

              <p className="text-xs text-muted-foreground">
                Requires admin role to save. Settings apply to all new migration jobs immediately.
                {migrationConfig?.updated_at && (
                  <> Last updated: {new Date(migrationConfig.updated_at).toLocaleString()}.</>
                )}
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="replication" className="space-y-4" role="tabpanel">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <RefreshCw className="h-5 w-5" />
                CDC capture tuning
              </CardTitle>
              <CardDescription>
                Control how often SQL Server CDC is polled and how many change rows are read per
                poll. These settings apply to all replication streams.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-2 max-w-2xl">
                <div className="space-y-2">
                  <Label htmlFor="replication-poll-sec">Poll interval (seconds)</Label>
                  <Input
                    id="replication-poll-sec"
                    type="number"
                    min={0.1}
                    max={600}
                    step={0.1}
                    value={replicationForm.poll_interval_ms / 1000}
                    onChange={(e) =>
                      updateReplicationField(
                        "poll_interval_ms",
                        Math.round(Number(e.target.value) * 1000),
                      )
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Current: every {(replicationForm.poll_interval_ms / 1000).toFixed(1)}s (
                    {replicationForm.poll_interval_ms} ms). Minimum 0.1s.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="replication-batch-size">Rows per CDC chunk</Label>
                  <Input
                    id="replication-batch-size"
                    type="number"
                    min={1}
                    max={10000}
                    value={replicationForm.batch_size}
                    onChange={(e) =>
                      updateReplicationField("batch_size", Number(e.target.value))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Maximum change rows fetched from SQL Server per table per poll.
                  </p>
                </div>
              </div>

              <Button onClick={handleSaveReplicationSettings} disabled={savingReplication}>
                {savingReplication ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Save className="h-4 w-4 mr-2" />
                )}
                {savingReplication ? "Saving…" : "Save replication settings"}
              </Button>

              <p className="text-xs text-muted-foreground">
                Requires admin role to save. Active streams pick up changes immediately; new streams
                use these values on start.
                {replicationConfig?.updated_at && (
                  <> Last updated: {new Date(replicationConfig.updated_at).toLocaleString()}.</>
                )}
              </p>
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

          <ConnectionPrivilegeScriptsPanel />

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
                        The same type, host, port, and database are already configured:
                      </p>
                      <ul className="text-xs list-disc pl-4 space-y-0.5">
                        {similarConnections.map((c) => (
                          <li key={c.id}>
                            <span className="font-medium">{c.name}</span>
                            {" "}
                            ({c.type} · {c.host}:{c.port} / {c.database})
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
                  onChange={(e) => {
                    setTestOnSave(e.target.checked);
                    localStorage.setItem(
                      "connection_test_on_save",
                      e.target.checked ? "true" : "false",
                    );
                  }}
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
                  A connection with the same type, host, port, and database is already saved. Add another anyway?
                </p>
                <ul className="text-sm list-disc pl-4 space-y-1">
                  {similarConnections.map((c) => (
                    <li key={c.id}>
                      <span className="font-medium">{c.name}</span>
                      {" "}
                      ({c.type} · {c.host}:{c.port} / {c.database})
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
