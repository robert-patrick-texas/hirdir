#!/bin/bash
# Make a copy of a hirdir package under another version number, for trying the records
# of a release against itself with the package test, before there is a later release:
#
#   scripts/relabel_deb.sh dist/hirdir_0.7.0_amd64.deb 0.7.1 /tmp/later
#   PREVIOUS_DEB=dist/hirdir_0.7.0_amd64.deb DEB=/tmp/later/hirdir_0.7.1_amd64.deb \
#       packaging/package-test.sh --upgrade-alone
#
# Usage: scripts/relabel_deb.sh PACKAGE VERSION OUT_DIR
#
# Only the version changes: in the control file, in hirdir's own __version__, which
# /api/v1/about answers, and in that file's line of md5sums. Everything else is the
# package as it was built, and the copy is built again with dpkg-deb, every file owned
# by root as in the original. It is written with its .sha256 into OUT_DIR, which may not
# be dist/: a package there is taken for a release, by the package test and by make
# facts. See "The previous release's package" in docs/release-process.md.
set -euo pipefail

if [ $# -ne 3 ]; then
    echo "usage: $0 PACKAGE VERSION OUT_DIR" >&2
    exit 2
fi
package=$1
version=$2
out_dir=$3
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "relabel_deb: $version is not a version such as 0.7.1" >&2
    exit 2
}
mkdir -p "$out_dir"
out_dir=$(cd "$out_dir" && pwd)
dist=$(cd "$(dirname "${BASH_SOURCE[0]}")/../dist" 2>/dev/null && pwd || true)
if [ -n "$dist" ] && [ "$out_dir" = "$dist" ]; then
    echo "relabel_deb: not into dist/, where the package would be taken for a release" >&2
    exit 2
fi
out=$out_dir/hirdir_${version}_amd64.deb

tree=$(mktemp -d)
trap 'rm -rf "$tree"' EXIT
dpkg-deb --raw-extract "$package" "$tree/root"
sed -i "s/^Version: .*/Version: $version/" "$tree/root/DEBIAN/control"
init=$(cd "$tree/root" && find opt -path '*/site-packages/hirdir/__init__.py')
[ -n "$init" ] || {
    echo "relabel_deb: $package holds no hirdir/__init__.py" >&2
    exit 1
}
sed -i "s/^__version__ = \".*\"/__version__ = \"$version\"/" "$tree/root/$init"
# The checksum of the one file that changed, in place of the one that was there.
sum=$(cd "$tree/root" && md5sum "$init")
{
    grep -v " $init\$" "$tree/root/DEBIAN/md5sums"
    echo "$sum"
} | sort -k2 >"$tree/md5sums"
mv "$tree/md5sums" "$tree/root/DEBIAN/md5sums"
dpkg-deb --root-owner-group --build "$tree/root" "$out" >/dev/null
(cd "$out_dir" && sha256sum "$(basename "$out")" >"$(basename "$out").sha256")
echo "relabel_deb: $out, hirdir $(dpkg-deb -f "$out" Version) from $(basename "$package")"
