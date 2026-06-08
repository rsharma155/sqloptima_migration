"use client";

/**
 * Module: dialog.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { type ReactNode } from "react";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

export function Dialog({ open, onOpenChange, children }: DialogProps) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={() => onOpenChange(false)}
    >
      <div onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

export function DialogContent({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`bg-background rounded-lg border shadow-lg w-full mx-4 max-h-[90vh] overflow-y-auto ${className}`}
      role="dialog"
      aria-modal="true"
    >
      {children}
    </div>
  );
}

export function DialogHeader({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`px-6 py-4 border-b space-y-1 ${className}`}>
      {children}
    </div>
  );
}

export function DialogTitle({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <h2 className={`text-lg font-semibold ${className}`.trim()}>{children}</h2>;
}

export function DialogDescription({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <p className={`text-sm text-muted-foreground ${className}`.trim()}>{children}</p>;
}

export function DialogFooter({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-center justify-end gap-2 px-6 py-4 border-t ${className}`}>
      {children}
    </div>
  );
}
