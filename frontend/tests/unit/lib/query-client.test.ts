import { describe, expect, it } from "vitest";

import { createQueryClient } from "@/lib/query-client";

describe("createQueryClient", () => {
    it("настраивает разумную свежесть данных", () => {
        const client = createQueryClient();

        expect(client.getDefaultOptions().queries?.staleTime).toBe(15_000);
    });
});
