/**
 * PhaseG-H1: capability/version handshake test placeholder.
 * Schema truth is protocol/schema.json; generated types are consumed, not authored.
 * Full error-code projection is PhaseG-H2.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "bun:test";
import type { InitializeRequest } from "./generated/types.ts";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

describe("PhaseG-H1 handshake placeholder", () => {
  test("generated InitializeRequest consumes frozen schema 1.1.0", () => {
    const schema = JSON.parse(
      readFileSync(join(repoRoot, "protocol", "schema.json"), "utf8"),
    ) as { protocol_version?: string };
    expect(schema.protocol_version).toBe("1.1.0");

    const init: InitializeRequest = {
      method: "initialize",
      client_name: "rxycode-desktop",
      client_version: "1.3.0",
      protocol_version: schema.protocol_version ?? "",
      capabilities: {},
    };
    expect(init.method).toBe("initialize");
    expect(init.protocol_version).toBe("1.1.0");
  });

  test("undeclared capability must not be treated as enabled", () => {
    const capabilities: Record<string, unknown> = { threads: true };
    const declared = (name: string): boolean => capabilities[name] === true;
    expect(declared("threads")).toBe(true);
    expect(declared("auto_review")).toBe(false);
    expect(declared("multi_agent")).toBe(false);
  });
});
