"""Where the server keeps its own files: logs and the Freerouting JAR.

Both used to sit under a fixed ``~/.kicad-mcp`` that no setting could move. A
setup that keeps every tool's state outside the home directory (a sandbox, a
CI runner, a workspace with its own KiCad configuration) had no way to stop the
server from writing there on every start.

- ``KICAD_MCP_HOME``: the server's home folder. Default ``~/.kicad-mcp``.
- ``KICAD_MCP_LOG_DIR``: the log folder. Default ``$KICAD_MCP_HOME/logs``.

``src/logger.ts`` resolves the same two variables the same way, so the Node
server and the Python worker always log into one folder.

In strict mode (``KICAD_MCP_STRICT_PATHS=1``) neither has a default below the
home directory; see utils/user_dirs.py.

This module imports only the standard library (and utils.user_dirs, which does
too): ``kicad_interface`` calls it while it sets up logging, before anything
else is imported.
"""

import os
from pathlib import Path

MCP_HOME_ENV = "KICAD_MCP_HOME"
MCP_LOG_DIR_ENV = "KICAD_MCP_LOG_DIR"


def _env_path(name: str) -> "Path | None":
    """The path in environment variable *name*, or None when it is unset or empty."""
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


class StrictPathError(OSError):
    """KICAD_MCP_STRICT_PATHS is set and the folder asked for is not configured."""


def mcp_home() -> Path:
    """The server's home folder: ``$KICAD_MCP_HOME``, else ``~/.kicad-mcp``.

    In strict mode (``KICAD_MCP_STRICT_PATHS=1``, utils/user_dirs.py) there is no
    default: an unset KICAD_MCP_HOME raises StrictPathError.
    """
    configured = _env_path(MCP_HOME_ENV)
    if configured is not None:
        return configured
    if _strict():
        raise StrictPathError("KICAD_MCP_STRICT_PATHS is set but KICAD_MCP_HOME is not")
    return Path.home() / ".kicad-mcp"


def mcp_log_dir() -> Path:
    """The log folder: ``$KICAD_MCP_LOG_DIR``, else ``<mcp_home()>/logs``."""
    return _env_path(MCP_LOG_DIR_ENV) or mcp_home() / "logs"


def _strict() -> bool:
    from utils.user_dirs import strict_paths

    return strict_paths()


def default_freerouting_jar() -> Path:
    """Where autoroute looks for Freerouting when no path is given.

    ``$FREEROUTING_JAR``, else ``<mcp_home()>/freerouting.jar``.
    """
    return _env_path("FREEROUTING_JAR") or mcp_home() / "freerouting.jar"
