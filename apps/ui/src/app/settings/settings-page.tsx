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
  Info,
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
  ArrowLeftRight,
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
  getTransferSettings,
  saveTransferSettings,
  type AlertConfigUpdateRequest,
  type MigrationSettingsResponse,
  type MigrationSettingsUpdateRequest,
  type ReplicationSettingsResponse,
  type ReplicationSettingsUpdateRequest,
  type TransferSettingsUpdateRequest,
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
  const queryClient = useQueryClient();
  const { theme: currentTheme, setTheme: setNextTheme } = useTheme();
  const theme = (currentTheme as Theme) ?? "dark";
  const [activeTab, setActiveTab] = useState("general");
  const [mounted, setMounted] = useState(false);
  const [apiEndpoint, setApiEndpoint] = useState("http://localhost:8508");
  const [migrationEnv, setMigrationEnv] = useState<MigrationEnvironment>("development");
  const [errors, setErrors] = useState<FormErrors>({});
  const [saving, setSaving] = useState(false);
  const [testingAlerts, setTestingAlerts] = useState(false);

  // Form states
  const [showDialog, setShowDialog] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<Connection>>({});
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [showPassword, setShowPassword] = useState(false);
  const [testOnSave, setTestOnSave] = useState(true);
  const [dialogTesting, setDialogTesting] = useState(false);
  const [similarConnections, setSimilarConnections] = useState<Connection[]>([]);
  const [similarConfirm, setSimilarConfirm] = useState(false);

  // Deletion states
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const dialogRef = useRef<HTMLDivElement>(null);
  const connectionBackdropDown = useRef(false);
  const similarBackdropDown = useRef(false);
  const deleteBackdropDown = useRef(false);

  // Settings states
  const [savingAlerts, setSavingAlerts] = useState(false);
  const [savingMigration, setSavingMigration] = useState(false);
  const [savingReplication, setSavingReplication] = useState(false);
  const [savingTransfer, setSavingTransfer] = useState(false);

  // Fetch settings
  const { data: alertConfig, refetch: refetchAlerts } = useQuery({
    queryKey: ["alertSettings"],
    queryFn: getAlertConfig,
  });

  const { data: migrationConfig, refetch: refetchMigration } = useQuery({
    queryKey: ["migrationSettings"],
    queryFn: getMigrationSettings,
  });

  const { data: replicationConfig, refetch: refetchReplication } = useQuery({
    queryKey: ["replicationSettings"],
    queryFn: getReplicationSettings,
  });

  const { data: transferConfig, refetch: refetchTransfer } = useQuery({
    queryKey: ["transferSettings"],
    queryFn: getTransferSettings,
  });

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
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);

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

  const [transferForm, setTransferForm] = useState<TransferSettingsUpdateRequest>({
    file_offload_enabled: true,
    file_offload_min_rows: 2_000_000,
    file_offload_min_mb: 256,
    staging_path: "",
  });

  useEffect(() => {
    if (alertConfig) {
      setAlertForm({
        webhook_enabled: alertConfig.webhook_enabled,
        webhook_url: "",
        email_enabled: alertConfig.email_enabled,
        smtp_host: alertConfig.smtp_host,
        smtp_port: alertConfig.smtp_port,
        smtp_user: alertConfig.smtp_user,
        smtp_password: "",
        alert_email_to: alertConfig.alert_email_to,
        alert_email_from: alertConfig.alert_email_from,
      });
    }
  }, [alertConfig]);

  useEffect(() => {
    if (migrationConfig) {
      setMigrationForm({
        source_throttle_enabled: migrationConfig.source_throttle_enabled,
        small_table_delay_sec: migrationConfig.small_table_delay_sec,
        large_table_delay_sec: migrationConfig.large_table_delay_sec,
        large_table_row_threshold: migrationConfig.large_table_row_threshold,
        large_table_size_mb_threshold: migrationConfig.large_table_size_mb_threshold,
        max_tables_per_job: migrationConfig.max_tables_per_job,
      });
    }
  }, [migrationConfig]);

  useEffect(() => {
    if (replicationConfig) {
      setReplicationForm({
        poll_interval_ms: replicationConfig.poll_interval_ms,
        batch_size: replicationConfig.batch_size,
      });
    }
  }, [replicationConfig]);

  useEffect(() => {
    if (transferConfig) {
      setTransferForm({
        file_offload_enabled: transferConfig.file_offload_enabled,
        file_offload_min_rows: transferConfig.file_offload_min_rows,
        file_offload_min_mb: transferConfig.file_offload_min_mb,
        staging_path: transferConfig.staging_path || "",
      });
    }
  }, [transferConfig]);

  // Connections
  const [connections, setConnections] = useState<Connection[]>([]);
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    setMounted(true);
    const storedEndpoint = localStorage.getItem("api_endpoint");
    if (storedEndpoint) setApiEndpoint(storedEndpoint);
    setMigrationEnv(loadMigrationEnvironment());
    const loaded = loadConnections();
    setConnections(loaded);

    const savedTestOnSave = localStorage.getItem("connection_test_on_save");
    if (savedTestOnSave !== null) {
      setTestOnSave(savedTestOnSave === "true");
    }

    const handler = () => {
      setConnections(loadConnections());
    };
    window.addEventListener(CONNECTIONS_UPDATED_EVENT, handler);
    return () => window.removeEventListener(CONNECTIONS_UPDATED_EVENT, handler);
  }, []);

  useEffect(() => {
    const similar = findSimilarConnections(
      connections,
      (form.type || "source") as "source" | "target",
      form.host,
      form.database,
      form.port,
      editingId,
    );
    setSimilarConnections(similar);
  }, [form, connections, editingId]);

  useEffect(() => {
    if (!showDialog) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setShowDialog(false);
        setEditingId(null);
        setForm({});
        setFormErrors({});
        setSimilarConfirm(false);
      }
      if (e.key === "Tab") {
        const dialog = dialogRef.current;
        if (!dialog) return;
        const focusable = dialog.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    const timer = setTimeout(() => {
      const first = dialogRef.current?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      first?.focus();
    }, 50);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [showDialog]);

  const updateFormField = (field: keyof Connection, value: any) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    if (formErrors[field]) {
      setFormErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  const updateAlertField = <K extends keyof AlertConfigUpdateRequest>(
    field: K,
    value: AlertConfigUpdateRequest[K],
  ) => {
    setAlertForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateMigrationField = (field: keyof MigrationSettingsUpdateRequest, value: any) => {
    setMigrationForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateReplicationField = (field: keyof ReplicationSettingsUpdateRequest, value: any) => {
    setReplicationForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateTransferField = <K extends keyof TransferSettingsUpdateRequest>(
    field: K,
    value: TransferSettingsUpdateRequest[K],
  ) => {
    setTransferForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveAlerts = async () => {
    setSavingAlerts(true);
    try {
      await saveAlertConfig(alertForm);
      toast.success("Alert settings saved");
      void refetchAlerts();
    } catch (err: any) {
      toast.error(err.message || "Failed to save alert settings");
    } finally {
      setSavingAlerts(false);
    }
  };

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

  const handleTestApiConnection = async () => {
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
      await testAlertChannels();
      toast.info("Test alerts sent to all configured channels");
    } catch (err: any) {
      toast.error(err.message || "Failed to send test alerts");
    } finally {
      setTestingAlerts(false);
    }
  };

  const handleSaveMigrationSettings = async () => {
    setSavingMigration(true);
    try {
      await saveMigrationSettings(migrationForm);
      toast.success("Migration platform settings saved");
      void refetchMigration();
    } catch (err: any) {
      toast.error(err.message || "Failed to save migration settings");
    } finally {
      setSavingMigration(false);
    }
  };

  const handleSaveReplicationSettings = async () => {
    setSavingReplication(true);
    try {
      await saveReplicationSettings(replicationForm);
      toast.success("Replication settings saved");
      void refetchReplication();
    } catch (err: any) {
      toast.error(err.message || "Failed to save replication settings");
    } finally {
      setSavingReplication(false);
    }
  };

  const handleSaveTransferSettings = async () => {
    setSavingTransfer(true);
    try {
      await saveTransferSettings(transferForm);
      toast.success("Transfer platform settings saved");
      void refetchTransfer();
    } catch (err: any) {
      toast.error(err.message || "Failed to save transfer settings");
    } finally {
      setSavingTransfer(false);
    }
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
    } else if (data.type === "target" && data.database.trim().toLowerCase() === "postgres") {
      errs.database = "The default 'postgres' database cannot be used as a target. Please create a new target database.";
    } else if (data.type === "source" && ["master", "model", "msdb", "tempdb", "distribution"].includes(data.database.trim().toLowerCase())) {
      errs.database = "System databases cannot be migrated. Please select a user database.";
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
          engine: trimmed.engine,
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
          engine: trimmed.engine,
          host: trimmed.host,
          port: trimmed.port,
          database: trimmed.database,
          username: trimmed.username,
          password: trimmed.password,
          trust_server_certificate: trimmed.trust_server_certificate,
        });
        trimmed.id = resp.id;
      }

      saveConnections(dedupeConnections([...connections.filter((c) => c.id !== trimmed.id), trimmed]));
    } catch (err: any) {
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
      engine: (form.engine as "sqlserver" | "postgres") || (form.type === "target" ? "postgres" : "sqlserver"),
      host: form.host!.trim(),
      port: Number(form.port),
      database: form.database!.trim(),
      username: form.username!.trim(),
      password: form.password || existing?.password || "",
      trust_server_certificate: Boolean(form.trust_server_certificate),
      status: existing?.status || "disconnected",
    };

    if (testOnSave) {
      setDialogTesting(true);
      try {
        const testResp = await apiTestRawConnection({
          name: trimmed.name,
          type: trimmed.type,
          engine: trimmed.engine,
          host: trimmed.host,
          port: trimmed.port,
          database: trimmed.database,
          username: trimmed.username,
          password: trimmed.password,
          trust_server_certificate: trimmed.trust_server_certificate,
        });

        if (testResp.status === "connected") {
          trimmed.status = "connected";
          toast.success(`Connection to ${trimmed.name} successful`);
        } else {
          trimmed.status = "error";
          toast.error(`Connection test failed: ${testResp.message}`);
        }
      } catch (err: any) {
        trimmed.status = "error";
        toast.error(`Connection test failed: ${err.message}`);
      } finally {
        setDialogTesting(false);
      }
    }

    const ok = await persistConnection(trimmed);
    if (ok) closeDialog();
  };

  const handleDialogTestConnection = async () => {
    const errs = validateConnectionForm(form);
    setFormErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setDialogTesting(true);
    try {
      const existing = editingId ? connections.find((c) => c.id === editingId) : null;
      const resp = await apiTestRawConnection({
        name: form.name!.trim(),
        type: form.type as "source" | "target",
        engine: (form.engine as "sqlserver" | "postgres") || (form.type === "target" ? "postgres" : "sqlserver"),
        host: form.host!.trim(),
        port: Number(form.port),
        database: form.database!.trim(),
        username: form.username!.trim(),
        password: form.password || existing?.password || "",
        trust_server_certificate: Boolean(form.trust_server_certificate),
      });

      if (resp.status === "connected") {
        toast.success("Connection test successful");
      } else {
        toast.error(`Connection test failed: ${resp.message}`);
      }
    } catch (err: any) {
      toast.error(`Connection test failed: ${err.message}`);
    } finally {
      setDialogTesting(false);
    }
  };

  const handleDeleteConnection = (id: string) => {
    setDeleteTargetId(id);
  };

  const confirmDelete = async () => {
    if (!deleteTargetId) return;
    setDeleting(true);
    try {
      await apiUpdateConnection(deleteTargetId, {
        name: connections.find((c) => c.id === deleteTargetId)?.name || "",
        type: connections.find((c) => c.id === deleteTargetId)?.type || "source",
        host: "",
        port: 0,
        database: "",
        username: "",
        password: "",
      });
      // The API should handle deletion if it's a DELETE request, but here we're using update as a proxy or just removing locally
      removeConnection(deleteTargetId);
      toast.success("Connection removed");
    } catch (err) {
      removeConnection(deleteTargetId);
      toast.info("Connection removed from local storage");
    } finally {
      setDeleting(false);
      setDeleteTargetId(null);
    }
  };

  const openAddDialog = () => {
    setEditingId(null);
    setForm({
      type: "source",
      engine: "sqlserver",
      host: "localhost",
      port: 1433,
      trust_server_certificate: true,
    });
    setFormErrors({});
    setShowDialog(true);
  };

  const openEditDialog = (conn: Connection) => {
    setEditingId(conn.id);
    setForm({ ...conn, password: "" });
    setFormErrors({});
    setShowDialog(true);
  };

  const closeDialog = () => {
    setShowDialog(false);
    setEditingId(null);
    setForm({});
    setFormErrors({});
    setSimilarConfirm(false);
  };

  const handleToggleConnection = async (id: string) => {
    setTestingIds((prev) => new Set(prev).add(id));
    try {
      const resp = await apiTestConnection(id);
      const updated = connections.map((c) =>
        c.id === id ? { ...c, status: resp.status as any } : c,
      );
      setConnections(updated);
      saveConnections(updated);
      if (resp.status === "connected") {
        toast.success("Connection successful");
      } else {
        toast.error(resp.message || "Connection failed");
      }
    } catch (err: any) {
      toast.error(err.message || "Failed to test connection");
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const deleteTarget = deleteTargetId ? connections.find((c) => c.id === deleteTargetId) : null;

  if (!mounted) return null;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configure your migration platform preferences
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList aria-label="Settings tabs" className="flex-wrap h-auto">
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
          <TabsTrigger value="transfer" className="flex items-center gap-2">
            <ArrowLeftRight className="h-4 w-4" aria-hidden="true" />
            Transfer
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
                    type="button"
                    onClick={() => handleThemeChange(value)}
                    role="radio"
                    aria-checked={theme === value}
                    aria-label={`${label} theme`}
                    className={`flex flex-col items-center gap-2 rounded-lg border-2 p-4 transition-all ${
                      theme === value
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
                <div className="flex flex-col gap-2 sm:flex-row">
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
                    onClick={handleTestApiConnection}
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
                External alerts for migration failures — configure in the Notifications tab or via server environment variables
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

              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => setActiveTab("notifications")}>
                  Open notification settings
                </Button>
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
              </div>
              {!alertConfig?.channels_active && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  Configure at least one channel in the Notifications tab or in <code className="text-[10px]">.env</code>, then restart the API to enable test sends.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Notification Channels</CardTitle>
              <CardDescription>
                Webhook and email alerts for migration failures and platform warnings
                {alertConfig?.source && alertConfig.source !== "none" && (
                  <> — active source: {alertConfig.source}</>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-8">
              <div className="space-y-4">
                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="webhook-enabled"
                    checked={alertForm.webhook_enabled}
                    onChange={(e) => updateAlertField("webhook_enabled", e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  <Label htmlFor="webhook-enabled" className="flex items-center gap-2 cursor-pointer">
                    <Webhook className="h-4 w-4" />
                    Webhook alerts
                  </Label>
                  {alertConfig?.webhook_configured && (
                    <Badge variant="outline" className="text-xs">configured</Badge>
                  )}
                </div>
                {alertForm.webhook_enabled && (
                  <div className="space-y-2 pl-6">
                    <Label htmlFor="webhook-url">Webhook URL</Label>
                    <Input
                      id="webhook-url"
                      placeholder={
                        alertConfig?.webhook_configured
                          ? "Leave blank to keep existing URL"
                          : "https://hooks.slack.com/services/..."
                      }
                      value={alertForm.webhook_url}
                      onChange={(e) => updateAlertField("webhook_url", e.target.value)}
                    />
                    {alertConfig?.webhook_url && (
                      <p className="text-xs text-muted-foreground">
                        Current: {alertConfig.webhook_url}
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="email-enabled"
                    checked={alertForm.email_enabled}
                    onChange={(e) => updateAlertField("email_enabled", e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  <Label htmlFor="email-enabled" className="flex items-center gap-2 cursor-pointer">
                    <Mail className="h-4 w-4" />
                    Email alerts
                  </Label>
                  {alertConfig?.email_configured && (
                    <Badge variant="outline" className="text-xs">configured</Badge>
                  )}
                </div>
                {alertForm.email_enabled && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pl-6">
                    <div className="space-y-2">
                      <Label htmlFor="smtp-host">SMTP Host</Label>
                      <Input
                        id="smtp-host"
                        placeholder="smtp.example.com"
                        value={alertForm.smtp_host}
                        onChange={(e) => updateAlertField("smtp_host", e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="smtp-port">SMTP Port</Label>
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
                      <Label htmlFor="smtp-user">SMTP User</Label>
                      <Input
                        id="smtp-user"
                        value={alertForm.smtp_user}
                        onChange={(e) => updateAlertField("smtp_user", e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="smtp-password">SMTP Password</Label>
                      <div className="relative">
                        <Input
                          id="smtp-password"
                          type={showSmtpPassword ? "text" : "password"}
                          placeholder={
                            alertConfig?.smtp_password_set
                              ? "Leave blank to keep existing password"
                              : "SMTP password"
                          }
                          value={alertForm.smtp_password}
                          onChange={(e) => updateAlertField("smtp_password", e.target.value)}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="absolute right-0 top-0 h-full px-3"
                          onClick={() => setShowSmtpPassword((v) => !v)}
                        >
                          {showSmtpPassword ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="alert-email-to">Alert Recipients</Label>
                      <Input
                        id="alert-email-to"
                        placeholder="devops@example.com"
                        value={alertForm.alert_email_to}
                        onChange={(e) => updateAlertField("alert_email_to", e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="alert-email-from">From Address</Label>
                      <Input
                        id="alert-email-from"
                        placeholder="alerts@example.com"
                        value={alertForm.alert_email_from}
                        onChange={(e) => updateAlertField("alert_email_from", e.target.value)}
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                <Button onClick={handleSaveAlerts} disabled={savingAlerts}>
                  {savingAlerts ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4 mr-2" />
                  )}
                  Save Channels
                </Button>
                <Button variant="outline" onClick={handleTestAlerts}>
                  Send Test Alert
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="migration" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Migration Engine Settings</CardTitle>
              <CardDescription>
                Source throttling and per-job table limits for the Go migration plane
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="source-throttle"
                  checked={migrationForm.source_throttle_enabled}
                  onChange={(e) =>
                    updateMigrationField("source_throttle_enabled", e.target.checked)
                  }
                  className="h-4 w-4 rounded border-gray-300"
                />
                <Label htmlFor="source-throttle" className="cursor-pointer">
                  Enable source throttling
                </Label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <Label htmlFor="small-table-delay">Small Table Delay (sec)</Label>
                  <Input
                    id="small-table-delay"
                    type="number"
                    min={0}
                    step={0.1}
                    value={migrationForm.small_table_delay_sec}
                    onChange={(e) =>
                      updateMigrationField("small_table_delay_sec", Number(e.target.value))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Pause between small table migrations to reduce source load.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="large-table-delay">Large Table Delay (sec)</Label>
                  <Input
                    id="large-table-delay"
                    type="number"
                    min={0}
                    step={0.1}
                    value={migrationForm.large_table_delay_sec}
                    onChange={(e) =>
                      updateMigrationField("large_table_delay_sec", Number(e.target.value))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Pause between large table migrations. Must be at least the small table delay.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="large-row-threshold">Large Table Row Threshold</Label>
                  <Input
                    id="large-row-threshold"
                    type="number"
                    min={1}
                    value={migrationForm.large_table_row_threshold}
                    onChange={(e) =>
                      updateMigrationField("large_table_row_threshold", Number(e.target.value))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="large-size-threshold">Large Table Size Threshold (MB)</Label>
                  <Input
                    id="large-size-threshold"
                    type="number"
                    min={1}
                    step={0.1}
                    value={migrationForm.large_table_size_mb_threshold}
                    onChange={(e) =>
                      updateMigrationField("large_table_size_mb_threshold", Number(e.target.value))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="max-tables-per-job">Max Tables per Job</Label>
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
                    Maximum tables included in a single migration job.
                  </p>
                </div>
              </div>

              <Button onClick={handleSaveMigrationSettings} disabled={savingMigration}>
                {savingMigration ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Save className="h-4 w-4 mr-2" />
                )}
                Save migration settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="replication" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Replication / CDC Settings</CardTitle>
              <CardDescription>Fine-tune live data sync performance</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <Label htmlFor="replication-poll">Poll Interval (ms)</Label>
                  <Input
                    id="replication-poll"
                    type="number"
                    min={100}
                    max={60000}
                    value={replicationForm.poll_interval_ms}
                    onChange={(e) =>
                      updateReplicationField("poll_interval_ms", Number(e.target.value))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Frequency to poll SQL Server for CDC changes (current:{" "}
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

        <TabsContent value="transfer" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Transfer file offload</CardTitle>
              <CardDescription>
                Cross-server SQL Server copies can stage native BCP files when a table is large
                enough. Same-server copies never use files. New transfer jobs snapshot these values.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="file-offload-enabled"
                  checked={transferForm.file_offload_enabled}
                  onChange={(e) =>
                    updateTransferField("file_offload_enabled", e.target.checked)
                  }
                  className="h-4 w-4 rounded border-gray-300"
                />
                <Label htmlFor="file-offload-enabled" className="cursor-pointer">
                  Enable file offload for large cross-server tables
                </Label>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <Label htmlFor="file-offload-min-rows">Minimum rows</Label>
                  <Input
                    id="file-offload-min-rows"
                    type="number"
                    min={1}
                    value={transferForm.file_offload_min_rows}
                    onChange={(e) =>
                      updateTransferField("file_offload_min_rows", Number(e.target.value))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Use native file offload when the source estimate is at least this many rows.
                    Default is 2,000,000.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="file-offload-min-mb">Minimum size (MB)</Label>
                  <Input
                    id="file-offload-min-mb"
                    type="number"
                    min={0.1}
                    step={0.1}
                    value={transferForm.file_offload_min_mb}
                    onChange={(e) =>
                      updateTransferField("file_offload_min_mb", Number(e.target.value))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Offload also triggers when estimated table size meets this threshold.
                  </p>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="file-offload-staging">Staging path (optional)</Label>
                  <Input
                    id="file-offload-staging"
                    value={transferForm.staging_path}
                    onChange={(e) => updateTransferField("staging_path", e.target.value)}
                    placeholder="Leave empty to use the worker default"
                  />
                  <p className="text-xs text-muted-foreground">
                    Directory or share the Go transfer worker writes BCP files to. Empty uses the
                    engine default.
                  </p>
                </div>
              </div>

              <Button onClick={handleSaveTransferSettings} disabled={savingTransfer}>
                {savingTransfer ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Save className="h-4 w-4 mr-2" />
                )}
                Save transfer settings
              </Button>
              <p className="text-xs text-muted-foreground">
                Requires admin role to save.
                {transferConfig?.updated_at && (
                  <> Last updated: {new Date(transferConfig.updated_at).toLocaleString()}.</>
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
                        {conn.type === "source" ? "Source" : "Target"} ·{" "}
                        {conn.engine === "postgres" ? "PostgreSQL" : "SQL Server"} &mdash;{" "}
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
          onPointerDown={(e) => {
            connectionBackdropDown.current = e.target === e.currentTarget;
          }}
          onPointerUp={(e) => {
            if (connectionBackdropDown.current && e.target === e.currentTarget) {
              closeDialog();
            }
            connectionBackdropDown.current = false;
          }}
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
              <div className="p-3 rounded-md bg-blue-500/10 border border-blue-500/20 text-xs text-blue-900 dark:text-blue-100">
                <div className="flex gap-2">
                  <Info className="h-4 w-4 shrink-0 mt-0.5" />
                  <p>
                    <strong>Note:</strong> One connection per database migration. If multiple databases need to be migrated, create a separate connection for each database. Migrations are performed at the database level, not at the server/instance level.
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-name">Connection Name <span className="text-destructive">*</span></Label>
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
                <Label htmlFor="conn-type">Connection Type <span className="text-destructive">*</span></Label>
                <select
                  id="conn-type"
                  value={form.type || "source"}
                  onChange={(e) => updateFormField("type", e.target.value as "source" | "target")}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  aria-invalid={!!formErrors.type}
                  aria-describedby={formErrors.type ? "conn-type-error" : undefined}
                >
                  <option value="source">Source (Migrations wizard)</option>
                  <option value="target">Target (Migrations wizard)</option>
                </select>
                {formErrors.type && (
                  <p id="conn-type-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.type}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-engine">Engine <span className="text-destructive">*</span></Label>
                <select
                  id="conn-engine"
                  value={form.engine || (form.type === "target" ? "postgres" : "sqlserver")}
                  onChange={(e) => {
                    const engine = e.target.value as "sqlserver" | "postgres";
                    setForm((prev) => ({
                      ...prev,
                      engine,
                      port: engine === "postgres" ? 5432 : 1433,
                    }));
                  }}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <option value="sqlserver">SQL Server</option>
                  <option value="postgres">PostgreSQL</option>
                </select>
                <p className="text-xs text-muted-foreground">
                  Used by Transfer. Migrations still treat Source as SQL Server and Target as PostgreSQL.
                </p>
              </div>
                {formErrors.type && (
                  <p id="conn-type-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.type}
                  </p>
                )}
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2 space-y-2">
                  <Label htmlFor="conn-host">Host <span className="text-destructive">*</span></Label>
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
                  <Label htmlFor="conn-port">Port <span className="text-destructive">*</span></Label>
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
                <Label htmlFor="conn-db">Database Name <span className="text-destructive">*</span></Label>
                <Input
                  id="conn-db"
                  value={form.database || ""}
                  onChange={(e) => updateFormField("database", e.target.value)}
                  placeholder="e.g. ProductionDB"
                  aria-invalid={!!formErrors.database}
                  aria-describedby={formErrors.database ? "conn-db-error" : undefined}
                />
                <p className="text-[10px] text-muted-foreground leading-tight">
                  {form.type === "target" 
                    ? "Mandatory. For PostgreSQL, do not use the default 'postgres' database. Create a new target database for your migration."
                    : "Mandatory. The specific user database to migrate. System databases (master, msdb, etc.) are not supported."}
                </p>
                {formErrors.database && (
                  <p id="conn-db-error" className="text-xs text-destructive flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {formErrors.database}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="conn-user">Username <span className="text-destructive">*</span></Label>
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
                <Label htmlFor="conn-password">Password {!editingId && <span className="text-destructive">*</span>}</Label>
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
          onPointerDown={(e) => {
            similarBackdropDown.current = e.target === e.currentTarget;
          }}
          onPointerUp={(e) => {
            if (similarBackdropDown.current && e.target === e.currentTarget) {
              setSimilarConfirm(false);
            }
            similarBackdropDown.current = false;
          }}
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
          onPointerDown={(e) => {
            deleteBackdropDown.current = e.target === e.currentTarget;
          }}
          onPointerUp={(e) => {
            if (deleteBackdropDown.current && e.target === e.currentTarget && !deleting) {
              setDeleteTargetId(null);
            }
            deleteBackdropDown.current = false;
          }}
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
