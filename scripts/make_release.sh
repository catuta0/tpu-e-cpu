#!/usr/bin/env bash
# make_release.sh <RELEASE_NAME>
# Builds an immutable release directory releases/<RELEASE_NAME>/ from the current
# git HEAD: copies the released files, writes a SHA-256 manifest and refuses to
# overwrite an existing release (releases are immutable — ADR / CLAUDE.md rule).
set -euo pipefail
cd "$(dirname "$0")/.."
REL="${1:?usage: make_release.sh <RELEASE_NAME>}"
DST="releases/$REL"
if [ -e "$DST" ]; then echo "ERROR: $DST exists; releases are immutable" >&2; exit 1; fi
if [ -n "$(git status --porcelain)" ]; then echo "ERROR: working tree dirty; commit first" >&2; exit 1; fi
REV="$(git rev-parse --short HEAD)"
mkdir -p "$DST"
# Everything tracked under these paths is part of the baseline.
PATHS="CLAUDE.md design requirements management/INTERFACES.json management/DECISIONS.md \
management/RISKS.md management/SOURCES.md management/metrics.json management/TOOLCHAIN.md \
management/SMOKE_TESTS.md management/EXECUTION_METRICS.md code scripts tests sim/data \
reports docs"
for p in $PATHS; do
  [ -e "$p" ] || continue
  git ls-files -z -- "$p" | while IFS= read -r -d '' f; do
    mkdir -p "$DST/$(dirname "$f")"; cp -p "$f" "$DST/$f"; done
done
echo "$REV" > "$DST/GIT_REVISION"
( cd "$DST" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )
chmod -R a-w "$DST"
echo "release $REL built from $REV: $(wc -l < "$DST/MANIFEST.sha256") files"
