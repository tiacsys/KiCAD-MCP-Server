"""Where the server keeps its own files: logs and the Freerouting JAR.

Both used to sit under a fixed ``~/.kicad-mcp`` that no setting could move. A
setup that keeps every tool's state outside the home directory (a sandbox, a
CI runner, a workspace with its own KiCad configuration) had no way to stop the
server from writing there on every start.

- ``KICAD_MCP_HOME``: the server's home folder. Default ``~/.kicad-mcp``.
- ``KICAD_MCP_LOG_DIR``: the log folder. Default ``$KICAD_MCP_HOME/logs``.

``src/logger.ts`` resolves the same two variables the same way, so the Node
server and the Python worker always log into one folder.

This module imports only the standard library: ``kicad_interface`` calls it
while it sets up logging, before anything else is imported.
"""

import os
from pathlib import Path

MCP_HOME_ENV = "KICAD_MCP_HOME"
MCP_LOG_DIR_ENV = "KICAD_MCP_LOG_DIR"


def _env_path(name: str) -> "Path | None":
    """The path in environment variable *name*, or None when it is unset or empty."""
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def mcp_home() -> Path:
    """The server's home folder: ``$KICAD_MCP_HOME``, else ``~/.kicad-mcp``."""
    return _env_path(MCP_HOME_ENV) or Path.home() / ".kicad-mcp"


def mcp_log_dir() -> Path:
    """The log folder: ``$KICAD_MCP_LOG_DIR``, else ``<mcp_home()>/logs``."""
    return _env_path(MCP_LOG_DIR_ENV) or mcp_home() / "logs"


def default_freerouting_jar() -> Path:
    """Where autoroute looks for Freerouting when no path is given.

    ``$FREEROUTING_JAR``, else ``<mcp_home()>/freerouting.jar``.
    """
    return _env_path("FREEROUTING_JAR") or mcp_home() / "freerouting.jar"
