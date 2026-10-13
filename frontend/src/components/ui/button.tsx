import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
    "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:pointer-events-none disabled:opacity-50",
    {
        variants: {
            variant: {
                default: "bg-accent text-accent-foreground hover:bg-accent/90",
                secondary: "bg-surface-2 text-foreground hover:bg-surface-2/80",
                outline: "border border-border bg-transparent hover:bg-surface-2",
                ghost: "hover:bg-surface-2",
                danger: "bg-danger text-background hover:bg-danger/90",
            },
            size: {
                default: "h-9 px-4 py-2",
                sm: "h-8 px-3",
                icon: "size-9",
            },
        },
        defaultVariants: {
            variant: "default",
            size: "default",
        },
    },
);

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
    asChild?: boolean;
}

/**
 * Кнопка интерфейса.
 *
 * @param props Свойства кнопки: вариант, размер, `asChild`.
 * @returns Кнопка либо обёртка над дочерним элементом.
 */
export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
    const Component = asChild ? Slot : "button";
    return <Component className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { buttonVariants };
