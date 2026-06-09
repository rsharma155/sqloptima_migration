"use client";

import { RequireNonViewer } from "@/components/auth/role-guard";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <RequireNonViewer>{children}</RequireNonViewer>;
}
