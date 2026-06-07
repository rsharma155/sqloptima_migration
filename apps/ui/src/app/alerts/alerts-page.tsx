"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Loader2,
  Mail,
  RefreshCw,
  Webhook,
  XCircle,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/shared/page-header";
import { AlertListItem } from "@/components/alerts/alert-list";
import { useGlobalAlerts } from "@/components/alerts/global-alerts-provider";
import { usePlatformAlerts } from "@/hooks/use-platform-alerts";
import { getAlertConfig } from "@/lib/api";
import { countBySeverity } from "@/lib/alert-dismiss";
import { cn } from "@/lib/utils";

type FilterTab = "all" | "critical" | "warning" | "info";

export default function AlertsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<FilterTab>("all");
  const { data, isPending, isError, dataUpdatedAt } = usePlatformAlerts();
  const { visibleAlerts, dismiss, dismissAll, openDialog } = useGlobalAlerts();

  const { data: config } = useQuery({
    queryKey: ["alert-config"],
    queryFn: getAlertConfig,
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    if (tab === "all") return visibleAlerts;
    return visibleAlerts.filter((a) => a.severity === tab);
  }, [visibleAlerts, tab]);

  const counts = countBySeverity(visibleAlerts);

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Alerts"
        description="Consolidated view of failed migrations, setup issues, and platform warnings"
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => qc.invalidateQueries({ queryKey: ["platform-alerts"] })}
        >
          <RefreshCw className="h-4 w-4 mr-1" /> Refresh
        </Button>
        {visibleAlerts.length > 0 && (
          <Button variant="outline" size="sm" onClick={dismissAll}>
            Dismiss all
          </Button>
        )}
      </PageHeader>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Critical</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-destructive">{counts.critical}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Warning</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">
              {counts.warning}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Info</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{counts.info}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Last checked</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-mono text-foreground">
              {dataUpdatedAt
                ? new Date(dataUpdatedAt).toLocaleTimeString()
                : "—"}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Notification channels */}
      {config && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">External notifications</CardTitle>
            <CardDescription>
              Webhook and email alerts for overnight migration failures — configure in{" "}
              <Link href="/settings" className="underline text-primary">
                Settings
              </Link>
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <span
              className={cn(
                "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
                config.webhook_configured
                  ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-border text-muted-foreground",
              )}
            >
              <Webhook className="h-4 w-4" />
              Webhook {config.webhook_configured ? "configured" : "not set"}
            </span>
            <span
              className={cn(
                "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
                config.email_configured
                  ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                  : "border-border text-muted-foreground",
              )}
            >
              <Mail className="h-4 w-4" />
              Email {config.email_configured ? `→ ${config.email_to}` : "not set"}
            </span>
          </CardContent>
        </Card>
      )}

      {/* Alert list */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <Bell className="h-4 w-4" />
                Active alerts
                {counts.total > 0 && (
                  <Badge variant="secondary" className="text-[10px]">
                    {counts.total}
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>
                Dismissed alerts are hidden for this browser session
              </CardDescription>
            </div>
            <Tabs value={tab} onValueChange={(v) => setTab(v as FilterTab)}>
              <TabsList className="h-8">
                <TabsTrigger value="all" className="text-xs h-7">
                  All ({counts.total})
                </TabsTrigger>
                <TabsTrigger value="critical" className="text-xs h-7">
                  <XCircle className="h-3 w-3 mr-1 text-destructive" />
                  {counts.critical}
                </TabsTrigger>
                <TabsTrigger value="warning" className="text-xs h-7">
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  {counts.warning}
                </TabsTrigger>
                <TabsTrigger value="info" className="text-xs h-7">
                  {counts.info}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </CardHeader>
        <CardContent>
          {isPending && (
            <div className="flex items-center justify-center py-16 text-muted-foreground gap-2">
              <Loader2 className="h-5 w-5 animate-spin" /> Loading alerts…
            </div>
          )}

          {isError && (
            <p className="text-sm text-destructive py-8 text-center">
              Could not load alerts — verify the API is running.
            </p>
          )}

          {!isPending && !isError && filtered.length === 0 && (
            <div className="flex flex-col items-center py-16 gap-3 text-muted-foreground">
              <CheckCircle2 className="h-12 w-12 text-emerald-500/70" />
              <p className="text-lg font-medium text-foreground">All clear</p>
              <p className="text-sm">
                {tab === "all"
                  ? "No active alerts for this session"
                  : `No ${tab} alerts`}
              </p>
              {data && (data.alerts?.length ?? 0) > visibleAlerts.length && (
                <p className="text-xs">
                  Some alerts were dismissed — refresh the page or clear session storage to see them again.
                </p>
              )}
            </div>
          )}

          {!isPending && filtered.length > 0 && (
            <div className="space-y-2">
              {filtered.map((alert) => (
                <AlertListItem key={alert.id} alert={alert} onDismiss={dismiss} />
              ))}
            </div>
          )}

          {!isPending && visibleAlerts.length > 0 && (
            <div className="mt-4 pt-4 border-t flex justify-end">
              <Button variant="ghost" size="sm" onClick={openDialog}>
                Open summary popup
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
