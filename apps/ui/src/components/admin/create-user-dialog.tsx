"use client";

/**
 * Module: components/admin/create-user-dialog.tsx
 * Purpose: Modern create-user dialog with validation, password strength, and role picker.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useEffect, useState, type ComponentType, type FormEvent } from "react";
import {
  UserPlus,
  Eye,
  EyeOff,
  CheckCircle2,
  XCircle,
  Loader2,
  Shield,
  Wrench,
  Eye as EyeIcon,
  Mail,
  User,
  Lock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { toast } from "sonner";
import { createUser } from "@/lib/api";

export type UserRole = "admin" | "operator" | "viewer";

interface CreateUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: () => void;
}

interface PasswordStrength {
  hasLength: boolean;
  hasUppercase: boolean;
  hasLowercase: boolean;
  hasNumber: boolean;
  hasSpecial: boolean;
  score: number;
}

const STRENGTH_COLORS = ["", "bg-red-500", "bg-orange-400", "bg-yellow-400", "bg-green-400", "bg-green-500"];
const STRENGTH_LABELS = ["", "Weak", "Fair", "Moderate", "Strong", "Very Strong"];

const ROLE_OPTIONS: Array<{
  value: UserRole;
  label: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
  accent: string;
  ring: string;
}> = [
  {
    value: "viewer",
    label: "Viewer",
    description: "Read-only access to migrations and reports",
    icon: EyeIcon,
    accent: "text-slate-400 bg-slate-500/10 border-slate-500/25",
    ring: "ring-slate-500/40",
  },
  {
    value: "operator",
    label: "Operator",
    description: "Run migrations, manage connections, view all data",
    icon: Wrench,
    accent: "text-blue-400 bg-blue-500/10 border-blue-500/25",
    ring: "ring-blue-500/40",
  },
  {
    value: "admin",
    label: "Admin",
    description: "Full platform access including user management",
    icon: Shield,
    accent: "text-red-400 bg-red-500/10 border-red-500/25",
    ring: "ring-red-500/40",
  },
];

function getPasswordStrength(p: string): PasswordStrength {
  const hasLength = p.length >= 8;
  const hasUppercase = /[A-Z]/.test(p);
  const hasLowercase = /[a-z]/.test(p);
  const hasNumber = /\d/.test(p);
  const hasSpecial = /[@$!%*?&._\-#^]/.test(p);
  const score = [hasLength, hasUppercase, hasLowercase, hasNumber, hasSpecial].filter(Boolean).length;
  return { hasLength, hasUppercase, hasLowercase, hasNumber, hasSpecial, score };
}

function validateUsername(v: string): string | null {
  if (!v.trim()) return "Username is required";
  if (v.length < 3) return "Must be at least 3 characters";
  if (v.length > 50) return "Must be 50 characters or fewer";
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$/.test(v))
    return "Letters, numbers, _ and - only";
  return null;
}

function validateEmail(v: string): string | null {
  if (!v.trim()) return "Email is required";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return "Enter a valid email address";
  return null;
}

function validatePassword(v: string, strength: PasswordStrength): string | null {
  if (!v) return "Password is required";
  if (!strength.hasLength) return "Must be at least 8 characters";
  if (!strength.hasUppercase) return "Include an uppercase letter";
  if (!strength.hasLowercase) return "Include a lowercase letter";
  if (!strength.hasNumber) return "Include a number";
  if (!strength.hasSpecial) return "Include a special character";
  return null;
}

const EMPTY_FORM = {
  email: "",
  username: "",
  password: "",
  confirm: "",
  role: "viewer" as UserRole,
};

export function CreateUserDialog({ open, onOpenChange, onCreated }: CreateUserDialogProps) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [touched, setTouched] = useState({
    email: false,
    username: false,
    password: false,
    confirm: false,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [creating, setCreating] = useState(false);

  const strength = getPasswordStrength(form.password);
  const usernameError = touched.username ? validateUsername(form.username) : null;
  const emailError = touched.email ? validateEmail(form.email) : null;
  const passwordError = touched.password ? validatePassword(form.password, strength) : null;
  const confirmError =
    touched.confirm && form.confirm && form.confirm !== form.password
      ? "Passwords do not match"
      : null;

  const isValid =
    !validateUsername(form.username) &&
    !validateEmail(form.email) &&
    !validatePassword(form.password, strength) &&
    form.password === form.confirm &&
    !!form.confirm;

  useEffect(() => {
    if (!open) {
      setForm(EMPTY_FORM);
      setTouched({ email: false, username: false, password: false, confirm: false });
      setShowPassword(false);
      setShowConfirm(false);
    }
  }, [open]);

  const touch = (field: keyof typeof touched) => {
    setTouched((t) => ({ ...t, [field]: true }));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched({ email: true, username: true, password: true, confirm: true });
    if (!isValid) return;

    setCreating(true);
    try {
      await createUser({
        email: form.email.trim(),
        username: form.username.trim(),
        password: form.password,
        role: form.role,
      });
      toast.success(`User "${form.username.trim()}" created`);
      onOpenChange(false);
      onCreated?.();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-2xl p-0 gap-0 flex flex-col max-h-[min(90vh,720px)] overflow-hidden">
        <DialogHeader className="px-6 py-5 border-b shrink-0">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <UserPlus className="h-5 w-5" />
            </div>
            <div className="space-y-1 min-w-0">
              <DialogTitle>
                <span className="text-xl">Create User</span>
              </DialogTitle>
              <DialogDescription>
                Add a team member with the right role and secure credentials.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} noValidate className="flex flex-col flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
            {/* Account details */}
            <section className="space-y-4">
              <h3 className="text-sm font-medium text-foreground">Account details</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="cu-username" className="flex items-center gap-1.5">
                    <User className="h-3.5 w-3.5 text-muted-foreground" />
                    Username
                  </Label>
                  <Input
                    id="cu-username"
                    value={form.username}
                    onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                    onBlur={() => touch("username")}
                    placeholder="jsmith"
                    autoComplete="username"
                    className={usernameError ? "border-destructive" : ""}
                  />
                  {usernameError && (
                    <p className="text-xs text-destructive flex items-center gap-1">
                      <XCircle className="h-3 w-3 shrink-0" />
                      {usernameError}
                    </p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cu-email" className="flex items-center gap-1.5">
                    <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                    Email
                  </Label>
                  <Input
                    id="cu-email"
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                    onBlur={() => touch("email")}
                    placeholder="user@company.com"
                    autoComplete="email"
                    className={emailError ? "border-destructive" : ""}
                  />
                  {emailError && (
                    <p className="text-xs text-destructive flex items-center gap-1">
                      <XCircle className="h-3 w-3 shrink-0" />
                      {emailError}
                    </p>
                  )}
                </div>
              </div>
            </section>

            {/* Security */}
            <section className="space-y-4">
              <h3 className="text-sm font-medium text-foreground">Security</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="cu-password" className="flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                    Password
                  </Label>
                  <div className="relative">
                    <Input
                      id="cu-password"
                      type={showPassword ? "text" : "password"}
                      value={form.password}
                      onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                      onBlur={() => touch("password")}
                      placeholder="Create a strong password"
                      autoComplete="new-password"
                      className={`pr-10 ${passwordError ? "border-destructive" : ""}`}
                    />
                    <button
                      type="button"
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      onClick={() => setShowPassword((s) => !s)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="cu-confirm" className="flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                    Confirm password
                  </Label>
                  <div className="relative">
                    <Input
                      id="cu-confirm"
                      type={showConfirm ? "text" : "password"}
                      value={form.confirm}
                      onChange={(e) => setForm((f) => ({ ...f, confirm: e.target.value }))}
                      onBlur={() => touch("confirm")}
                      placeholder="Re-enter password"
                      autoComplete="new-password"
                      className={`pr-10 ${confirmError ? "border-destructive" : ""}`}
                    />
                    <button
                      type="button"
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      onClick={() => setShowConfirm((s) => !s)}
                      aria-label={showConfirm ? "Hide password" : "Show password"}
                    >
                      {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  {confirmError ? (
                    <p className="text-xs text-destructive flex items-center gap-1">
                      <XCircle className="h-3 w-3 shrink-0" />
                      {confirmError}
                    </p>
                  ) : touched.confirm && form.confirm && form.confirm === form.password ? (
                    <p className="text-xs text-emerald-500 flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 shrink-0" />
                      Passwords match
                    </p>
                  ) : null}
                </div>
              </div>

              {form.password && (
                <div className="rounded-lg border border-border bg-muted/20 px-4 py-3 space-y-2">
                  <div className="flex gap-1">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <div
                        key={i}
                        className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
                          i < strength.score ? STRENGTH_COLORS[strength.score] : "bg-muted"
                        }`}
                      />
                    ))}
                  </div>
                  {strength.score > 0 && (
                    <p className="text-xs text-muted-foreground">{STRENGTH_LABELS[strength.score]}</p>
                  )}
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-1">
                    {[
                      { ok: strength.hasLength, label: "8+ characters" },
                      { ok: strength.hasUppercase, label: "Uppercase" },
                      { ok: strength.hasLowercase, label: "Lowercase" },
                      { ok: strength.hasNumber, label: "Number" },
                      { ok: strength.hasSpecial, label: "Special char" },
                    ].map(({ ok, label }) => (
                      <div
                        key={label}
                        className={`flex items-center gap-1 text-xs ${
                          ok ? "text-emerald-500" : "text-muted-foreground"
                        }`}
                      >
                        {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                        {label}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {passwordError && (
                <p className="text-xs text-destructive flex items-center gap-1">
                  <XCircle className="h-3 w-3 shrink-0" />
                  {passwordError}
                </p>
              )}
            </section>

            {/* Role */}
            <section className="space-y-3">
              <h3 className="text-sm font-medium text-foreground">Platform role</h3>
              <div className="grid gap-3 sm:grid-cols-3">
                {ROLE_OPTIONS.map((role) => {
                  const Icon = role.icon;
                  const selected = form.role === role.value;
                  return (
                    <button
                      key={role.value}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, role: role.value }))}
                      className={`rounded-lg border p-3 text-left transition-all hover:bg-muted/30 ${
                        selected
                          ? `border-primary/50 bg-primary/5 ring-2 ${role.ring}`
                          : "border-border"
                      }`}
                    >
                      <div className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium mb-2 ${role.accent}`}>
                        <Icon className="h-3 w-3" />
                        {role.label}
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">{role.description}</p>
                    </button>
                  );
                })}
              </div>
            </section>
          </div>

          <DialogFooter className="px-6 py-4 border-t shrink-0 bg-muted/10">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={creating}>
              Cancel
            </Button>
            <Button type="submit" disabled={creating || !isValid}>
              {creating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Creating…
                </>
              ) : (
                <>
                  <UserPlus className="h-4 w-4 mr-2" />
                  Create User
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
