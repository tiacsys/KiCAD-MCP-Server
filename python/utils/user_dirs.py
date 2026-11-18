"""KiCad's per-user folders, as the environment configures them, and strict mode.

KiCad itself moves its per-user folders with two variables:

- ``KICAD_CONFIG_HOME``: the configuration root (``<root>/<ver>/kicad_common.json``,
  the global library tables). When it is set, KiCad reads no other root.
- ``KICAD_DOCUMENTS_HOME``: the root of the user documents tree,
  ``<root>/kicad/<ver>/`` on Linux (``<root>/KiCad/<ver>/`` on Windows and
  macOS), which holds ``3rdparty/`` (Plugin and Content Manager), ``plugins/``,
  ``symbols/``, ``footprints/`` and ``template/``. Unset, the root is
  ``~/.local/share`` on Linux and ``~/Documents`` elsewhere.

The server used to look in the default places even when these were set, so a
setup with its own KiCad configuration (a sandbox, CI, a workspace that keeps
all tool state in one folder) still read the user's real libraries and wrote
the GUI-driver plugin into the real KiCad data folder. This module is the one
place that knows the rules; the lookups ask it.

``KICAD_MCP_STRICT_PATHS=1`` goes one step further: no lookup falls back to the
home directory (``~/Documents``, ``~/.local``, ``~/.config``, XDG defaults) or
reads another program's files (the Claude client logs). Folders the server
needs must then be configured: ``check_strict_paths()`` lists what is missing,
and the worker refuses to start when that list is not empty.

Only the standard library is imported here.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

STRICT_ENV = "KICAD_MCP_STRICT_PATHS"
DOCUMENTS_HOME_ENV = "KICAD_DOCUMENTS_HOME"
CONFIG_HOME_ENV = "KICAD_CONFIG_HOME"

_TRUE = ("1", "true", "yes", "on")


def strict_paths() -> bool:
    """True when ``KICAD_MCP_STRICT_PATHS`` is set to 1/true/yes/on."""
    return os.environ.get(STRICT_ENV, "").strip().lower() in _TRUE


def _env_dir(name: str) -> Optional[Path]:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _kicad_folder_name(platform: Optional[str] = None) -> str:
    platform = platform if platform is not None else sys.platform
    return "kicad" if platform.startswith("linux") else "KiCad"


def config_home() -> Optional[Path]:
    """``$KICAD_CONFIG_HOME``, or None when it is unset."""
    return _env_dir(CONFIG_HOME_ENV)


def documents_root(platform: Optional[str] = None) -> Optional[Path]:
    """KiCad's user documents folder without the version: ``<root>/kicad``.

    ``$KICAD_DOCUMENTS_HOME/kicad`` (``KiCad`` on Windows and macOS) when the
    variable is set. Otherwise KiCad's default, ``~/.local/share/kicad`` on Linux
    and ``~/Documents/KiCad`` elsewhere, or None in strict mode.
    """
    platform = platform if platform is not None else sys.platform
    configured = _env_dir(DOCUMENTS_HOME_ENV)
    if configured is not None:
        return configured / _kicad_folder_name(platform)
    if strict_paths():
        return None
    if platform.startswith("linux"):
        return Path.home() / ".local" / "share" / "kicad"
    return Path.home() / "Documents" / "KiCad"


def user_root(default: Path, platform: Optional[str] = None) -> Optional[Path]:
    """Map one per-user KiCad root below ``$HOME`` to where it is in this setup.

    *default* is a root a lookup has always used (``~/.local/share/kicad`` or
    ``~/Documents/KiCad``). With ``KICAD_DOCUMENTS_HOME`` set, every such root is
    ``documents_root()``; in strict mode without it, None (skip the entry);
    otherwise *default* unchanged. Each lookup keeps its own list and order and
    maps its roots through this, so a default setup searches exactly the
    folders it always did, in the same order.
    """
    if _env_dir(DOCUMENTS_HOME_ENV) is not None:
        return documents_root(platform)
    if strict_paths():
        return None
    return default


def map_user_paths(defaults: List[Tuple[Path, str]], platform: Optional[str] = None) -> List[Path]:
    """``[(default root, relative part), ...]`` -> paths, through user_root().

    Entries whose root is skipped are left out; duplicates (two defaults that
    map to the same configured root) are kept once, at their first position.
    """
    out: List[Path] = []
    for root, rel in defaults:
        mapped = user_root(root, platform)
        if mapped is None:
            continue
        path = mapped / rel if rel else mapped
        if path not in out:
            out.append(path)
    return out


def home_fallbacks_allowed() -> bool:
    """False in strict mode: lookups must not try places below the home directory."""
    return not strict_paths()


def client_log_dir(platform: Optional[str] = None) -> Optional[Path]:
    """The Claude Desktop log folder some developer tools copy from, or None.

    ``KICAD_MCP_CLIENT_LOG_DIR`` when set; None in strict mode (the server
    then reads no other program's files); otherwise Claude Desktop's default.
    """
    platform = platform if platform is not None else sys.platform
    configured = _env_dir("KICAD_MCP_CLIENT_LOG_DIR")
    if configured is not None:
        return configured
    if strict_paths():
        return None
    if platform.startswith("win"):
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "logs"
    if platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Claude"
    return Path.home() / ".config" / "Claude" / "logs"


def check_strict_paths() -> List[str]:
    """What strict mode is missing; empty when strict mode is off or complete.

    Strict mode needs ``KICAD_CONFIG_HOME`` and ``KICAD_DOCUMENTS_HOME`` as
    existing absolute folders and ``KICAD_MCP_HOME`` as an absolute path (it is
    created when missing), so that nothing defaults to the home directory. An
    ``XDG_*_HOME`` that points into the user's desktop folders (``$HOME``
    itself, ``~/.config``, ``~/.cache``, ``~/.local`` and below; inherited from a
    desktop session) counts as a problem too, because the server's own folders
    follow it. A project folder elsewhere below ``$HOME`` is fine. Strict mode
    covers the server's lookups; child processes (kicad-cli, Java for
    Freerouting) get the environment as it is, so a strict setup should give
    them a HOME of its own as well.
    """
    if not strict_paths():
        return []
    problems = []
    for name in (CONFIG_HOME_ENV, DOCUMENTS_HOME_ENV):
        path = _env_dir(name)
        if path is None:
            problems.append(f"{name} is not set")
        elif not path.is_absolute():
            problems.append(f"{name} is not an absolute path: {path}")
        elif not path.is_dir():
            problems.append(f"{name} does not exist: {path}")
    home = Path.home()
    # The desktop defaults (and $HOME itself), not any folder below $HOME: a
    # workspace that keeps its tool folders inside a project below $HOME is fine.
    defaults = (home, home / ".config", home / ".cache", home / ".local" / "share", home / ".local")
    for name in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
        path = _env_dir(name)
        if path is not None:
            path = Path(os.path.normpath(path))  # "proj/../.config" is ~/.config
        if path is not None and (path in defaults or any(d in path.parents for d in defaults[1:])):
            problems.append(f"{name} points into the user's desktop folders: {path}")
    mcp_home = _env_dir("KICAD_MCP_HOME")
    if mcp_home is None:
        problems.append("KICAD_MCP_HOME is not set")
    elif not mcp_home.is_absolute():
        problems.append(f"KICAD_MCP_HOME is not an absolute path: {mcp_home}")
    return problems
