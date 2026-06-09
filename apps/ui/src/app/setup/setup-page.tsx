"use client";

/**
 * Module: app/setup/page.tsx
 * Purpose: First-time admin account creation. Shown when no users exist in the DB.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Layers, Eye, EyeOff, CheckCircle, XCircle, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { setupAdmin, ApiError, purgeStaleAuth } from "@/lib/api";
import { toast } from "sonner";

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

function validateUsername(v: string): string | null {
  if (!v) return "Username is required";
  if (v.length < 3) return "Must be at least 3 characters";
  if (v.length > 50) return "Must be 50 characters or fewer";
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$/.test(v))
    return "Only letters, numbers, _ and - allowed; cannot start/end with _ or -";
  return null;
}

function validateEmail(v: string): string | null {
  if (!v) return "Email is required";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return "Enter a valid email address";
  return null;
}

interface PasswordStrength {
  hasLength: boolean;
  hasUppercase: boolean;
  hasLowercase: boolean;
  hasNumber: boolean;
  hasSpecial: boolean;
  score: number;
}

function getPasswordStrength(p: string): PasswordStrength {
  const hasLength = p.length >= 8;
  const hasUppercase = /[A-Z]/.test(p);
  const hasLowercase = /[a-z]/.test(p);
  const hasNumber = /\d/.test(p);
  const hasSpecial = /[@$!%*?&._\-#^]/.test(p);
  const score = [hasLength, hasUppercase, hasLowercase, hasNumber, hasSpecial].filter(Boolean).length;
  return { hasLength, hasUppercase, hasLowercase, hasNumber, hasSpecial, score };
}

function validatePassword(v: string, strength: PasswordStrength): string | null {
  if (!v) return "Password is required";
  if (!strength.hasLength) return "Must be at least 8 characters";
  if (!strength.hasUppercase) return "Must include at least one uppercase letter";
  if (!strength.hasLowercase) return "Must include at least one lowercase letter";
  if (!strength.hasNumber) return "Must include at least one number";
  if (!strength.hasSpecial) return "Must include at least one special character (@$!%*?&._-#^)";
  return null;
}

const STRENGTH_COLORS = ["", "bg-red-500", "bg-orange-400", "bg-yellow-400", "bg-green-400", "bg-green-500"];
const STRENGTH_LABELS = ["", "Weak", "Fair", "Moderate", "Strong", "Very Strong"];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function SetupPage() {
  const router = useRouter();

  const [form, setForm] = useState({ username: "", email: "", password: "", confirm: "" });
  const [touched, setTouched] = useState({ username: false, email: false, password: false, confirm: false });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    purgeStaleAuth();
  }, []);

  const strength = getPasswordStrength(form.password);
  const usernameError = touched.username ? validateUsername(form.username) : null;
  const emailError = touched.email ? validateEmail(form.email) : null;
  const passwordError = touched.password ? validatePassword(form.password, strength) : null;
  const confirmError =
    touched.confirm && form.confirm && form.confirm !== form.password
      ? "Passwords do not match"
      : null;

  const isFormValid =
    !validateUsername(form.username) &&
    !validateEmail(form.email) &&
    !validatePassword(form.password, strength) &&
    form.password === form.confirm &&
    !!form.confirm;

  function touch(field: keyof typeof touched) {
    setTouched((t) => ({ ...t, [field]: true }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ username: true, email: true, password: true, confirm: true });
    if (!isFormValid) return;

    setLoading(true);
    try {
      await setupAdmin({ username: form.username, email: form.email, password: form.password });
      toast.success("Admin account created! Please sign in to continue.");
      router.replace("/login");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Setup failed. Please try again.";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-6">

        {/* Branding */}
        <div className="text-center space-y-2">
          <div className="flex items-center justify-center gap-2">
            <Layers className="h-8 w-8 text-primary" />
            <span className="text-2xl font-bold tracking-tight">SQL Optima Migration</span>
          </div>
          <h1 className="text-xl font-semibold">Welcome! Let&apos;s get you set up</h1>
          <p className="text-sm text-muted-foreground">
            Create your admin account to start using the migration platform.
          </p>
        </div>

        {/* Admin notice */}
        <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700 p-4 flex gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-500 shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-amber-800 dark:text-amber-300">This is the admin account for SQL Optima Migration</p>
            <p className="mt-1 text-amber-700 dark:text-amber-400">
              This account will have full admin privileges — user management, migration controls,
              and all settings. You can create additional users after signing in. Keep your
              credentials safe.
            </p>
          </div>
        </div>

        {/* Form card */}
        <form
          onSubmit={handleSubmit}
          noValidate
          className="bg-card border rounded-lg p-6 space-y-5 shadow-sm"
        >

          {/* Username */}
          <div className="space-y-1.5">
            <label htmlFor="setup-username" className="text-sm font-medium">
              Username
            </label>
            <input
              id="setup-username"
              className={`flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm
                focus:outline-none focus:ring-2 focus:ring-ring transition-colors
                ${usernameError ? "border-destructive" : "border-input"}`}
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              onBlur={() => touch("username")}
              placeholder="admin"
              autoComplete="username"
              autoFocus
              maxLength={50}
            />
            {usernameError ? (
              <p className="text-xs text-destructive flex items-center gap-1">
                <XCircle className="h-3.5 w-3.5 shrink-0" />
                {usernameError}
              </p>
            ) : touched.username && form.username ? (
              <p className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                <CheckCircle className="h-3.5 w-3.5 shrink-0" />
                Looks good
              </p>
            ) : null}
          </div>

          {/* Email */}
          <div className="space-y-1.5">
            <label htmlFor="setup-email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="setup-email"
              type="email"
              className={`flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm
                focus:outline-none focus:ring-2 focus:ring-ring transition-colors
                ${emailError ? "border-destructive" : "border-input"}`}
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              onBlur={() => touch("email")}
              placeholder="admin@company.com"
              autoComplete="email"
            />
            {emailError ? (
              <p className="text-xs text-destructive flex items-center gap-1">
                <XCircle className="h-3.5 w-3.5 shrink-0" />
                {emailError}
              </p>
            ) : touched.email && form.email ? (
              <p className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                <CheckCircle className="h-3.5 w-3.5 shrink-0" />
                Valid email
              </p>
            ) : null}
          </div>

          {/* Password */}
          <div className="space-y-1.5">
            <label htmlFor="setup-password" className="text-sm font-medium">
              Password
            </label>
            <div className="relative">
              <input
                id="setup-password"
                type={showPassword ? "text" : "password"}
                className={`flex h-10 w-full rounded-md border bg-background px-3 py-2 pr-10 text-sm
                  focus:outline-none focus:ring-2 focus:ring-ring transition-colors
                  ${passwordError ? "border-destructive" : "border-input"}`}
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                onBlur={() => touch("password")}
                placeholder="Create a strong password"
                autoComplete="new-password"
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

            {/* Strength bar */}
            {form.password && (
              <div className="space-y-1">
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
              </div>
            )}

            {/* Requirements checklist */}
            {(touched.password || form.password) && (
              <div className="grid grid-cols-2 gap-1 pt-0.5">
                {[
                  { ok: strength.hasLength, label: "8+ characters" },
                  { ok: strength.hasUppercase, label: "Uppercase letter" },
                  { ok: strength.hasLowercase, label: "Lowercase letter" },
                  { ok: strength.hasNumber, label: "Number (0–9)" },
                  { ok: strength.hasSpecial, label: "Special character" },
                ].map(({ ok, label }) => (
                  <div
                    key={label}
                    className={`flex items-center gap-1 text-xs transition-colors ${
                      ok ? "text-green-600 dark:text-green-400" : "text-muted-foreground"
                    }`}
                  >
                    {ok ? (
                      <CheckCircle className="h-3 w-3 shrink-0" />
                    ) : (
                      <XCircle className="h-3 w-3 shrink-0" />
                    )}
                    {label}
                  </div>
                ))}
              </div>
            )}

            {passwordError && (
              <p className="text-xs text-destructive flex items-center gap-1">
                <XCircle className="h-3.5 w-3.5 shrink-0" />
                {passwordError}
              </p>
            )}
          </div>

          {/* Confirm Password */}
          <div className="space-y-1.5">
            <label htmlFor="setup-confirm" className="text-sm font-medium">
              Confirm Password
            </label>
            <div className="relative">
              <input
                id="setup-confirm"
                type={showConfirm ? "text" : "password"}
                className={`flex h-10 w-full rounded-md border bg-background px-3 py-2 pr-10 text-sm
                  focus:outline-none focus:ring-2 focus:ring-ring transition-colors
                  ${confirmError ? "border-destructive" : "border-input"}`}
                value={form.confirm}
                onChange={(e) => setForm((f) => ({ ...f, confirm: e.target.value }))}
                onBlur={() => touch("confirm")}
                placeholder="Re-enter your password"
                autoComplete="new-password"
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
                <XCircle className="h-3.5 w-3.5 shrink-0" />
                {confirmError}
              </p>
            ) : touched.confirm && form.confirm && form.confirm === form.password ? (
              <p className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                <CheckCircle className="h-3.5 w-3.5 shrink-0" />
                Passwords match
              </p>
            ) : null}
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Creating account…
              </>
            ) : (
              "Create Admin Account"
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}
