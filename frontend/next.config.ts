import type { NextConfig } from "next";

/**
 * Статический экспорт: интерфейс раздаётся тем же процессом FastAPI.
 *
 * `trailingSlash` заставляет Next писать `route/index.html` — так раздача
 * статики (`StaticFiles(html=True)`) отдаёт страницу и по адресу со слэшем,
 * и без него, а глубокие ссылки работают без серверного роутинга.
 */
const nextConfig: NextConfig = {
    output: "export",
    trailingSlash: true,
    images: { unoptimized: true },
    turbopack: {
        rules: {
            "*.css": {
                loaders: ["@tailwindcss/turbopack"],
                as: "*.css",
            },
        },
    },
};

export default nextConfig;
