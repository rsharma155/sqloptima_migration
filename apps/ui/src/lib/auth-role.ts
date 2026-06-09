/**
 * Client-side role helpers — reads the role claim from the JWT access token.
 */

import { getToken } from "@/lib/api";

export type UserRole = "admin" | "operator" | "viewer";

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const segment = token.split(".")[1];
    if (!segment) return null;
    const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function normalizeRole(value: unknown): UserRole | null {
  if (value === "admin" || value === "operator" || value === "viewer") {
    return value;
  }
  return null;
}

/** Return the current user's platform role, or null when not logged in. */
export function getAuthRole(): UserRole | null {
  if (typeof window === "undefined") return null;

  const token = getToken();
  if (token) {
    const payload = decodeJwtPayload(token);
    const fromToken = normalizeRole(payload?.role);
    if (fromToken) return fromToken;
  }

  const stored = localStorage.getItem("auth_role");
  return normalizeRole(stored);
}

export function isViewerRole(): boolean {
  return getAuthRole() === "viewer";
}

/** Viewers cannot access Settings or Admin pages. */
export function canAccessAdminSettingsPages(): boolean {
  const role = getAuthRole();
  return role === "admin" || role === "operator";
}

export function persistAuthRoleFromToken(token: string): void {
  if (typeof window === "undefined") return;
  const payload = decodeJwtPayload(token);
  const role = normalizeRole(payload?.role);
  if (role) {
    localStorage.setItem("auth_role", role);
  }
}

export function clearAuthRole(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("auth_role");
}
