"use client";

import { usePathname } from "next/navigation";
import { Nav } from "@/components/dashboard/nav";

const HIDDEN_NAV_PATHS = ["/setup", "/login"];

export function ConditionalNav() {
  const pathname = usePathname();
  if (HIDDEN_NAV_PATHS.includes(pathname)) return null;
  return <Nav />;
}
