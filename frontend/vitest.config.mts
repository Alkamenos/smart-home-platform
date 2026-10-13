import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react()],
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./tests/unit/setup.ts"],
        include: ["tests/unit/**/*.test.{ts,tsx}"],
        css: false,
        coverage: {
            provider: "v8",
            include: ["src/**/*.{ts,tsx}"],
            // Примитивы UI — тонкая обёртка над Radix; их поведение проверяется E2E.
            exclude: ["src/components/ui/**", "**/*.d.ts", "src/app/**/layout.tsx"],
        },
    },
    resolve: {
        alias: {
            "@": path.resolve(import.meta.dirname, "./src"),
        },
    },
});
