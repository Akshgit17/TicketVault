import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em] transition-colors [&_svg]:size-3",
  {
    variants: {
      variant: {
        default:     "border-transparent bg-primary/15 text-primary",
        neutral:     "border-border bg-secondary/50 text-muted-foreground",
        success:     "border-transparent bg-success/15 text-success",
        destructive: "border-transparent bg-destructive/15 text-destructive",
        outline:     "border-border text-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
