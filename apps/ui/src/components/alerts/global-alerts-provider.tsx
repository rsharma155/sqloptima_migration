"use client";

/**
 * Global alerts — auto popup on load (once per session) + shared dialog state.
 * No page-header banner; use nav badge and /alerts page for full list.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePlatformAlerts } from "@/hooks/use-platform-alerts";
import type { PlatformAlert } from "@/lib/api";
import {
  filterVisibleAlerts,
  loadDismissedAlerts,
  markAutoPopupShown,
  saveDismissedAlerts,
  wasAutoPopupShown,
} from "@/lib/alert-dismiss";
import { AlertsDialog } from "./alerts-dialog";

interface AlertsContextValue {
  visibleAlerts: PlatformAlert[];
  actionableCount: number;
  criticalCount: number;
  dialogOpen: boolean;
  openDialog: () => void;
  closeDialog: () => void;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

const AlertsContext = createContext<AlertsContextValue | null>(null);

export function GlobalAlertsProvider({ children }: { children: ReactNode }) {
  const { data } = usePlatformAlerts();
  const [dismissed, setDismissed] = useState<Set<string>>(() => loadDismissedAlerts());
  const [dialogOpen, setDialogOpen] = useState(false);

  const allAlerts = data?.alerts ?? [];
  const visibleAlerts = useMemo(
    () => filterVisibleAlerts(allAlerts, dismissed),
    [allAlerts, dismissed],
  );
  const actionable = visibleAlerts.filter((a) => a.severity !== "info");
  const criticalCount = actionable.filter((a) => a.severity === "critical").length;
  const actionableCount = actionable.length;

  const dismiss = useCallback((id: string) => {
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(id);
      saveDismissedAlerts(next);
      return next;
    });
  }, []);

  const dismissAll = useCallback(() => {
    setDismissed((prev) => {
      const next = new Set(prev);
      visibleAlerts.forEach((a) => next.add(a.id));
      saveDismissedAlerts(next);
      return next;
    });
  }, [visibleAlerts]);

  // Auto-open once per session when actionable alerts exist
  useEffect(() => {
    if (!data || actionableCount === 0 || wasAutoPopupShown()) return;
    markAutoPopupShown();
    setDialogOpen(true);
  }, [data, actionableCount]);

  const value: AlertsContextValue = {
    visibleAlerts,
    actionableCount,
    criticalCount,
    dialogOpen,
    openDialog: () => setDialogOpen(true),
    closeDialog: () => setDialogOpen(false),
    dismiss,
    dismissAll,
  };

  return (
    <AlertsContext.Provider value={value}>
      {children}
      <AlertsDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        alerts={visibleAlerts}
        onDismiss={dismiss}
        onDismissAll={() => {
          dismissAll();
          setDialogOpen(false);
        }}
      />
    </AlertsContext.Provider>
  );
}

export function useGlobalAlerts(): AlertsContextValue {
  const ctx = useContext(AlertsContext);
  if (!ctx) {
    throw new Error("useGlobalAlerts must be used within GlobalAlertsProvider");
  }
  return ctx;
}
