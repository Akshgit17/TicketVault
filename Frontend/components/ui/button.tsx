import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground hover:bg-amber-400 active:bg-amber-600",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-zinc-700",
        outline:
          "border border-border bg-transparent text-foreground hover:border-zinc-600 hover:bg-secondary/40",
        ghost:
          "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-red-600",
        link:
          "text-primary underline-offset-4 hover:underline p-0 h-auto",
      },
      size: {
        sm:   "h-8  px-3 text-xs [&_svg]:size-3.5",
        default: "h-10 px-4 text-sm [&_svg]:size-4",
        lg:   "h-12 px-6 text-base [&_svg]:size-4",
        icon: "h-10 w-10 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <>
            <Loader2 className="animate-spin" />
            {children}
          </>
        ) : (
          children
        )}
      </Comp>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
