"""The server's own folder and log folder can be moved (KICAD_MCP_HOME, KICAD_MCP_LOG_DIR).

Both used to be fixed under ``~/.kicad-mcp``: the Python worker created
``~/.kicad-mcp/logs`` when it was imported, the Node logger did the same on the
first message, and ``logDir`` in the config file was read but never applied.
A setup that keeps all tool state out of the home directory had no way to stop
those writes.

- ``KICAD_MCP_HOME`` moves the server's folder (logs, default Freerouting JAR).
- ``KICAD_MCP_LOG_DIR`` moves the log folder alone and wins over KICAD_MCP_HOME.
- Unset or empty, everything stays where it was.

Everything here runs against a fake home directory; the real one is never read
or written. tests-ts/logger-paths.test.ts covers the Node side.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from commands import freerouting  # noqa: E402
from utils.mcp_paths import default_freerouting_jar, mcp_home, mcp_log_dir  # noqa: E402
from utils.platform_helper import PlatformHelper  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home directory, with every variable this module reads cleared."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake)
    monkeypatch.setenv("HOME", str(fake))
    for var in ("KICAD_MCP_HOME", "KICAD_MCP_LOG_DIR", "FREEROUTING_JAR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return fake


class TestDefaults:
    def test_home_and_logs_under_dot_kicad_mcp(self, home):
        assert mcp_home() == home / ".kicad-mcp"
        assert mcp_log_dir() == home / ".kicad-mcp" / "logs"

    def test_empty_values_count_as_unset(self, home, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_HOME", "")
        monkeypatch.setenv("KICAD_MCP_LOG_DIR", "  ")
        assert mcp_log_dir() == home / ".kicad-mcp" / "logs"

    def test_freerouting_jar_default(self, home):
        assert default_freerouting_jar() == home / ".kicad-mcp" / "freerouting.jar"


class TestOverrides:
    def test_mcp_home_moves_logs_and_jar(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "ws" / "kicad-mcp"))
        assert mcp_home() == tmp_path / "ws" / "kicad-mcp"
        assert mcp_log_dir() == tmp_path / "ws" / "kicad-mcp" / "logs"
        assert default_freerouting_jar() == tmp_path / "ws" / "kicad-mcp" / "freerouting.jar"

    def test_log_dir_wins_over_mcp_home(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "mcp"))
        monkeypatch.setenv("KICAD_MCP_LOG_DIR", str(tmp_path / "logs"))
        assert mcp_log_dir() == tmp_path / "logs"
        assert mcp_home() == tmp_path / "mcp"

    def test_tilde_is_expanded(self, home, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_HOME", "~/elsewhere")
        assert mcp_home() == home / "elsewhere"

    def test_freerouting_jar_env_wins(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "mcp"))
        monkeypatch.setenv("FREEROUTING_JAR", str(tmp_path / "fr.jar"))
        assert default_freerouting_jar() == tmp_path / "fr.jar"

    def test_platform_helper_log_dir_follows_env(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_LOG_DIR", str(tmp_path / "logs"))
        assert PlatformHelper.get_log_dir() == tmp_path / "logs"


class TestPlatformConfigDir:
    """get_config_dir() on Windows and unknown platforms is the server's home folder."""

    def _platform(self, monkeypatch, name):
        for check in ("is_windows", "is_linux", "is_macos"):
            monkeypatch.setattr(
                PlatformHelper, check, staticmethod(lambda c=check: c == f"is_{name}")
            )

    @pytest.mark.parametrize("name", ["windows", "unknown"])
    def test_default(self, home, monkeypatch, name):
        self._platform(monkeypatch, name)
        assert PlatformHelper.get_config_dir() == home / ".kicad-mcp"

    @pytest.mark.parametrize("name", ["windows", "unknown"])
    def test_follows_mcp_home(self, home, tmp_path, monkeypatch, name):
        self._platform(monkeypatch, name)
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "mcp"))
        assert PlatformHelper.get_config_dir() == tmp_path / "mcp"
        assert PlatformHelper.get_cache_dir() == tmp_path / "mcp" / "cache"
        assert PlatformHelper.get_data_dir() == tmp_path / "mcp" / "data"


class TestFreeroutingUsesTheResolvedJar:
    def test_check_freerouting_looks_under_mcp_home(self, home, tmp_path, monkeypatch):
        """check_freerouting resolves the default per call, not at import."""
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "mcp"))
        seen = []
        monkeypatch.setattr(freerouting, "_jar_required_java", lambda jar: seen.append(jar) or 21)
        monkeypatch.setattr(freerouting, "_find_java", lambda required: None)
        commands = freerouting.FreeroutingCommands.__new__(freerouting.FreeroutingCommands)
        try:
            commands.check_freerouting({})
        except Exception:
            pass  # only the path it looked at matters here
        assert seen and Path(seen[0]) == tmp_path / "mcp" / "freerouting.jar"


class TestWorkerImport:
    """Importing kicad_interface sets up the log file; it must land in the configured folder.

    The child process gets the same pcbnew stand-in as conftest.py, so this
    runs without KiCad.
    """

    PRELUDE = (
        "import sys\n"
        "from unittest.mock import MagicMock\n"
        "pcbnew = MagicMock()\n"
        "pcbnew.__file__ = '/fake/pcbnew.so'\n"
        "pcbnew.__spec__ = None\n"
        "pcbnew.GetBuildVersion.return_value = '10.0.0-stub'\n"
        "sys.modules['pcbnew'] = pcbnew\n"
        "import kicad_interface\n"
    )

    def _import_worker(self, home: Path, **env: str) -> None:
        run_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("KICAD_MCP_HOME", "KICAD_MCP_LOG_DIR", "PYTHONPATH")
        }
        run_env.update(HOME=str(home), KICAD_SKIP_SYMBOL_WARMUP="1", **env)
        subprocess.run(
            [sys.executable, "-c", self.PRELUDE],
            cwd=PYTHON_DIR,
            env=run_env,
            check=True,
            capture_output=True,
            timeout=120,
        )

    def test_log_dir_env(self, home, tmp_path):
        self._import_worker(home, KICAD_MCP_LOG_DIR=str(tmp_path / "logs"))
        assert list((tmp_path / "logs").glob("kicad_interface-*.log"))
        assert not (home / ".kicad-mcp").exists()

    def test_mcp_home_env(self, home, tmp_path):
        self._import_worker(home, KICAD_MCP_HOME=str(tmp_path / "mcp"))
        assert list((tmp_path / "mcp" / "logs").glob("kicad_interface-*.log"))
        assert not (home / ".kicad-mcp").exists()
