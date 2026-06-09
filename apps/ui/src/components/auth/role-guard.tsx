"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { getToken } from "@/lib/api";
import { canAccessAdminSettingsPages } from "@/lib/auth-role";

interface RequireNonViewerProps {
  children: React.ReactNode;
}

/**
 * Blocks viewer accounts from Settings and Admin routes.
 * Operators and admins pass through.
 */
export function RequireNonViewer({ children }: RequireNonViewerProps) {
  const router = useRouter();
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      setAllowed(false);
      return;
    }
    if (!canAccessAdminSettingsPages()) {
      toast.error("Access denied — viewer accounts cannot open Settings or Admin");
      router.replace("/");
      setAllowed(false);
      return;
    }
    setAllowed(true);
  }, [router]);

  if (allowed !== true) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Checking access" />
      </div>
    );
  }

  return <>{children}</>;
}
