"""In readonly and manufacturing mode run_drc leaves the design folder untouched.

run_drc always wrote ``<board>_drc_violations.json`` next to the board, also in
readonly mode, which promises a session that changes nothing in the design: a
readonly DRC on a checked-out repo left an untracked file in it. The full
violation list now goes to ``$KICAD_MCP_HOME/reports`` in those modes (named
after the board plus a hash of its path); in write mode it stays next to the
board as before. ``get_drc_violations`` reads it from wherever run_drc wrote it.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
sys.path.insert(0, str(Path(__file__).parent))

from test_run_drc_report_categories import KICAD10_HELP, _commands  # noqa: E402
from utils.mcp_paths import drc_violations_file, operating_mode  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def mcp_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("mcp-home")  # outside the board's folder
    monkeypatch.setenv("KICAD_MCP_HOME", str(home))
    monkeypatch.delenv("KICAD_MCP_OPERATING_MODE", raising=False)
    return home


@pytest.mark.parametrize(
    "raw, mode",
    [
        (None, "write"),
        ("", "write"),
        ("Write", "write"),
        ("read-only", "readonly"),
        ("READ_ONLY", "readonly"),
        ("manufacturing", "manufacturing"),
        ("nonsense", "readonly"),  # fails closed, as operating-mode.ts
    ],
)
def test_operating_mode_matches_the_node_side(monkeypatch, raw, mode):
    if raw is None:
        monkeypatch.delenv("KICAD_MCP_OPERATING_MODE", raising=False)
    else:
        monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", raw)
    assert operating_mode() == mode


def test_write_mode_keeps_the_file_next_to_the_board(tmp_path, mcp_home):
    board = tmp_path / "proj" / "b.kicad_pcb"
    assert drc_violations_file(str(board)) == tmp_path / "proj" / "b_drc_violations.json"


@pytest.mark.parametrize("mode", ["readonly", "manufacturing"])
def test_readonly_file_under_mcp_home(tmp_path, mcp_home, monkeypatch, mode):
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", mode)
    a = drc_violations_file(str(tmp_path / "a" / "b.kicad_pcb"))
    b = drc_violations_file(str(tmp_path / "c" / "b.kicad_pcb"))
    assert a.parent == mcp_home / "reports" and b.parent == mcp_home / "reports"
    assert a != b and a.name.startswith("b-") and a.name.endswith("_drc_violations.json")


def test_readonly_run_drc_writes_nothing_next_to_the_board(tmp_path, mcp_home, monkeypatch):
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "readonly")
    runs = []
    cmds, board_file = _commands(tmp_path, monkeypatch, KICAD10_HELP, runs)
    before = sorted(p.name for p in board_file.parent.iterdir())
    res = cmds.run_drc({})
    assert res["success"], res
    assert sorted(p.name for p in board_file.parent.iterdir()) == before
    report = Path(res["violationsFile"])
    assert report.parent == mcp_home / "reports"
    assert json.loads(report.read_text())["total_violations"] == 3
    got = cmds.get_drc_violations({})  # runs DRC again and reads the file back
    assert got["success"] and len(got["violations"]) == 3


def test_write_mode_run_drc_unchanged(tmp_path, mcp_home, monkeypatch):
    runs = []
    cmds, board_file = _commands(tmp_path, monkeypatch, KICAD10_HELP, runs)
    res = cmds.run_drc({})
    assert Path(res["violationsFile"]) == board_file.parent / "b_drc_violations.json"
    assert not (mcp_home / "reports").exists()
