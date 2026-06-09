"use client";

import { RequireNonViewer } from "@/components/auth/role-guard";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <RequireNonViewer>{children}</RequireNonViewer>;
}
