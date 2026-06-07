"use client";

/**
 * Module: app/projects/page.tsx
 * Purpose: CRUD page for migration projects.  Each project pairs a SQL Server
 *          source connection with a PostgreSQL target connection and serves as
 *          the entry-point for discovery, assessment, and migration jobs.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect, useCallback } from "react";
import {
  FolderOpen,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  Database,
  ChevronRight,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getProjects,
  createProject,
  updateProject,
  deleteProject,
  getConnections,
  type Project,
  type ConnectionResponse,
} from "@/lib/api";
import { CONNECTIONS_UPDATED_EVENT } from "@/lib/connection-store";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function connName(id: string | null, connections: ConnectionResponse[]): string {
  if (!id) return "—";
  return connections.find((c) => c.id === id)?.name ?? id.slice(0, 8) + "…";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [loading, setLoading] = useState(true);

  // Dialog state
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formSrc, setFormSrc] = useState("");
  const [formTgt, setFormTgt] = useState("");
  const [saving, setSaving] = useState(false);

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ps, cs] = await Promise.all([getProjects(), getConnections()]);
      setProjects(ps);
      setConnections(cs);
    } catch {
      toast.error("Failed to load projects");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const refreshConnections = () => {
      getConnections()
        .then(setConnections)
        .catch(() => {});
    };
    window.addEventListener(CONNECTIONS_UPDATED_EVENT, refreshConnections);
    return () => window.removeEventListener(CONNECTIONS_UPDATED_EVENT, refreshConnections);
  }, []);

  const openCreate = () => {
    setEditing(null);
    setFormName(""); setFormDesc(""); setFormSrc(""); setFormTgt("");
    setShowDialog(true);
  };

  const openEdit = (p: Project) => {
    setEditing(p);
    setFormName(p.name);
    setFormDesc(p.description ?? "");
    setFormSrc(p.source_connection_id ?? "");
    setFormTgt(p.target_connection_id ?? "");
    setShowDialog(true);
  };

  const handleSave = async () => {
    if (!formName.trim()) { toast.error("Project name is required"); return; }
    setSaving(true);
    try {
      const payload = {
        name: formName.trim(),
        description: formDesc.trim() || undefined,
        source_connection_id: formSrc || undefined,
        target_connection_id: formTgt || undefined,
      };
      if (editing) {
        await updateProject(editing.id, payload);
        toast.success("Project updated");
      } else {
        await createProject(payload);
        toast.success("Project created");
      }
      setShowDialog(false);
      load();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteProject(deleteTarget.id);
      toast.success(`Project "${deleteTarget.name}" deleted`);
      setDeleteTarget(null);
      load();
    } catch {
      toast.error("Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  const srcConns = connections.filter((c) => c.type === "source");
  const tgtConns = connections.filter((c) => c.type === "target");

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Projects"
        description="Group source and target connections into named migration projects"
      >
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" /> New Project
        </Button>
      </PageHeader>

      {loading ? (
        <div className="flex justify-center py-16" role="status" aria-label="Loading">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title="No projects yet"
          description="Create a project to group a SQL Server source with a PostgreSQL target and start your migration journey."
          actionLabel="Create First Project"
          onAction={openCreate}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <Card key={p.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FolderOpen className="h-4 w-4 text-primary" />
                    {p.name}
                  </CardTitle>
                  <div className="flex gap-1">
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(p)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-destructive hover:text-destructive"
                      onClick={() => setDeleteTarget(p)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
                {p.description && (
                  <CardDescription className="text-xs">{p.description}</CardDescription>
                )}
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Database className="h-3.5 w-3.5 text-blue-400" />
                  <span>Source: </span>
                  <span className="text-foreground font-medium">
                    {connName(p.source_connection_id, connections)}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Database className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Target: </span>
                  <span className="text-foreground font-medium">
                    {connName(p.target_connection_id, connections)}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  {p.source_connection_id && (
                    <Button size="sm" variant="outline" className="text-xs h-7" asChild>
                      <a href={`/assessment?connectionId=${p.source_connection_id}`}>
                        Assess <ChevronRight className="h-3 w-3 ml-1" />
                      </a>
                    </Button>
                  )}
                  <Button size="sm" variant="outline" className="text-xs h-7" asChild>
                    <a href={`/discovery/${p.id}`}>Discover</a>
                  </Button>
                  {p.source_connection_id && p.target_connection_id && (
                    <Button size="sm" variant="outline" className="text-xs h-7" asChild>
                      <a href={`/schema-compare/${p.id}`}>Compare</a>
                    </Button>
                  )}
                  <Button size="sm" variant="outline" className="text-xs h-7" asChild>
                    <a href="/migrations">Migrate</a>
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground/60">
                  Created {new Date(p.created_at).toLocaleDateString()}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create / Edit Dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              <span className="flex items-center gap-2">
                <FolderOpen className="h-4 w-4 text-primary" />
                {editing ? "Edit Project" : "New Project"}
              </span>
            </DialogTitle>
            <DialogDescription>
              {editing
                ? "Update project name, description, or connection assignments."
                : "Pair a SQL Server source with a PostgreSQL target to start a migration project."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-1">
            {/* Project info */}
            <div className="rounded-md border border-border bg-muted/20 px-4 py-3 space-y-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Project Info</p>
              <div className="space-y-2">
                <Label htmlFor="pname" className="text-sm">Name <span className="text-destructive">*</span></Label>
                <Input
                  id="pname"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="e.g. Acme DB Migration"
                  className="h-9"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pdesc" className="text-sm">Description <span className="text-muted-foreground font-normal">(optional)</span></Label>
                <Input
                  id="pdesc"
                  value={formDesc}
                  onChange={(e) => setFormDesc(e.target.value)}
                  placeholder="Brief description of this migration"
                  className="h-9"
                />
              </div>
            </div>

            {/* Connections */}
            <div className="rounded-md border border-border bg-muted/20 px-4 py-3 space-y-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Connections</p>
              <div className="space-y-2">
                <Label htmlFor="psrc" className="text-sm flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5 text-blue-400" /> Source (SQL Server)
                </Label>
                <select
                  id="psrc"
                  value={formSrc}
                  onChange={(e) => setFormSrc(e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— none selected —</option>
                  {srcConns.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.host})</option>
                  ))}
                </select>
                {srcConns.length === 0 && (
                  <p className="text-xs text-amber-500">No source connections — <a href="/settings" className="underline">add one in Settings</a>.</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="ptgt" className="text-sm flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5 text-emerald-400" /> Target (PostgreSQL)
                </Label>
                <select
                  id="ptgt"
                  value={formTgt}
                  onChange={(e) => setFormTgt(e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— none selected —</option>
                  {tgtConns.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.host})</option>
                  ))}
                </select>
                {tgtConns.length === 0 && (
                  <p className="text-xs text-amber-500">No target connections — <a href="/settings" className="underline">add one in Settings</a>.</p>
                )}
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setShowDialog(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              {editing ? "Save Changes" : "Create Project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete Project</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete <strong>{deleteTarget?.name}</strong>? This cannot
              be undone.
            </DialogDescription>
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
