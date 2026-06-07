"use client";

/**
 * Module: app/admin/users/page.tsx
 * Purpose: Admin-only user management page — list platform users, create new
 *          accounts, update roles, and deactivate/delete users.
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
  type UserRecord,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Role = "admin" | "operator" | "viewer";

const ROLE_CONFIG: Record<Role, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  admin:    { label: "Admin",    color: "text-red-400 border-red-500/30 bg-red-500/10",    icon: Shield },
  operator: { label: "Operator", color: "text-blue-400 border-blue-500/30 bg-blue-500/10", icon: Shield },
  viewer:   { label: "Viewer",   color: "text-slate-400 border-slate-500/30 bg-slate-500/10", icon: Eye },
};

function RoleBadge({ role }: { role: Role }) {
  const cfg = ROLE_CONFIG[role] ?? ROLE_CONFIG.viewer;
  const Icon = cfg.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${cfg.color}`}
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AdminUsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const [showCreate, setShowCreate] = useState(false);

  // Role update
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  // Delete confirm
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
    <div className="p-6 space-y-6">
      <PageHeader
        title="User Management"
        description="Manage platform users, roles and access. Admin access required."
      >
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> New User
        </Button>
      </PageHeader>

      {/* Role legend */}
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
                          {updatingId === u.id && (
                            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                          )}
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
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => setDeleteTarget(u)}
                        >
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

      {/* Delete confirm */}
      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>
              Delete <strong>{deleteTarget?.username}</strong>? This cannot be undone.
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
