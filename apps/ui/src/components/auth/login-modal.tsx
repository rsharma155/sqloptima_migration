"use client";

/**
 * Module: components/auth/login-modal.tsx
 * Purpose: Standalone login modal extracted from nav.tsx.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useState } from "react";
import { createPortal } from "react-dom";
import { User, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { login } from "@/lib/api";
import { toast } from "sonner";

interface LoginModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

export function LoginModal({ onClose, onSuccess }: LoginModalProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    const trimmed = username.trim();
    if (!trimmed || !password) {
      toast.error("Enter username and password.");
      return;
    }
    setLoading(true);
    try {
      await login(trimmed, password);
      onSuccess();
      toast.success("Logged in successfully");
    } catch (err: unknown) {
      const msg =
        err instanceof Error && err.message
          ? err.message
          : "Login failed. Check credentials.";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const modal = (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 text-foreground"
      onClick={onClose}
    >
      <div
        className="bg-background text-foreground rounded-lg border shadow-lg w-full max-w-sm mx-4"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Login"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <User className="h-4 w-4" aria-hidden="true" />
            Login
          </h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Close login"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div className="space-y-2">
            <label htmlFor="login-user" className="text-sm font-medium text-foreground">
              Username
            </label>
            <input
              id="login-user"
              className="flex h-10 w-full rounded-md border border-input bg-background text-foreground px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              autoComplete="username"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="login-pass" className="text-sm font-medium text-foreground">
              Password
            </label>
            <input
              id="login-pass"
              type="password"
              className="flex h-10 w-full rounded-md border border-input bg-background text-foreground px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              placeholder="password"
              autoComplete="current-password"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleLogin} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
            ) : null}
            {loading ? "Logging in…" : "Login"}
          </Button>
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return null;
  return createPortal(modal, document.body);
}
