import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
    "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
    {
        variants: {
            variant: {
                neutral: "border-border bg-surface-2 text-muted",
                success: "border-transparent bg-success/15 text-success",
                warning: "border-transparent bg-warning/15 text-warning",
                danger: "border-transparent bg-danger/15 text-danger",
                info: "border-transparent bg-accent/15 text-accent",
            },
        },
        defaultVariants: { variant: "neutral" },
    },
);

export interface BadgeProps
    extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

/**
 * Бейдж состояния.
 *
 * @param props Свойства: вариант оформления.
 * @returns Бейдж.
 */
export function Badge({ className, variant, ...props }: BadgeProps) {
    return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
