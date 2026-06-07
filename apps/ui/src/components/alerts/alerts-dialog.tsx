"use client";

import Link from "next/link";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { PlatformAlert } from "@/lib/api";
import { countBySeverity } from "@/lib/alert-dismiss";
import { AlertListItem } from "./alert-list";

interface AlertsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  alerts: PlatformAlert[];
  onDismiss: (id: string) => void;
  onDismissAll: () => void;
}

function summaryLabel(counts: ReturnType<typeof countBySeverity>): string {
  const parts: string[] = [];
  if (counts.critical > 0) {
    parts.push(`${counts.critical} critical`);
  }
  if (counts.warning > 0) {
    parts.push(`${counts.warning} warning`);
  }
  if (parts.length === 0 && counts.info > 0) {
    parts.push(`${counts.info} info`);
  }
  return parts.join(", ");
}

export function AlertsDialog({
  open,
  onOpenChange,
  alerts,
  onDismiss,
  onDismissAll,
}: AlertsDialogProps) {
  const actionable = alerts.filter((a) => a.severity !== "info");
  const display = actionable.length > 0 ? actionable : alerts;
  const counts = countBySeverity(display);
  const preview = display.slice(0, 8);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg p-0 gap-0">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-foreground" />
            {counts.total} alert{counts.total !== 1 ? "s" : ""} need attention
          </DialogTitle>
          <DialogDescription>
            {summaryLabel(counts)}
            {display.length > preview.length
              ? ` — showing ${preview.length} of ${display.length}`
              : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 py-2 max-h-[min(360px,50vh)] overflow-y-auto space-y-2">
          {preview.map((alert) => (
            <AlertListItem key={alert.id} alert={alert} onDismiss={onDismiss} compact />
          ))}
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2 sm:justify-between">
          <Button variant="ghost" size="sm" onClick={onDismissAll} className="text-muted-foreground">
            Dismiss all
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button size="sm" asChild>
              <Link href="/alerts" onClick={() => onOpenChange(false)}>
                View all alerts
              </Link>
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
