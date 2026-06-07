"use client";

/**
 * Module: app/login/page.tsx
 * Purpose: Standalone full-page login. Also detects first-run (no users) and
 *          redirects to /setup automatically.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Layers, Eye, EyeOff, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { login, getApiBase } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [checkingSetup, setCheckingSetup] = useState(true);

  // Field-level validation errors (shown inline, survive page state)
  const [usernameError, setUsernameError] = useState("");
  const [passwordError, setPasswordError] = useState("");
  // API-level error (wrong credentials, server down, etc.)
  const [loginError, setLoginError] = useState("");

  // On mount: check whether any users exist.
  // If not, redirect immediately to /setup — the login page is useless until
  // at least one admin account is created.
  useEffect(() => {
    async function checkSetup() {
      try {
        const res = await fetch(`${getApiBase()}/api/v1/auth/setup-required`);
        if (res.ok) {
          const { setup_required } = await res.json() as { setup_required: boolean };
          if (setup_required) {
            router.replace("/setup");
            return;
          }
        }
      } catch {
        // API unreachable — show login form; the user will see an error on submit
      } finally {
        setCheckingSetup(false);
      }
    }
    checkSetup();
  }, [router]);

  function validate(): boolean {
    let ok = true;
    if (!username.trim()) {
      setUsernameError("Username is required");
      ok = false;
    } else {
      setUsernameError("");
    }
    if (!password) {
      setPasswordError("Password is required");
      ok = false;
    } else {
      setPasswordError("");
    }
    return ok;
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoginError("");
    if (!validate()) return;

    setLoading(true);
    try {
      await login(username.trim(), password);
      router.replace("/");
    } catch (err: unknown) {
      const msg =
        err instanceof Error && err.message
          ? err.message
          : "Invalid username or password. Please try again.";
      setLoginError(msg);
    } finally {
      setLoading(false);
    }
  }

  // Show a spinner while we check setup-required so there's no flash of the
  // login form before a potential redirect to /setup.
  if (checkingSetup) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-6">

        {/* Branding */}
        <div className="text-center space-y-2">
          <div className="flex items-center justify-center gap-2">
            <Layers className="h-8 w-8 text-primary" />
            <span className="text-2xl font-bold tracking-tight">SQL Optima Migration</span>
          </div>
          <h1 className="text-xl font-semibold">Sign in to your account</h1>
          <p className="text-sm text-muted-foreground">
            SQL Server → PostgreSQL Migration Platform
          </p>
        </div>

        {/* Login form */}
        <form
          onSubmit={handleLogin}
          noValidate
          className="bg-card border rounded-lg p-6 space-y-4 shadow-sm"
        >

          {/* API / credentials error banner */}
          {loginError && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{loginError}</span>
            </div>
          )}

          {/* Username */}
          <div className="space-y-1.5">
            <label htmlFor="login-username" className="text-sm font-medium">
              Username
            </label>
            <input
              id="login-username"
              className={`flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm
                focus:outline-none focus:ring-2 focus:ring-ring transition-colors
                ${usernameError ? "border-destructive" : "border-input"}`}
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                if (usernameError) setUsernameError("");
                if (loginError) setLoginError("");
              }}
              placeholder="Enter your username"
              autoComplete="username"
              autoFocus
              disabled={loading}
            />
            {usernameError && (
              <p className="text-xs text-destructive flex items-center gap-1">
                <AlertCircle className="h-3 w-3 shrink-0" />
                {usernameError}
              </p>
            )}
          </div>

          {/* Password */}
          <div className="space-y-1.5">
            <label htmlFor="login-password" className="text-sm font-medium">
              Password
            </label>
            <div className="relative">
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                className={`flex h-10 w-full rounded-md border bg-background px-3 py-2 pr-10 text-sm
                  focus:outline-none focus:ring-2 focus:ring-ring transition-colors
                  ${passwordError ? "border-destructive" : "border-input"}`}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (passwordError) setPasswordError("");
                  if (loginError) setLoginError("");
                }}
                placeholder="Enter your password"
                autoComplete="current-password"
                disabled={loading}
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground disabled:opacity-50"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                disabled={loading}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {passwordError && (
              <p className="text-xs text-destructive flex items-center gap-1">
                <AlertCircle className="h-3 w-3 shrink-0" />
                {passwordError}
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Signing in…
              </>
            ) : (
              "Sign In"
            )}
          </Button>
        </form>

      </div>
    </div>
  );
}
