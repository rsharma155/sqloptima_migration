"use client";

/**
 * Module: components/command-palette.tsx
 * Purpose: Global Cmd+K command palette — quick navigation to any page,
 *          recent migration jobs from TanStack Query cache, and quick actions.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  LayoutDashboard,
  FolderOpen,
  ShieldCheck,
  Database,
  Repeat,
  GitCompare,
  GitBranch,
  Code,
  FileText,
  Settings,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  SlidersHorizontal,
  ArrowRight,
  ArrowLeftRight,
} from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import type { MigrationResponse } from "@/lib/api";

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const NAV_ITEMS = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, section: "Core Workflow" },
  { label: "Projects", href: "/projects", icon: FolderOpen, section: "Core Workflow" },
  { label: "Assessment", href: "/assessment", icon: ShieldCheck, section: "Core Workflow" },
  { label: "Migrations", href: "/migrations", icon: Database, section: "Core Workflow" },
  { label: "Transfer", href: "/transfers", icon: ArrowLeftRight, section: "Core Workflow" },
  { label: "Replication", href: "/replication", icon: Repeat, section: "Core Workflow" },
  { label: "Comparison", href: "/comparison", icon: GitCompare, section: "Analysis & Tools" },
  { label: "Objects", href: "/objects", icon: GitBranch, section: "Analysis & Tools" },
  { label: "SQL Converter", href: "/sql", icon: Code, section: "Analysis & Tools" },
  { label: "Reports", href: "/reports", icon: FileText, section: "Analysis & Tools" },
  { label: "Settings", href: "/settings", icon: Settings, section: "Admin" },
  { label: "Admin", href: "/admin", icon: SlidersHorizontal, section: "Admin" },
];

const QUICK_ACTIONS = [
  { label: "Start New Migration", href: "/migrations", icon: ArrowRight, hint: "Opens migration wizard" },
  { label: "Start Transfer", href: "/transfers", icon: ArrowLeftRight, hint: "Cross-database bulk copy" },
  { label: "Run Assessment", href: "/assessment", icon: ShieldCheck, hint: "Assess migration readiness" },
  { label: "Convert SQL", href: "/sql", icon: Code, hint: "T-SQL → PL/pgSQL converter" },
];

function migrationStatusIcon(status: string) {
  const s = status.toUpperCase();
  if (s === "COMPLETED") return <CheckCircle2 className="text-emerald-500!" />;
  if (["FAILED", "STOPPED"].includes(s)) return <XCircle className="text-destructive!" />;
  if (["RUNNING", "IN_PROGRESS"].includes(s)) return <Play className="text-blue-500!" />;
  return <Clock className="text-amber-500!" />;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const qc = useQueryClient();

  // Cmd+K / Ctrl+K global shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const navigate = useCallback(
    (href: string) => {
      router.push(href);
      setOpen(false);
    },
    [router],
  );

  // Read cached migrations from TanStack Query — no extra network request
  const migrations =
    (qc.getQueryData<MigrationResponse[]>(["migrations"]) ?? [])
      .slice()
      .sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )
      .slice(0, 5);

  // Group nav items by section
  const sections = NAV_ITEMS.reduce<Record<string, typeof NAV_ITEMS>>(
    (acc, item) => {
      (acc[item.section] ??= []).push(item);
      return acc;
    },
    {},
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="p-0 gap-0 max-w-xl overflow-hidden shadow-2xl">
        <Command>
          <CommandInput placeholder="Search pages, jobs, actions…" autoFocus />
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>

            {/* Quick Actions */}
            <CommandGroup heading="Quick Actions">
              {QUICK_ACTIONS.map((action) => (
                <CommandItem
                  key={action.href + action.label}
                  value={action.label}
                  onSelect={() => navigate(action.href)}
                >
                  <action.icon />
                  <span>{action.label}</span>
                  <CommandShortcut>{action.hint}</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />

            {/* Navigation sections */}
            {Object.entries(sections).map(([section, items]) => (
              <CommandGroup key={section} heading={section}>
                {items.map((item) => (
                  <CommandItem
                    key={item.href}
                    value={item.label}
                    onSelect={() => navigate(item.href)}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                    <CommandShortcut className="font-mono text-[10px]">
                      {item.href}
                    </CommandShortcut>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}

            {/* Recent migration jobs from cache */}
            {migrations.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Recent Migrations">
                  {migrations.map((m) => (
                    <CommandItem
                      key={m.job_id}
                      value={`migration ${m.job_id}`}
                      onSelect={() => navigate(`/migrations/${m.job_id}`)}
                    >
                      {migrationStatusIcon(m.status)}
                      <span className="font-mono text-xs">
                        {m.job_id.slice(0, 20)}…
                      </span>
                      <CommandShortcut>
                        {m.table_count ?? 0} tables · {m.status.toLowerCase()}
                      </CommandShortcut>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>

          {/* Footer hint */}
          <div className="flex items-center gap-3 border-t px-3 py-2 text-[10px] text-muted-foreground/60 select-none">
            <span><kbd className="rounded bg-muted px-1 py-0.5 font-mono">↑↓</kbd> navigate</span>
            <span><kbd className="rounded bg-muted px-1 py-0.5 font-mono">↵</kbd> open</span>
            <span><kbd className="rounded bg-muted px-1 py-0.5 font-mono">esc</kbd> close</span>
            <span className="ml-auto">
              <kbd className="rounded bg-muted px-1 py-0.5 font-mono">⌘K</kbd> anywhere
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
