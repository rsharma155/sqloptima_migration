"use client";

/**
 * Module: nav.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  LayoutDashboard,
  Database,
  Repeat,
  GitBranch,
  GitCompare,
  Code,
  Settings,
  ChevronLeft,
  ChevronRight,
  Layers,
  LogIn,
  LogOut,
  FolderOpen,
  ShieldCheck,
  FileText,
  SlidersHorizontal,
  Bell,
} from "lucide-react";
import { useState, useEffect } from "react";
import { logout, getToken, getAuthUsername } from "@/lib/api";
import { canAccessAdminSettingsPages } from "@/lib/auth-role";
import { toast } from "sonner";
import { LoginModal } from "@/components/auth/login-modal";
import { useGlobalAlerts } from "@/components/alerts/global-alerts-provider";

// ---------------------------------------------------------------------------
// Nav structure — grouped into sections for scannability
// ---------------------------------------------------------------------------

const navSections = [
  {
    label: "Core Workflow",
    links: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/alerts", label: "Alerts", icon: Bell },
      { href: "/projects", label: "Projects", icon: FolderOpen },
      { href: "/assessment", label: "Assessment", icon: ShieldCheck },
      { href: "/migrations", label: "Migrations", icon: Database },
      { href: "/programs", label: "Programs", icon: Layers },
      { href: "/replication", label: "Replication", icon: Repeat },
    ],
  },
  {
    label: "Analysis & Tools",
    links: [
      { href: "/comparison", label: "Comparison", icon: GitCompare },
      { href: "/objects", label: "Objects", icon: GitBranch },
      { href: "/sql", label: "SQL Converter", icon: Code },
      { href: "/reports", label: "Reports", icon: FileText },
    ],
  },
  {
    label: "Admin",
    links: [
      { href: "/admin", label: "Admin", icon: SlidersHorizontal },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

// ---------------------------------------------------------------------------
// Nav component
// ---------------------------------------------------------------------------

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [authUsername, setAuthUsername] = useState<string | null>(null);
  const { actionableCount, criticalCount } = useGlobalAlerts();

  const [showAdminNav, setShowAdminNav] = useState(true);

  useEffect(() => {
    setIsLoggedIn(!!getToken());
    setAuthUsername(getAuthUsername());
    setShowAdminNav(canAccessAdminSettingsPages());
  }, []);

  const handleLogout = () => {
    logout();
    setIsLoggedIn(false);
    setAuthUsername(null);
    toast.success("Logged out");
    router.replace("/login");
  };

  const userInitial = authUsername?.trim().charAt(0).toUpperCase() || "?";

  function NavLink({
    href,
    label,
    icon: Icon,
    badge,
    badgeCritical,
  }: {
    href: string;
    label: string;
    icon: React.ElementType;
    badge?: number;
    badgeCritical?: boolean;
  }) {
    const isActive =
      pathname === href || (href !== "/" && pathname.startsWith(href));

    const inner = (
      <Link href={href}>
        <Button
          variant="ghost"
          className={cn(
            "w-full justify-start gap-3 text-sm font-normal rounded-md",
            "text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent",
            collapsed ? "justify-center px-0 h-9 w-9" : "px-3",
            isActive && [
              "bg-sidebar-primary/20",
              "!text-sidebar-primary",
              "font-medium",
              "hover:bg-sidebar-primary/25",
              "hover:!text-sidebar-primary",
              !collapsed && "border-l-2 border-sidebar-primary pl-[10px]",
            ],
          )}
        >
          <Icon className="h-4 w-4 shrink-0" />
          {!collapsed && <span className="flex-1 text-left">{label}</span>}
          {!collapsed && badge != null && badge > 0 && (
            <span
              className={cn(
                "ml-auto flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold",
                badgeCritical
                  ? "bg-destructive text-destructive-foreground"
                  : "bg-amber-500 text-white dark:bg-amber-600",
              )}
            >
              {badge > 9 ? "9+" : badge}
            </span>
          )}
        </Button>
      </Link>
    );

    if (collapsed) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>{inner}</TooltipTrigger>
          <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
      );
    }
    return inner;
  }

  return (
    <TooltipProvider delayDuration={150}>
      <aside
        className={cn(
          "relative flex flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-all duration-300",
          collapsed ? "w-16" : "w-64",
        )}
      >
        {/* ── Header: logo + collapse toggle ── */}
        <div className="flex h-14 items-center border-b border-sidebar-border px-3 gap-2">
          <Layers className="h-6 w-6 shrink-0 text-sidebar-primary" />
          {!collapsed && (
            <span className="flex-1 text-sm font-semibold tracking-tight truncate text-sidebar-foreground">
              SQL Optima Migration
            </span>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
              "text-sidebar-foreground/50 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring",
            )}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </button>
        </div>

        {/* ── Nav links ── */}
        <nav className="flex-1 overflow-y-auto p-2">
          {navSections
            .filter((section) => section.label !== "Admin" || showAdminNav)
            .map((section, si) => (
              <div key={section.label} className={cn(si > 0 && "mt-1")}>
                {!collapsed && (
                  <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/35 select-none">
                    {section.label}
                  </p>
                )}
                {collapsed && si > 0 && (
                  <div className="mx-auto my-2 h-px w-6 bg-sidebar-border" />
                )}
                <div className="space-y-0.5">
                  {section.links.map((link) => (
                    <NavLink
                      key={link.href}
                      {...link}
                      badge={link.href === "/alerts" ? actionableCount : undefined}
                      badgeCritical={link.href === "/alerts" && criticalCount > 0}
                    />
                  ))}
                </div>
              </div>
            ))}
        </nav>

        {/* ── Footer: auth (pb-12 keeps clear of Next.js dev indicator) ── */}
        <div className="border-t border-sidebar-border p-2 pb-12 space-y-1">
          {isLoggedIn ? (
            collapsed ? (
              <div className="flex flex-col items-center gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className="flex h-9 w-9 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold text-sidebar-accent-foreground"
                      aria-label={authUsername ? `Signed in as ${authUsername}` : "Signed in"}
                    >
                      {userInitial}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="right">
                    {authUsername ? `Signed in as ${authUsername}` : "Signed in"}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Logout"
                      className="h-9 w-9 justify-center px-0 text-destructive hover:text-destructive hover:bg-destructive/10"
                      onClick={handleLogout}
                    >
                      <LogOut className="h-4 w-4 shrink-0" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="right">Logout</TooltipContent>
                </Tooltip>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 px-2 py-1 min-w-0">
                  <div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold text-sidebar-accent-foreground"
                    aria-hidden="true"
                  >
                    {userInitial}
                  </div>
                  <span className="flex-1 truncate text-xs font-medium text-sidebar-foreground">
                    {authUsername || "Signed in"}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start gap-3 text-destructive hover:text-destructive hover:bg-destructive/10"
                  onClick={handleLogout}
                >
                  <LogOut className="h-4 w-4 shrink-0" />
                  <span className="text-xs font-medium">Logout</span>
                </Button>
              </>
            )
          ) : collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Login"
                  className="w-full justify-center px-0 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                  onClick={() => setShowLogin(true)}
                >
                  <LogIn className="h-4 w-4 shrink-0" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Login</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-3 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent"
              onClick={() => setShowLogin(true)}
            >
              <LogIn className="h-4 w-4 shrink-0" />
              <span className="text-xs">Login</span>
            </Button>
          )}
        </div>

        {/* ── Login modal (extracted component) ── */}
        {showLogin && (
          <LoginModal
            onClose={() => setShowLogin(false)}
            onSuccess={() => {
              setIsLoggedIn(true);
              setAuthUsername(getAuthUsername());
              setShowAdminNav(canAccessAdminSettingsPages());
              setShowLogin(false);
            }}
          />
        )}
      </aside>
    </TooltipProvider>
  );
}
