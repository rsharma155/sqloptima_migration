"use client";

/**
 * Module: hooks/use-platform-alerts.ts
 * Purpose: Shared TanStack Query hook for platform-wide alerts.
 */

import { useQuery } from "@tanstack/react-query";
import { getPlatformAlerts, getToken, type AlertsResponse } from "@/lib/api";

export function usePlatformAlerts(enabled = true) {
  const authed = typeof window !== "undefined" && !!getToken();
  return useQuery<AlertsResponse>({
    queryKey: ["platform-alerts"],
    queryFn: getPlatformAlerts,
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    enabled: enabled && authed,
    staleTime: 15_000,
  });
}
