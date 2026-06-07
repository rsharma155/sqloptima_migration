/**
 * Module: components/shared/empty-state.tsx
 * Purpose: Centred empty-state placeholder with icon, title, description, and
 *          an optional action button.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { type LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-16">
        <Icon className="h-14 w-14 text-muted-foreground/30 mb-4" />
        <h2 className="text-lg font-semibold text-muted-foreground mb-1">{title}</h2>
        {description && (
          <p className="text-sm text-muted-foreground/70 text-center max-w-md mb-6">
            {description}
          </p>
        )}
        {actionLabel && onAction && (
          <Button onClick={onAction}>{actionLabel}</Button>
        )}
      </CardContent>
    </Card>
  );
}
