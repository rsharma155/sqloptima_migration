/** Shared dismiss state for platform alerts (session-scoped). */

import type { PlatformAlert } from "@/lib/api";

const DISMISS_KEY = "dismissed_platform_alerts";
const AUTO_POPUP_KEY = "alerts_auto_popup_shown";

export function loadDismissedAlerts(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = sessionStorage.getItem(DISMISS_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function saveDismissedAlerts(ids: Set<string>): void {
  sessionStorage.setItem(DISMISS_KEY, JSON.stringify([...ids]));
}

export function wasAutoPopupShown(): boolean {
  if (typeof window === "undefined") return true;
  return sessionStorage.getItem(AUTO_POPUP_KEY) === "1";
}

export function markAutoPopupShown(): void {
  sessionStorage.setItem(AUTO_POPUP_KEY, "1");
}

export function filterVisibleAlerts(
  alerts: PlatformAlert[],
  dismissed: Set<string>,
): PlatformAlert[] {
  return alerts.filter((a) => !dismissed.has(a.id));
}

export function countBySeverity(alerts: PlatformAlert[]) {
  return {
    total: alerts.length,
    critical: alerts.filter((a) => a.severity === "critical").length,
    warning: alerts.filter((a) => a.severity === "warning").length,
    info: alerts.filter((a) => a.severity === "info").length,
  };
}
