import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { applyConfigLogDir } from "../src/config.js";
import { logger, resolveLogDir, resolveMcpHome, strictPaths } from "../src/logger.js";

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

  it("expands a leading ~\\ as well", () => {
    expect(resolveMcpHome({ KICAD_MCP_HOME: "~\\mcp" })).toBe(join(homedir(), "mcp"));
  });

  it("applies logDir of the config file as an absolute KICAD_MCP_LOG_DIR", () => {
    const env: NodeJS.ProcessEnv = {};
    expect(applyConfigLogDir({ logDir: "rel/logs" }, env)).toBe(resolve("rel/logs"));
    expect(env.KICAD_MCP_LOG_DIR).toBe(resolve("rel/logs"));
  });

  it("keeps a KICAD_MCP_LOG_DIR that is already set over logDir of the config file", () => {
    const env: NodeJS.ProcessEnv = { KICAD_MCP_LOG_DIR: "/env/logs" };
    expect(applyConfigLogDir({ logDir: "/config/logs" }, env)).toBe("/env/logs");
    expect(env.KICAD_MCP_LOG_DIR).toBe("/env/logs");
  });

  it("changes nothing without logDir", () => {
    const env: NodeJS.ProcessEnv = {};
    expect(applyConfigLogDir({}, env)).toBeUndefined();
    expect(env).toEqual({});
  });

  it("has no home-directory default in strict mode", () => {
    expect(strictPaths({ KICAD_MCP_STRICT_PATHS: "1" })).toBe(true);
    expect(strictPaths({ KICAD_MCP_STRICT_PATHS: "0" })).toBe(false);
    expect(resolveMcpHome({ KICAD_MCP_STRICT_PATHS: "1" })).toBeNull();
    expect(resolveLogDir({ KICAD_MCP_STRICT_PATHS: "true" })).toBeNull();
    expect(resolveLogDir({ KICAD_MCP_STRICT_PATHS: "1", KICAD_MCP_HOME: "/ws/mcp" })).toBe(
      "/ws/mcp/logs",
    );
  });

  it("logs to stderr only in strict mode without a configured folder", () => {
    const home = temp();
    process.env.HOME = home; // os.homedir() follows HOME on POSIX
    process.env.KICAD_MCP_STRICT_PATHS = "1";
    delete process.env.KICAD_MCP_HOME;
    delete process.env.KICAD_MCP_LOG_DIR;
    logger.error("logger-paths strict test message");
    expect(logger.getLogDir()).toBeNull();
    expect(readdirSync(home)).toEqual([]);
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
