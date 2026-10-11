#!/usr/bin/env bash
# Downloads a pinned, checksum-verified Litestream binary into ./bin.
# Runs during the Render build (see render.yaml). Safe to re-run.
set -euo pipefail

VERSION="0.5.17"
SHA256="cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d"  # linux-x86_64 tarball
URL="https://github.com/benbjohnson/litestream/releases/download/v${VERSION}/litestream-${VERSION}-linux-x86_64.tar.gz"

cd "$(dirname "$0")/.."
mkdir -p bin
if [ -x bin/litestream ] && [ "$(bin/litestream version)" = "$VERSION" ]; then
  echo "Litestream $VERSION already installed"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/litestream.tar.gz" "$URL"
echo "$SHA256  $tmp/litestream.tar.gz" | sha256sum -c -
tar -xzf "$tmp/litestream.tar.gz" -C "$tmp" litestream
install -m 0755 "$tmp/litestream" bin/litestream
echo "Installed Litestream $(bin/litestream version) to bin/litestream"
