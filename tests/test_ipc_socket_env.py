"""The IPC backend honours KICAD_API_SOCKET and KICAD_API_TOKEN.

``IPCBackend.connect()`` tried ``/tmp/kicad/api.sock`` and
``/run/user/<uid>/kicad/api.sock`` first and only then let kipy pick its
default, so ``KICAD_API_SOCKET`` (which KiCad sets for the plugins it starts,
and which a setup with its own runtime folder sets for other clients) was used
only after both fixed paths had failed, and a KiCad listening on the fixed
path won even when the variable named another one.

Now an explicit ``socket_path`` comes first, then ``KICAD_API_SOCKET`` as the
only candidate (a bare path gets the ``ipc://`` scheme), then the old list.
``KICAD_API_TOKEN`` is passed to kipy when set.

No KiCad is started; a fake kipy records what the backend asks for.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_api import ipc_backend  # noqa: E402
from kicad_api.ipc_backend import IPCBackend, api_socket_from_env  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_kipy(monkeypatch):
    """A kipy whose KiCad records every connection attempt and accepts *accept*."""
    attempts = []
    state = {"accept": lambda path: True}

    class FakeKiCad:
        def __init__(self, socket_path=None, kicad_token=None):
            attempts.append({"socket_path": socket_path, "kicad_token": kicad_token})
            if not state["accept"](socket_path):
                raise OSError(f"nothing listens on {socket_path}")

        def ping(self):
            pass

        def check_version(self):
            return True

        def get_api_version(self):
            return "10.0.8"

    module = types.ModuleType("kipy")
    module.KiCad = FakeKiCad  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kipy", module)
    for var in ("KICAD_API_SOCKET", "KICAD_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ipc_backend.platform, "system", lambda: "Linux")
    return attempts, state


class TestApiSocketFromEnv:
    def test_unset_and_empty(self, monkeypatch):
        monkeypatch.delenv("KICAD_API_SOCKET", raising=False)
        assert api_socket_from_env() is None
        monkeypatch.setenv("KICAD_API_SOCKET", "  ")
        assert api_socket_from_env() is None

    def test_bare_path_gets_the_scheme(self, monkeypatch):
        monkeypatch.setenv("KICAD_API_SOCKET", "/ws/build/kicad/api.sock")
        assert api_socket_from_env() == "ipc:///ws/build/kicad/api.sock"

    def test_url_unchanged(self, monkeypatch):
        monkeypatch.setenv("KICAD_API_SOCKET", "ipc:///ws/api.sock")
        assert api_socket_from_env() == "ipc:///ws/api.sock"


class TestConnect:
    def test_env_socket_is_the_only_candidate(self, fake_kipy, monkeypatch):
        attempts, state = fake_kipy
        monkeypatch.setenv("KICAD_API_SOCKET", "/ws/api.sock")
        assert IPCBackend().connect()
        assert [a["socket_path"] for a in attempts] == ["ipc:///ws/api.sock"]

    def test_env_socket_does_not_fall_back(self, fake_kipy, monkeypatch):
        """A KiCad on /tmp/kicad/api.sock must not answer for the one the env names."""
        attempts, state = fake_kipy
        state["accept"] = lambda path: path == "ipc:///tmp/kicad/api.sock"
        monkeypatch.setenv("KICAD_API_SOCKET", "/ws/api.sock")
        with pytest.raises(Exception):
            IPCBackend().connect()
        assert [a["socket_path"] for a in attempts] == ["ipc:///ws/api.sock"]

    def test_explicit_argument_wins(self, fake_kipy, monkeypatch):
        attempts, _ = fake_kipy
        monkeypatch.setenv("KICAD_API_SOCKET", "/ws/api.sock")
        assert IPCBackend().connect("ipc:///other.sock")
        assert attempts[0]["socket_path"] == "ipc:///other.sock"

    def test_default_list_unchanged(self, fake_kipy):
        attempts, state = fake_kipy
        state["accept"] = lambda path: path is None
        assert IPCBackend().connect()
        paths = [a["socket_path"] for a in attempts]
        assert paths[0] == "ipc:///tmp/kicad/api.sock"
        assert paths[-1] is None  # kipy auto-detect last

    def test_token_is_passed(self, fake_kipy, monkeypatch):
        attempts, _ = fake_kipy
        monkeypatch.setenv("KICAD_API_SOCKET", "/ws/api.sock")
        monkeypatch.setenv("KICAD_API_TOKEN", "secret-token")
        assert IPCBackend().connect()
        assert attempts[0]["kicad_token"] == "secret-token"

    def test_no_token_argument_without_env(self, fake_kipy, monkeypatch):
        attempts, _ = fake_kipy
        monkeypatch.setenv("KICAD_API_SOCKET", "/ws/api.sock")
        assert IPCBackend().connect()
        assert attempts[0]["kicad_token"] is None
