import { cn } from "@/lib/utils";

/**
 * Заглушка загрузки.
 *
 * @param props Свойства: классы.
 * @returns Пульсирующий блок.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
    return <div className={cn("bg-surface-2 animate-pulse rounded-md", className)} {...props} />;
}
