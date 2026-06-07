"use client";

/**
 * Dashboard summary card — links to the full /alerts page.
 */

import Link from "next/link";
import { AlertTriangle, Bell, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useGlobalAlerts } from "@/components/alerts/global-alerts-provider";
import { usePlatformAlerts } from "@/hooks/use-platform-alerts";
import { countBySeverity } from "@/lib/alert-dismiss";

export function AlertsPanel() {
  const { isPending, isError } = usePlatformAlerts();
  const { visibleAlerts, actionableCount, openDialog } = useGlobalAlerts();
  const counts = countBySeverity(visibleAlerts);

  return (
    <Card className={counts.critical > 0 ? "border-destructive/40" : undefined}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <Bell className="h-4 w-4" />
          Alerts
          {counts.total > 0 && (
            <Badge variant="secondary" className="text-[10px] h-5">
              {counts.total}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>Failed migrations and platform warnings</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isPending && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        )}

        {isError && (
          <p className="text-sm text-destructive">Could not load alerts</p>
        )}

        {!isPending && !isError && counts.total === 0 && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            All clear
          </div>
        )}

        {!isPending && counts.total > 0 && (
          <div className="flex flex-wrap gap-3 text-sm">
            {counts.critical > 0 && (
              <span className="inline-flex items-center gap-1.5 text-destructive">
                <XCircle className="h-4 w-4" />
                {counts.critical} critical
              </span>
            )}
            {counts.warning > 0 && (
              <span className="inline-flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-4 w-4" />
                {counts.warning} warning
              </span>
            )}
            {counts.info > 0 && (
              <span className="text-muted-foreground">{counts.info} info</span>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="default" className="text-xs h-8" asChild>
            <Link href="/alerts">View all alerts</Link>
          </Button>
          {actionableCount > 0 && (
            <Button size="sm" variant="outline" className="text-xs h-8" onClick={openDialog}>
              Quick summary
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
