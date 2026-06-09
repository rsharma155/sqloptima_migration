"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { getApiBase, getToken, purgeStaleAuth } from "@/lib/api";

/**
 * Runs on every page load to enforce the first-time setup and login flow:
 * 1. If no users exist in the DB → redirect to /setup (checked on ALL pages including /login)
 * 2. If users exist but no auth token and not on /login → redirect to /login
 * 3. Otherwise → stay on the current page
 *
 * Only /setup itself is skipped to avoid a redirect loop during account creation.
 */
export function AuthInit() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Never run the check while the user is actively filling in the setup form
    if (pathname === "/setup") return;

    async function checkAuth() {
      purgeStaleAuth();
      try {
        const res = await fetch(`${getApiBase()}/api/v1/auth/setup-required`);
        if (!res.ok) return;
        const { setup_required } = await res.json() as { setup_required: boolean };
        if (setup_required) {
          // No users in the DB yet — always go to setup, even from /login
          router.replace("/setup");
          return;
        }
        // Users exist; redirect to login only when not already there and no token present
        if (pathname !== "/login" && !getToken()) {
          router.replace("/login");
        }
      } catch {
        // Backend unreachable — leave existing state intact
      }
    }

    checkAuth();
  }, [pathname, router]);

  return null;
}
