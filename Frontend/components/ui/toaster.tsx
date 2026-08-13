"use client";

import { Toaster as Sonner } from "sonner";

/**
 * Styled through the token set rather than sonner's defaults so toasts match
 * the rest of the surface treatment.
 */
export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "group flex items-center gap-3 rounded-lg border border-border bg-card p-4 text-sm text-foreground shadow-xl",
          description: "text-muted-foreground",
          actionButton: "bg-primary text-primary-foreground rounded-md px-2 py-1 text-xs",
          cancelButton: "bg-secondary text-secondary-foreground rounded-md px-2 py-1 text-xs",
          error: "border-destructive/40",
          success: "border-success/40",
        },
      }}
    />
  );
}
