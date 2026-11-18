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


def operating_mode() -> str:
    """``KICAD_MCP_OPERATING_MODE`` as src/tools/operating-mode.ts reads it.

    Unset or empty: ``write``; ``-``, ``_``, blanks and case are ignored; an
    unknown value fails closed to ``readonly``.
    """
    raw = os.environ.get("KICAD_MCP_OPERATING_MODE", "").strip()
    if not raw:
        return "write"
    value = raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    return value if value in ("write", "readonly", "manufacturing") else "readonly"


def report_dir() -> Path:
    """Where generated reports go when the design folder must stay untouched.

    ``<mcp_home()>/reports``; created on demand by the caller.
    """
    return mcp_home() / "reports"


def design_output_file(board_file: str, suffix: str) -> Path:
    """Where a tool writes a generated file about a board (report, preview).

    In write mode ``<board dir>/<board><suffix>``, as the tools always did. In
    readonly and manufacturing mode a session must not change the design
    folder, so the file goes to ``report_dir()``, named after the board plus a
    short hash of its full path (two boards of the same name do not overwrite
    each other).
    """
    import hashlib

    board = Path(board_file)
    if operating_mode() == "write":
        return board.parent / f"{board.stem}{suffix}"
    digest = hashlib.sha256(str(board.resolve()).encode("utf-8")).hexdigest()[:12]
    return report_dir() / f"{board.stem}-{digest}{suffix}"


def drc_violations_file(board_file: str) -> Path:
    """The JSON file run_drc writes its full violation list to (design_output_file)."""
    return design_output_file(board_file, "_drc_violations.json")


def confine_report_path(requested: str) -> "tuple[str, str | None]":
    """A caller-given output path, kept inside report_dir() unless in write mode.

    Returns (path, note). In write mode the path is used as given. In readonly
    and manufacturing mode a path outside ``report_dir()`` (it could name the
    board itself) is replaced by ``report_dir()/<its file name>``, and the note
    says so.
    """
    path = Path(requested).expanduser().resolve()
    if operating_mode() == "write":
        return str(path), None
    reports = report_dir().resolve()
    if path == reports or reports in path.parents:
        return str(path), None
    confined = reports / path.name
    return str(confined), (
        f"{operating_mode()} mode: the report was written to {confined} instead of "
        f"{requested}, because this mode does not write outside {reports}"
    )
