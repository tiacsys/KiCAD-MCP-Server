# tiacsys build of KiCAD-MCP-Server

This fork carries a small patch series on top of an upstream release for the tiacsys XDMOD
workspaces, which keep every tool's configuration inside the workspace (no writes to, and no
reads from, the user's home directory).

- Branch `xd/main` = upstream tag (now `v2.9.0`) + the patches, each merged through a pull request.
- Tags `v<upstream>-xd.<n>` (e.g. `v2.9.0-xd.1`) on `xd/main`; `.github/workflows/xd-release.yml`
  publishes `kicad-mcp-server-<version>.tar.gz` and `SHA256SUMS` for them (built by
  `xd/build-asset.sh`).
- `requirements.lock.txt`: the runtime Python dependencies with hashes, compiled from
  `xd/requirements.in` (requirements.txt without pymupdf, which is AGPL-3.0) with the
  pip-compile command at the top of that file. `xd-ci.yml` fails when either falls behind.
- `xd-ci.yml` runs the tests (with an empty fake `HOME`; any write below it fails the job) and
  builds the asset twice to check that it is reproducible. `xd-release.yml` does not run the
  tests: tags go only on `xd/main` commits whose CI passed. It builds with a read-only token
  and no stored credentials, then a separate job with the write token publishes the files.
- Actions are pinned by commit SHA, Node by exact version (`NODE_VERSION` in both workflows).
- Every patch is offered upstream. When upstream has them and publishes release assets, the
  workspaces go back to upstream and this fork is archived.

Licence: MIT, as upstream (LICENSE unchanged); the patches are MIT too.

## Patches on xd/main

| Patch | Variables | Upstream |
|---|---|---|
| Server folder and logs | `KICAD_MCP_HOME` (default `~/.kicad-mcp`), `KICAD_MCP_LOG_DIR` (default `$KICAD_MCP_HOME/logs`); `logDir` of the config file applies | draft, not yet offered |
