#!/usr/bin/env bash
# Build the release asset of the tiacsys build of KiCAD-MCP-Server.
#
#   xd/build-asset.sh <version> <out-dir>      e.g. xd/build-asset.sh 2.9.0-xd.1 out
#
# Writes <out-dir>/kicad-mcp-server-<version>.tar.gz and <out-dir>/SHA256SUMS. The archive holds
# one top folder kicad-mcp-server-<version>/ with what a user needs to run the server without a
# build step and without network access for npm:
#
#   dist/                  compiled TypeScript (npm run build)
#   node_modules/          production dependencies only (npm ci, then npm prune --omit=dev)
#   python/                the Python worker
#   gui_driver_plugin/     the optional in-KiCad helper
#   config/                example client configurations
#   package.json, package-lock.json, LICENSE
#   requirements.lock.txt  exact Python dependencies with hashes, without pymupdf (AGPL-3.0);
#                          install with pip install --no-deps --require-hashes -r ...
#   XD-BUILD.json          version, commit, node and npm versions of the build
#
# The archive is reproducible for a given commit, Node and npm version (pinned in the workflows):
# sorted names, fixed owner and modes, mtime = commit time, gzip without a timestamp. xd-ci.yml
# builds it twice and compares. Run from the repository root.
set -euo pipefail

version="${1:?usage: xd/build-asset.sh <version> <out-dir>}"
out="${2:?usage: xd/build-asset.sh <version> <out-dir>}"
name="kicad-mcp-server-${version}"

upstream="${version%%-xd.*}"
package=$(node -p "require('./package.json').version")
if [ "$upstream" != "$package" ]; then
  echo "error: version $version does not start with the package.json version $package" >&2
  exit 1
fi
if grep -qi '^pymupdf' requirements.lock.txt; then
  echo "error: requirements.lock.txt must not contain pymupdf (AGPL-3.0)" >&2
  exit 1
fi
if grep -E '^[A-Za-z0-9._-]+==' requirements.lock.txt | grep -vq -- '\\$'; then
  echo "error: requirements.lock.txt has a requirement without hashes" >&2
  exit 1
fi

commit=$(git rev-parse HEAD)
epoch=$(git log -1 --format=%ct HEAD)

# --ignore-scripts: no lifecycle script of any dependency runs; the build is plain tsc.
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm prune --omit=dev --no-audit --no-fund

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
root="$stage/$name"
mkdir -p "$root"
cp -a dist node_modules python gui_driver_plugin config package.json package-lock.json LICENSE \
  requirements.lock.txt "$root/"
find "$root" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$root" -name '*.pyc' -delete
cat > "$root/XD-BUILD.json" <<EOF
{
  "name": "kicad-mcp-server",
  "version": "${version}",
  "upstream_version": "${upstream}",
  "commit": "${commit}",
  "node": "$(node --version)",
  "npm": "$(npm --version)"
}
EOF

mkdir -p "$out"
tar --sort=name --mtime="@${epoch}" --owner=0 --group=0 --numeric-owner --mode='u+rw,go+rX,go-w' \
  --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime \
  -C "$stage" -cf - "$name" | gzip -n -9 > "$out/${name}.tar.gz"
(cd "$out" && sha256sum "${name}.tar.gz" > SHA256SUMS)
cat "$out/SHA256SUMS"
