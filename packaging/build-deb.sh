#!/bin/bash
# Build dist/hirdir_<version>_amd64.deb in a clean ubuntu:26.04 container, with
# dpkg-deb, and check it with lintian. "make deb" runs this after "make web".
# It needs docker and make.
#
# Usage: packaging/build-deb.sh [OUTPUT_DIR]        (default: dist)
# Environment:
#   HIRDIR_UV_CACHE   the docker volume that keeps uv's downloads between builds
#                     (default: hirdir-uv-cache; set it empty to use none). Every
#                     download is checked against a hash, so the cache cannot change
#                     what is built.
#
# The container is given the files the build reads and nothing else: the Python
# source with the built web UI in src/hirdir/static, the lock, packaging/, examples/, and
# the HTML documentation in html/ when "make docs" has produced it. packaging/container/
# build.sh does the work there, and writes lintian's full report beside the package.
# The package's SHA-256 is written beside it as well, as <package>.sha256.
#
# Packages of other versions in OUTPUT_DIR are left alone: the package test upgrades
# from the previous release's package, which it looks for there.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
out_dir=${1:-dist}
mkdir -p "$out_dir"
out_dir=$(cd "$out_dir" && pwd)
cache=${HIRDIR_UV_CACHE-hirdir-uv-cache}

version=$(make -s version)
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "build-deb: 'make -s version' printed '$version', which is not a version" >&2
    exit 1
}
name=hirdir_${version}_amd64

# The time given to every packaged file: that of the last commit, so that two builds
# of one commit agree, or now where there is no commit to ask.
epoch=$(git log -1 --format=%ct 2>/dev/null || date +%s)

paths=(.python-version .gitignore pyproject.toml uv.lock README.md src packaging examples)
if [ -f src/hirdir/static/index.html ]; then
    web_ui="with the web UI"
else
    web_ui="WITHOUT the web UI"
    echo "build-deb: WARNING: src/hirdir/static/index.html does not exist." >&2
    echo "build-deb: WARNING: this package will have NO WEB UI. Run 'make web' first, or 'make deb'." >&2
fi
if [ -f html/index.html ]; then
    paths+=(html)
else
    echo "build-deb: note: html/ does not exist, so the package gets no HTML documentation (make docs)." >&2
fi

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
tar --create --file="$stage/source.tar" --exclude=__pycache__ --exclude='*.pyc' \
    --exclude=.pytest_cache --exclude=.ruff_cache "${paths[@]}"
cp packaging/container/build.sh "$stage/build.sh"

# A unique tag, so that two builds at once do not replace each other's image. The
# layers are cached, so only the first build on a host installs anything.
image=hirdir-deb-builder:$$-$RANDOM
trap 'rm -rf "$stage"; docker image rm --force "$image" >/dev/null 2>&1 || true' EXIT
uv_version=$(uv --version | awk '{print $2}')
docker build --quiet --tag "$image" --build-arg "UV_VERSION=$uv_version" - \
    <packaging/container/Dockerfile.build >/dev/null

cache_mount=()
if [ -n "$cache" ]; then cache_mount=(--volume "$cache:/root/.cache/uv"); fi
rm -f "$out_dir/$name.deb" "$out_dir/$name.deb.sha256" "$out_dir/$name.lintian.txt"
echo "build-deb: building $name.deb $web_ui"
docker run --rm \
    --volume "$stage:/in:ro" --volume "$out_dir:/out" "${cache_mount[@]}" \
    --env HIRDIR_VERSION="$version" --env SOURCE_DATE_EPOCH="$epoch" \
    --env HOST_UID="$(id -u)" --env HOST_GID="$(id -g)" \
    "$image" bash /in/build.sh

# The checksum that is attached to the release with the package, in the form that
# "sha256sum --check" reads. The package test of the next release, which upgrades from
# this package, compares the two.
(cd "$out_dir" && sha256sum "$name.deb" >"$name.deb.sha256")

echo "build-deb: $out_dir/$name.deb ($(du -h "$out_dir/$name.deb" | cut -f1), $web_ui)"
echo "build-deb: SHA-256 $(cut -d' ' -f1 "$out_dir/$name.deb.sha256"), in $name.deb.sha256"
echo "build-deb: lintian's full report is in $out_dir/$name.lintian.txt"
