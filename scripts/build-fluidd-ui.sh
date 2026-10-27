#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_TAG="v1.37.6"
BASE_COMMIT="d894c50d580212c245a7c552ae695008c441683b"
SOURCE_DIR="${FLUIDD_SOURCE_DIR:-$REPO_DIR/.build/fluidd-v1.37.6}"
PATCH_FILE="$REPO_DIR/fluidd/fluidd-v1.37.6.patch"
DIST_DIR="$REPO_DIR/fluidd/dist"

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v node >/dev/null || {
    echo "Node.js 22.12+ or 24 is required to rebuild Fluidd." >&2
    echo "The prebuilt fluidd/dist can be installed without Node.js." >&2
    exit 1
}
command -v pnpm >/dev/null || {
    echo "pnpm 12.5.1 is required to rebuild Fluidd." >&2
    exit 1
}

rm -rf "$SOURCE_DIR"
mkdir -p "$(dirname "$SOURCE_DIR")"
git clone --depth 1 --branch "$BASE_TAG" \
    https://github.com/fluidd-core/fluidd.git "$SOURCE_DIR"

ACTUAL_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
if [[ "$ACTUAL_COMMIT" != "$BASE_COMMIT" ]]; then
    echo "Unexpected Fluidd $BASE_TAG commit: $ACTUAL_COMMIT" >&2
    exit 1
fi

git -C "$SOURCE_DIR" apply --check "$PATCH_FILE"
git -C "$SOURCE_DIR" apply "$PATCH_FILE"

(
    cd "$SOURCE_DIR"
    pnpm install --frozen-lockfile
    pnpm run lint
    pnpm run type-check
    NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1536}" pnpm run build
)

rm -rf "$DIST_DIR"
cp -a "$SOURCE_DIR/dist" "$DIST_DIR"
echo "Built custom Fluidd at: $DIST_DIR"
