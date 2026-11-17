import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { logger, resolveLogDir, resolveMcpHome } from "../src/logger.js";

// The Node logger's folder follows KICAD_MCP_LOG_DIR, else KICAD_MCP_HOME/logs,
// else ~/.kicad-mcp/logs — the same rule as python/utils/mcp_paths.py
// (tests/test_mcp_home_paths.py), so both processes log into one folder.
describe("log folder", () => {
  const saved = { ...process.env };
  const temps: string[] = [];

  afterEach(() => {
    process.env = { ...saved };
    for (const dir of temps.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  function temp(): string {
    const dir = mkdtempSync(join(tmpdir(), "kicad-mcp-logger-"));
    temps.push(dir);
    return dir;
  }

  it("defaults to ~/.kicad-mcp/logs", () => {
    expect(resolveMcpHome({})).toBe(join(homedir(), ".kicad-mcp"));
    expect(resolveLogDir({})).toBe(join(homedir(), ".kicad-mcp", "logs"));
  });

  it("treats empty values as unset", () => {
    expect(resolveLogDir({ KICAD_MCP_HOME: "", KICAD_MCP_LOG_DIR: " " })).toBe(
      join(homedir(), ".kicad-mcp", "logs"),
    );
  });

  it("puts logs under KICAD_MCP_HOME", () => {
    expect(resolveLogDir({ KICAD_MCP_HOME: "/ws/.xdmod/kicad-mcp" })).toBe(
      "/ws/.xdmod/kicad-mcp/logs",
    );
  });

  it("lets KICAD_MCP_LOG_DIR win over KICAD_MCP_HOME", () => {
    expect(resolveLogDir({ KICAD_MCP_HOME: "/a", KICAD_MCP_LOG_DIR: "/b/logs" })).toBe("/b/logs");
  });

  it("expands a leading ~", () => {
    expect(resolveMcpHome({ KICAD_MCP_HOME: "~/mcp" })).toBe(join(homedir(), "mcp"));
  });

  it("writes the log file into the folder the environment names", () => {
    const dir = join(temp(), "logs");
    process.env.KICAD_MCP_LOG_DIR = dir;
    logger.error("logger-paths test message");
    expect(logger.getLogDir()).toBe(dir);
    expect(existsSync(dir)).toBe(true);
    expect(readdirSync(dir).some((name) => name.startsWith("kicad-mcp-"))).toBe(true);
  });
});
