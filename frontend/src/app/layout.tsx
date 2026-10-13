import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";
import { TopNav } from "@/features/shell/top-nav";
import "./globals.css";

export const metadata: Metadata = {
    title: "Дом — пульт инженера",
    description: "Состояние дома, автоматика и журнал платформы умного дома",
};

export const viewport: Viewport = {
    width: "device-width",
    initialScale: 1,
    themeColor: "#0b0f17",
};

/**
 * Корневая оболочка: единый стиль и навигация для всех разделов (FR-002).
 *
 * @param props Дочерние страницы.
 * @returns HTML-каркас.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
    return (
        <html lang="ru">
            <body className="min-h-dvh">
                <Providers>
                    <a
                        href="#main"
                        className="focus:bg-surface focus:text-foreground sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:px-3 focus:py-2"
                    >
                        Перейти к содержимому
                    </a>
                    <TopNav />
                    <main id="main" className="mx-auto max-w-6xl px-4 py-6">
                        {children}
                    </main>
                </Providers>
            </body>
        </html>
    );
}
