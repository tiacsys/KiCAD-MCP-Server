"""KiCad's per-user folders follow KICAD_DOCUMENTS_HOME / KICAD_CONFIG_HOME, and strict mode.

KiCad moves its per-user folders with two variables of its own, but several
lookups here ignored them:

- the global library tables were also searched in ``~/.config/kicad`` (and
  ``APPDATA``, ``XDG_CONFIG_HOME``) when ``KICAD_CONFIG_HOME`` was set, though
  KiCad then reads only that root;
- per-user libraries, the ``3rdparty`` folder, the GUI-driver plugin folder
  and its token file were always looked for in ``~/Documents/KiCad`` or
  ``~/.local/share/kicad``, never under ``KICAD_DOCUMENTS_HOME``;
- two developer helpers read the Claude Desktop logs from the home directory.

``KICAD_MCP_STRICT_PATHS=1`` turns every remaining home-directory default off,
and the worker refuses to start unless the folders it needs are configured.

Everything here runs against a fake home directory; the real one is never read
or written.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))
sys.path.insert(0, str(PYTHON_DIR.parent / "gui_driver_plugin"))

from commands import gui_driver  # noqa: E402
from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402
from commands.footprint import FootprintCreator  # noqa: E402
from commands.library_schematic import LibraryManager as SchematicLibraryManager  # noqa: E402
from utils import kicad_cli  # noqa: E402
from utils.mcp_paths import StrictPathError, mcp_home  # noqa: E402
from utils.platform_helper import PlatformHelper  # noqa: E402
from utils.user_dirs import (  # noqa: E402
    check_strict_paths,
    client_log_dir,
    documents_root,
    map_user_paths,
    user_root,
)

pytestmark = pytest.mark.unit

ENV_VARS = (
    "KICAD_MCP_STRICT_PATHS",
    "KICAD_DOCUMENTS_HOME",
    "KICAD_CONFIG_HOME",
    "KICAD_MCP_HOME",
    "KICAD_MCP_LOG_DIR",
    "KICAD_MCP_CLIENT_LOG_DIR",
    "APPDATA",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "KICAD10_3RD_PARTY",
    "KICAD9_3RD_PARTY",
    "KICAD8_3RD_PARTY",
    "KICAD_3RD_PARTY",
    "KICAD_GUI_DRIVER_TOKEN_FILE",
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home directory with KiCad folders in every default place.

    The default places are filled so that a lookup that still falls back to
    the home directory finds something and the test can see it.
    """
    fake = tmp_path / "home"
    for rel in (
        ".local/share/kicad/10.0/symbols",
        ".local/share/kicad/10.0/footprints/Home.pretty",
        ".local/share/kicad/10.0/3rdparty/plugins",
        "Documents/KiCad/10.0/symbols",
        "Documents/KiCad/10.0/footprints/HomeDocs.pretty",
        "Documents/KiCad/10.0/3rdparty",
        ".config/kicad/10.0",
        ".local/bin",
    ):
        (fake / rel).mkdir(parents=True)
    (fake / ".local/share/kicad/10.0/symbols/Home.kicad_sym").write_text("(kicad_symbol_lib)")
    (fake / "Documents/KiCad/10.0/symbols/HomeDocs.kicad_sym").write_text("(kicad_symbol_lib)")
    monkeypatch.setattr(Path, "home", lambda: fake)
    monkeypatch.setenv("HOME", str(fake))
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    DynamicSymbolLoader.clear_library_caches()
    yield fake
    DynamicSymbolLoader.clear_library_caches()


@pytest.fixture
def docs(tmp_path, monkeypatch):
    """KICAD_DOCUMENTS_HOME with one per-user library of each kind (Linux layout)."""
    root = tmp_path / "ws" / "kicad-documents"
    ver = root / "kicad" / "10.0"
    (ver / "symbols").mkdir(parents=True)
    (ver / "symbols" / "Ws.kicad_sym").write_text("(kicad_symbol_lib)")
    (ver / "footprints" / "Ws.pretty").mkdir(parents=True)
    (ver / "3rdparty" / "plugins").mkdir(parents=True)
    monkeypatch.setenv("KICAD_DOCUMENTS_HOME", str(root))
    monkeypatch.setattr(sys, "platform", "linux")
    return root


def _strict(monkeypatch):
    monkeypatch.setenv("KICAD_MCP_STRICT_PATHS", "1")


def _no_home(paths, home: Path):
    """None of *paths* (strings, Paths or glob patterns) points below *home*."""
    below = [str(p) for p in paths if str(p).startswith(str(home))]
    assert below == [], below


# --- utils/user_dirs.py ----------------------------------------------------- #


class TestDocumentsRoot:
    def test_default_linux(self, home):
        assert documents_root("linux") == home / ".local" / "share" / "kicad"

    def test_default_windows_and_macos(self, home):
        assert documents_root("win32") == home / "Documents" / "KiCad"
        assert documents_root("darwin") == home / "Documents" / "KiCad"

    def test_documents_home(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_DOCUMENTS_HOME", str(tmp_path / "d"))
        assert documents_root("linux") == tmp_path / "d" / "kicad"
        assert documents_root("win32") == tmp_path / "d" / "KiCad"
        for default in (home / ".local/share/kicad", home / "Documents/KiCad"):
            assert user_root(default, "linux") == tmp_path / "d" / "kicad"

    def test_default_roots_are_unchanged(self, home):
        for default in (home / ".local/share/kicad", home / "Documents/KiCad"):
            assert user_root(default, "linux") == default

    def test_map_keeps_order_and_drops_duplicates(self, home, tmp_path, monkeypatch):
        defaults = [(home / "Documents/KiCad", "10.0/x"), (home / ".local/share/kicad", "10.0/x")]
        assert map_user_paths(defaults, "linux") == [
            home / "Documents/KiCad/10.0/x",
            home / ".local/share/kicad/10.0/x",
        ]
        monkeypatch.setenv("KICAD_DOCUMENTS_HOME", str(tmp_path / "d"))
        assert map_user_paths(defaults, "linux") == [tmp_path / "d" / "kicad" / "10.0" / "x"]

    def test_strict_has_no_default(self, home, monkeypatch):
        _strict(monkeypatch)
        assert documents_root("linux") is None
        assert user_root(home / "Documents/KiCad", "linux") is None


class TestClientLogDir:
    def test_default(self, home, monkeypatch):
        assert client_log_dir("linux") == home / ".config" / "Claude" / "logs"

    def test_override(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_MCP_CLIENT_LOG_DIR", str(tmp_path / "c"))
        assert client_log_dir("linux") == tmp_path / "c"

    def test_strict_reads_no_client_logs(self, home, monkeypatch):
        _strict(monkeypatch)
        assert client_log_dir("linux") is None


class TestCheckStrictPaths:
    def test_off_means_no_problems(self, home):
        assert check_strict_paths() == []

    def test_lists_every_missing_folder(self, home, monkeypatch):
        _strict(monkeypatch)
        problems = " ".join(check_strict_paths())
        for var in ("KICAD_CONFIG_HOME", "KICAD_DOCUMENTS_HOME", "KICAD_MCP_HOME"):
            assert var in problems

    def test_complete(self, home, tmp_path, monkeypatch):
        _strict(monkeypatch)
        for var, sub in (("KICAD_CONFIG_HOME", "c"), ("KICAD_DOCUMENTS_HOME", "d")):
            (tmp_path / sub).mkdir()
            monkeypatch.setenv(var, str(tmp_path / sub))
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "m"))
        assert check_strict_paths() == []

    def test_relative_and_missing_folders(self, home, tmp_path, monkeypatch):
        _strict(monkeypatch)
        monkeypatch.setenv("KICAD_CONFIG_HOME", "relative/conf")
        monkeypatch.setenv("KICAD_DOCUMENTS_HOME", str(tmp_path / "nope"))
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "m"))
        problems = check_strict_paths()
        assert any("not an absolute path" in p for p in problems)
        assert any("does not exist" in p for p in problems)

    def test_mcp_home_has_no_default_in_strict_mode(self, home, monkeypatch):
        _strict(monkeypatch)
        with pytest.raises(StrictPathError):
            mcp_home()


# --- KICAD_CONFIG_HOME is the only configuration root ------------------------ #


class TestConfigHome:
    def test_only_root_when_set(self, home, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_CONFIG_HOME", str(tmp_path / "conf"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        dirs = PlatformHelper.kicad_config_dirs()
        assert dirs and all(d.parent == tmp_path / "conf" for d in dirs)
        assert dirs[0] == tmp_path / "conf" / "10.0"

    def test_default_still_searches_the_platform_roots(self, home):
        assert home / ".config" / "kicad" / "10.0" in PlatformHelper.kicad_config_dirs()

    def test_strict_without_config_home_searches_nothing(self, home, monkeypatch):
        _strict(monkeypatch)
        assert PlatformHelper.kicad_config_dirs() == []


# --- per-user libraries and 3rdparty ----------------------------------------- #


class TestUserLibraries:
    def test_3rdparty_under_documents_home(self, home, docs):
        assert PlatformHelper.find_kicad_3rd_party_dir() == str(
            docs / "kicad" / "10.0" / "3rdparty"
        )

    def test_3rdparty_default_order_unchanged(self, home, monkeypatch):
        """Both default folders exist (fixture): ~/Documents/KiCad wins, as upstream."""
        monkeypatch.setattr(sys, "platform", "linux")
        assert PlatformHelper.find_kicad_3rd_party_dir() == str(
            home / "Documents" / "KiCad" / "10.0" / "3rdparty"
        )

    def test_3rdparty_strict_does_not_fall_back(self, home, monkeypatch):
        _strict(monkeypatch)
        assert PlatformHelper.find_kicad_3rd_party_dir() is None

    def test_symbol_patterns(self, home, docs, monkeypatch):
        monkeypatch.setattr(PlatformHelper, "is_linux", staticmethod(lambda: True))
        monkeypatch.setattr(PlatformHelper, "is_windows", staticmethod(lambda: False))
        monkeypatch.setattr(PlatformHelper, "is_macos", staticmethod(lambda: False))
        patterns = PlatformHelper.get_kicad_library_search_paths()
        assert str(docs / "kicad" / "*" / "symbols" / "*.kicad_sym") in patterns
        _no_home([p for p in patterns if "Documents" in p], home)
        _strict(monkeypatch)
        _no_home(PlatformHelper.get_kicad_library_search_paths(), home)

    def test_symbol_patterns_default_unchanged(self, home, monkeypatch):
        """Exactly upstream's home-directory globs, in upstream's order."""
        monkeypatch.setattr(PlatformHelper, "is_linux", staticmethod(lambda: True))
        monkeypatch.setattr(PlatformHelper, "is_windows", staticmethod(lambda: False))
        monkeypatch.setattr(PlatformHelper, "is_macos", staticmethod(lambda: False))
        patterns = PlatformHelper.get_kicad_library_search_paths()
        assert [p for p in patterns if p.startswith(str(home))] == [
            str(home / ".local/share/kicad/symbols/*.kicad_sym"),
            str(home / "Documents/KiCad/*/symbols/*.kicad_sym"),
            str(home / "Documents/KiCad/*/symbols/*.kicad_symdir/*.kicad_sym"),
        ]
        assert patterns.index(str(home / ".local/share/kicad/symbols/*.kicad_sym")) == 2

    def test_macos_user_applications_not_in_strict_mode(self, home, monkeypatch):
        monkeypatch.setattr(PlatformHelper, "is_linux", staticmethod(lambda: False))
        monkeypatch.setattr(PlatformHelper, "is_windows", staticmethod(lambda: False))
        monkeypatch.setattr(PlatformHelper, "is_macos", staticmethod(lambda: True))
        (home / "Applications/KiCad/KiCad.app/Contents/Frameworks").mkdir(parents=True)
        assert any(str(home) in p for p in PlatformHelper.get_kicad_library_search_paths())
        _strict(monkeypatch)
        _no_home(PlatformHelper.get_kicad_library_search_paths(), home)
        _no_home(PlatformHelper.get_kicad_python_paths(), home)

    def test_footprint_libraries_default_unchanged(self, home):
        """Upstream searched ~/Documents/KiCad/{9,10}.0/footprints only."""
        names = set(FootprintCreator().list_footprint_libraries()["libraries"])
        assert "HomeDocs" in names and "Home" not in names

    def test_schematic_library_list_default_unchanged(self, home):
        names = SchematicLibraryManager.list_available_libraries()["names"]
        assert "HomeDocs" in names and "Home" not in names

    def test_dynamic_loader_default_unchanged(self, home):
        dirs = DynamicSymbolLoader().find_kicad_symbol_libraries()
        assert [d for d in dirs if str(d).startswith(str(home))] == [
            home / ".local/share/kicad/10.0/symbols"
        ]

    def test_footprint_libraries(self, home, docs, monkeypatch):
        libs = FootprintCreator().list_footprint_libraries()
        names = set(libs.get("libraries", libs))
        assert "Ws" in names
        assert "HomeDocs" not in names and "Home" not in names

    def test_schematic_library_list(self, home, docs):
        names = SchematicLibraryManager.list_available_libraries()["names"]
        assert "Ws" in names and "HomeDocs" not in names

    def test_dynamic_loader_dirs(self, home, docs, monkeypatch):
        dirs = DynamicSymbolLoader().find_kicad_symbol_libraries()
        assert docs / "kicad" / "10.0" / "symbols" in dirs
        _no_home(dirs, home)

    def test_dynamic_loader_strict(self, home, monkeypatch):
        _strict(monkeypatch)
        _no_home(DynamicSymbolLoader().find_kicad_symbol_libraries(), home)


# --- binaries and Python paths below the home directory --------------------- #


class TestHomeBinaries:
    def test_kicad_cli_candidates(self, home, monkeypatch):
        monkeypatch.setattr(kicad_cli.platform, "system", lambda: "Linux")
        assert home / ".local" / "bin" / "kicad-cli" in kicad_cli._candidate_paths()
        _strict(monkeypatch)
        _no_home(kicad_cli._candidate_paths(), home)

    def test_kicad_python_paths(self, home, monkeypatch):
        (home / ".local/lib/kicad/lib/python3/dist-packages").mkdir(parents=True)
        monkeypatch.setattr(PlatformHelper, "is_windows", staticmethod(lambda: False))
        monkeypatch.setattr(PlatformHelper, "is_linux", staticmethod(lambda: True))
        _strict(monkeypatch)
        _no_home(PlatformHelper.get_kicad_python_paths(), home)


# --- the server's own folders in strict mode --------------------------------- #


class TestStrictServerFolders:
    def test_config_cache_data_under_mcp_home(self, home, tmp_path, monkeypatch):
        _strict(monkeypatch)
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "m"))
        assert PlatformHelper.get_config_dir() == tmp_path / "m" / "config"
        assert PlatformHelper.get_cache_dir() == tmp_path / "m" / "cache"
        assert PlatformHelper.get_data_dir() == tmp_path / "m" / "data"
        assert PlatformHelper.get_log_dir() == tmp_path / "m" / "logs"

    def test_xdg_still_wins(self, home, tmp_path, monkeypatch):
        _strict(monkeypatch)
        monkeypatch.setenv("KICAD_MCP_HOME", str(tmp_path / "m"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        assert PlatformHelper.get_cache_dir() == tmp_path / "xdg-cache" / "kicad-mcp"

    def test_defaults_unchanged(self, home, monkeypatch):
        monkeypatch.setattr(PlatformHelper, "is_windows", staticmethod(lambda: False))
        monkeypatch.setattr(PlatformHelper, "is_linux", staticmethod(lambda: True))
        assert PlatformHelper.get_cache_dir() == home / ".cache" / "kicad-mcp"


# --- GUI driver: plugin folder and token file -------------------------------- #


class TestGuiDriver:
    def test_plugin_dir_from_3rd_party_var(self, tmp_path):
        dirs = gui_driver.kicad_plugin_dirs(
            platform="linux", environ={"KICAD10_3RD_PARTY": str(tmp_path / "3p")}, home=tmp_path
        )
        assert dirs == [tmp_path / "3p" / "plugins"]

    def test_plugin_dir_under_documents_home(self, tmp_path):
        (tmp_path / "d" / "kicad" / "10.0").mkdir(parents=True)
        (tmp_path / "h" / ".local/share/kicad/10.0").mkdir(parents=True)
        dirs = gui_driver.kicad_plugin_dirs(
            platform="linux",
            environ={"KICAD_DOCUMENTS_HOME": str(tmp_path / "d")},
            home=tmp_path / "h",
        )
        assert dirs == [tmp_path / "d" / "kicad" / "10.0" / "3rdparty" / "plugins"]

    def test_plugin_dir_strict_without_config(self, tmp_path):
        (tmp_path / ".local/share/kicad/10.0").mkdir(parents=True)
        assert (
            gui_driver.kicad_plugin_dirs(
                platform="linux", environ={"KICAD_MCP_STRICT_PATHS": "1"}, home=tmp_path
            )
            == []
        )

    def test_token_path_under_documents_home_matches_listener(self, home, docs, monkeypatch):
        from plugins import listener

        monkeypatch.setenv("KICAD_GUI_DRIVER_PORT", "8770")
        written = listener._token_path()
        assert written == gui_driver._token_path()
        assert written == docs / "kicad" / "gui_driver_8770.token"


# --- the worker under strict mode -------------------------------------------- #

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


def _run_worker(home: Path, code: str, **env: str) -> subprocess.CompletedProcess:
    run_env = {k: v for k, v in os.environ.items() if k not in ENV_VARS and k != "PYTHONPATH"}
    run_env.update(HOME=str(home), KICAD_SKIP_SYMBOL_WARMUP="1", **env)
    return subprocess.run(
        [sys.executable, "-c", PRELUDE + code],
        cwd=PYTHON_DIR,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )


class TestWorkerStrict:
    def test_refuses_to_start_and_writes_nothing(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        r = _run_worker(home, "kicad_interface.main()\n", KICAD_MCP_STRICT_PATHS="1")
        assert r.returncode == 2, r.stderr[-2000:]
        assert "KICAD_MCP_STRICT_PATHS is set, but" in r.stderr
        assert list(home.iterdir()) == []

    def test_configured_lookups_stay_out_of_home(self, tmp_path):
        """Tripwire: a strict worker resolves its folders without reading or writing HOME.

        HOME holds a planted KiCad tree in every default place. The child records
        every stat, open, listdir, scandir and glob below HOME (os.stat/os.lstat
        wrapped, the rest through audit hooks) and prints them; there must be none.
        """
        home = tmp_path / "home"
        for rel in (
            ".config/kicad/10.0",
            ".local/share/kicad/10.0/symbols",
            ".local/share/kicad/10.0/3rdparty/plugins",
            "Documents/KiCad/10.0/footprints/Planted.pretty",
            "Documents/KiCad/10.0/3rdparty",
            ".local/bin",
        ):
            (home / rel).mkdir(parents=True)
        (home / ".local/share/kicad/10.0/symbols/Planted.kicad_sym").write_text("(x)")
        conf, docs, mcp = tmp_path / "conf", tmp_path / "docs", tmp_path / "mcp"
        conf.mkdir()
        docs.mkdir()
        code = (
            "import os, sys, json\n"
            "HOME = os.environ['HOME']\n"
            "hits = []\n"
            "def _rec(p):\n"
            "    try:\n"
            "        s = os.fsdecode(p)\n"
            "    except TypeError:\n"
            "        return\n"
            "    if s == HOME or s.startswith(HOME + os.sep):\n"
            "        hits.append(s)\n"
            "def _hook(event, args):\n"
            "    if event in ('open', 'os.listdir', 'os.scandir', 'glob.glob') and args:\n"
            "        _rec(args[0])\n"
            "sys.addaudithook(_hook)\n"
            "for name in ('stat', 'lstat'):\n"
            "    real = getattr(os, name)\n"
            "    def wrapped(p, *a, _real=real, **k):\n"
            "        _rec(p)\n"
            "        return _real(p, *a, **k)\n"
            "    setattr(os, name, wrapped)\n"
            "from utils.platform_helper import PlatformHelper as P\n"
            "from utils import kicad_cli\n"
            "from commands.dynamic_symbol_loader import DynamicSymbolLoader\n"
            "from commands.footprint import FootprintCreator\n"
            "from commands.library_schematic import LibraryManager as L\n"
            "P.kicad_config_dirs(); P.find_kicad_3rd_party_dir()\n"
            "P.get_kicad_library_search_paths(); P.get_kicad_python_paths(); P.ensure_directories()\n"
            "DynamicSymbolLoader().find_kicad_symbol_libraries()\n"
            "FootprintCreator().list_footprint_libraries(); L.list_available_libraries()\n"
            "kicad_cli._candidate_paths()\n"
            "print('HITS=' + json.dumps(hits))\n"
        )
        r = _run_worker(
            home,
            code,
            KICAD_MCP_STRICT_PATHS="1",
            KICAD_CONFIG_HOME=str(conf),
            KICAD_DOCUMENTS_HOME=str(docs),
            KICAD_MCP_HOME=str(mcp),
        )
        assert r.returncode == 0, r.stderr[-2000:]
        hits = json.loads(r.stdout.rsplit("HITS=", 1)[1])
        assert hits == [], hits
        assert list((mcp / "logs").glob("kicad_interface-*.log"))
