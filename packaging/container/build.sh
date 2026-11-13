#!/bin/bash
# Assemble /opt/hirdir at its final path and pack it with dpkg-deb, inside the clean
# builder container. packaging/build-deb.sh runs this; do not run it on a host,
# because it installs into /opt/hirdir.
#
# Inputs:
#   /in/source.tar        the source tree, with examples, and src/hirdir/static and html when built
#   HIRDIR_VERSION        the version, as "make -s version" prints it
#   SOURCE_DATE_EPOCH     the time every packaged file is given
#   HOST_UID, HOST_GID    the owner of the file written to /out
# Output: /out/hirdir_<version>_amd64.deb and /out/hirdir_<version>_amd64.lintian.txt
set -euo pipefail

: "${HIRDIR_VERSION:?}" "${SOURCE_DATE_EPOCH:?}"
export SOURCE_DATE_EPOCH
# No stray byte-code while hirdir itself runs below; the package ships none.
export PYTHONDONTWRITEBYTECODE=1
export UV_PYTHON_INSTALL_DIR=/build/python UV_NO_PROGRESS=1 UV_LINK_MODE=copy
# The interpreter is downloaded only when asked for, and its archive is kept in the
# cache volume beside the wheels.
export UV_PYTHON_DOWNLOADS=manual UV_PYTHON_CACHE_DIR=/root/.cache/uv/python-downloads

OPT=/opt/hirdir
PY=$OPT/python/bin/python3
VENV_PY=$OPT/venv/bin/python
SRC=/build/src
STAGE=/build/stage
NAME=hirdir_${HIRDIR_VERSION}_amd64
PYVER=""  # from .python-version, such as 3.15.2
PYMINOR="" # its first two parts, such as 3.15

log() { printf '==> %s\n' "$*"; }
die() {
    printf 'build.sh: %s\n' "$*" >&2
    exit 1
}

unpack_source() {
    mkdir -p "$SRC" /build/out "$OPT"
    tar -xf /in/source.tar -C "$SRC"
    cd "$SRC"
    local stated
    stated=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/hirdir/__init__.py)
    [ "$stated" = "$HIRDIR_VERSION" ] || die "src/hirdir/__init__.py says $stated, not $HIRDIR_VERSION"
    PYVER=$(tr -d '[:space:]' <.python-version)
    [[ $PYVER =~ ^3\.[0-9]+\.[0-9]+$ ]] || die ".python-version must name one release, not '$PYVER'"
    PYMINOR=${PYVER%.*}
}

install_python() {
    # uv takes the interpreter from python-build-standalone and verifies its checksum.
    log "installing CPython $PYVER into $OPT/python"
    uv python install --no-bin "$PYVER"
    local found installed
    found=$(uv python find --managed-python "$PYVER")
    installed=$(dirname "$(dirname "$(readlink -f "$found")")")
    mv "$installed" "$OPT/python"
    # uv writes the directory it installed into in the interpreter's build settings,
    # and nowhere else. They must name the directory the package installs.
    sed -i "s|$installed|$OPT/python|g" "$OPT"/python/lib/python*/_sysconfigdata_*.py
    local lib=$OPT/python/lib stdlib=$OPT/python/lib/python$PYMINOR
    # Tk and IDLE need a display. Headers, the config directory, the *-config scripts
    # and libpython serve building and embedding only. The interpreter's own pip goes
    # too, so that packages enter through the locked virtual environment alone.
    rm -rf "$stdlib"/{idlelib,tkinter,turtledemo,turtle.py,ensurepip} \
        "$stdlib"/lib-dynload/_tkinter.* "$lib"/{tcl,tk,itcl,thread}* "$lib"/lib{tcl,tk}* \
        "$lib/pkgconfig" "$lib"/libpython3* "$stdlib"/config-"$PYMINOR"-* \
        "$OPT/python/include" "$OPT/python/share" "$stdlib"/site-packages/pip* \
        "$OPT/python/bin"/{idle,pip,pydoc}* "$OPT/python/bin"/python*-config "$OPT/python/BUILD"
    [ "$("$PY" -c 'import platform; print(platform.python_version())')" = "$PYVER" ] ||
        die "the interpreter in $OPT/python is not $PYVER"
}

install_venv() {
    log "creating $OPT/venv with the locked dependencies and the hirdir wheel"
    # Created where it will be installed, so no path in it needs changing afterwards.
    uv venv --quiet --no-project --python "$PY" "$OPT/venv"
    # A relative link to the interpreter, which holds wherever the tree is unpacked
    # to be looked at. pyvenv.cfg names /opt/hirdir/python, where it will be installed.
    ln -sfn ../../python/bin/python3 "$OPT/venv/bin/python"
    uv export --quiet --frozen --no-dev --no-emit-project --format requirements.txt \
        --python "$PY" --output-file /build/requirements.txt
    # Every dependency comes as a wheel whose hash is in uv.lock. Nothing is compiled.
    uv pip install --quiet --python "$VENV_PY" --require-hashes --only-binary :all: --no-deps \
        -r /build/requirements.txt
    uv build --quiet --wheel --python "$PY" --out-dir /build/wheel
    # --no-index and --find-links: the wheel is installed by name, so that no record
    # of where it was built is kept. --no-cache: a wheel of the same version from an
    # earlier build must never stand in for this one.
    uv pip install --quiet --python "$VENV_PY" --no-deps --no-index --no-cache \
        --find-links /build/wheel "hirdir==$HIRDIR_VERSION"
    local site=$OPT/venv/lib/python$PYMINOR/site-packages
    # The installed package must be exactly what is in src/ now, web UI included.
    diff -rq --exclude=__pycache__ src/hirdir "$site/hirdir" ||
        die "the packaged hirdir differs from src/hirdir"
    # What only uv or a development checkout uses: the lock, the ignore file, the
    # activation scripts, and uv's own record of each install.
    rm -f "$OPT/venv/.lock" "$OPT/venv/.gitignore" "$OPT/venv/CACHEDIR.TAG" \
        "$OPT"/venv/bin/activate* "$OPT/venv/bin/deactivate.bat" "$OPT/venv/bin/pydoc.bat"
    find "$site" -name uv_cache.json -delete
    find "$site" -name RECORD -exec sed -i '/\/uv_cache\.json,/d' {} +
    # Nothing but hirdir and what the lock names for running it. A package of the
    # development or the documentation group here would be shipped to every host.
    local installed extra
    installed=$(uv pip freeze --python "$VENV_PY")
    grep -qx "hirdir==$HIRDIR_VERSION" <<<"$installed" ||
        die "uv pip freeze does not list hirdir $HIRDIR_VERSION in $OPT/venv"
    extra=$(comm -23 \
        <(grep -v '^hirdir==' <<<"$installed" | LC_ALL=C sort) \
        <(grep -oE '^[A-Za-z0-9][A-Za-z0-9._-]*==[^ ;\\]+' /build/requirements.txt | LC_ALL=C sort))
    [ -z "$extra" ] ||
        die "the environment holds what the lock does not name for running hirdir: $extra"
}

check_web_ui() {
    local static=$OPT/venv/lib/python$PYMINOR/site-packages/hirdir/static reference
    if [ ! -f "$static/index.html" ]; then
        log "WARNING: src/hirdir/static was not built, so this package has NO WEB UI"
        return
    fi
    log "checking the web UI: the base tag, and every file the page names"
    # The server writes the URL prefix into this tag, exactly as it is spelled here.
    grep -qF '<base href="/" />' "$static/index.html" ||
        die "the web UI's index.html lacks <base href=\"/\" />, which the server rewrites"
    while read -r reference; do
        case $reference in
            /*) die "the web UI's index.html names $reference, which breaks under a URL prefix" ;;
        esac
        [ -f "$static/${reference#./}" ] ||
            die "the web UI's index.html names $reference, which is not in the package"
    done < <(grep -oE '(src|href)="[^":]*[^":/]"' "$static/index.html" | sed -E 's/^[a-z]+="//; s/"$//')
}

smoke_test() {
    log "smoke test: the command runs and every bundled module loads"
    [ "$("$OPT/venv/bin/hirdir" version)" = "$HIRDIR_VERSION" ] ||
        die "the installed hirdir is not $HIRDIR_VERSION"
    "$VENV_PY" - <<'PY'
import importlib
import pathlib
import sys

version = f"python{sys.version_info.major}.{sys.version_info.minor}"
dynload = pathlib.Path(sys.base_exec_prefix, "lib", version, "lib-dynload")
extensions = sorted(path.name.split(".")[0] for path in dynload.glob("*.so"))
# Most extensions are built into the interpreter; these cover its static libraries.
builtin = ["ssl", "sqlite3", "ctypes", "zlib", "bz2", "lzma", "decimal", "zoneinfo", "tomllib"]
ours = ["hirdir.app", "hirdir.cli.main", "hirdir.db.migrate", "argon2", "uvicorn", "alembic"]
# Every compiled module a wheel brought, by the name it is imported under. Each one
# must be the build for this interpreter, or it does not load.
site = pathlib.Path(sys.prefix, "lib", version, "site-packages")
compiled = sorted(
    ".".join([*path.relative_to(site).parts[:-1], path.name.split(".")[0]])
    for path in site.rglob("*.so")
)
for name in [*extensions, *builtin, *ours, *compiled]:
    importlib.import_module(name)
count = len(extensions) + len(builtin) + len(ours)
print(f"imported {count} modules on Python {sys.version}")
print(f"imported the {len(compiled)} compiled modules of the wheels: {', '.join(compiled)}")

# The engine behind the regular expressions of the filter grammar, with its time limit.
import regex

if "regex._regex" not in compiled:
    sys.exit("the regex package has no compiled module in this environment")
if not regex.search("^site2-sw-(core|dist)-[0-9]+$", "site2-sw-core-01", timeout=0.05):
    sys.exit("the regex package does not match as it should")
PY
    # hirdir-setup is run by this interpreter and uses the standard library alone.
    "$VENV_PY" -I packaging/hirdir_setup.py --help >/dev/null
}

stage_files() {
    log "staging the package tree"
    rm -rf "$STAGE"
    mkdir -p "$STAGE/DEBIAN" "$STAGE/opt" "$STAGE/usr/bin"
    find "$OPT" -depth -type d -name __pycache__ -exec rm -rf {} +
    cp -a "$OPT" "$STAGE/opt/hirdir"
    ln -s /opt/hirdir/venv/bin/hirdir "$STAGE/usr/bin/hirdir"
    install -Dm755 packaging/hirdir_setup.py "$STAGE/usr/sbin/hirdir-setup"
    # The settings file is not a conffile either. A release that adds a setting ships a
    # different file, and dpkg would ask every site that had edited its own. The package
    # ships the text here, and postinst has "hirdir-setup --settings" write
    # /etc/hirdir/config.toml from it on a first install and, at an upgrade, put the
    # settings that file lacks into it, commented out, changing nothing the site set.
    install -Dm644 packaging/config.toml "$STAGE/usr/share/hirdir/config.toml"
    install -d "$STAGE/etc/hirdir"
    install -Dm644 packaging/nginx/upstream.conf "$STAGE/etc/nginx/conf.d/hirdir.conf"
    # The snippet that holds the URL prefix is not a conffile: hirdir-setup rewrites its
    # prefix, and dpkg would ask about every such file at each upgrade that changes the
    # snippet. The package ships the text here, and postinst has "hirdir-setup --renew"
    # write /etc/nginx/snippets/hirdir.conf from it with the prefix that file has. The
    # directory is shipped, so that it is there on a host that has no nginx yet.
    install -Dm644 packaging/nginx/snippet.conf "$STAGE/usr/share/hirdir/nginx/snippet.conf"
    install -d "$STAGE/etc/nginx/snippets"
    local units=$STAGE/usr/lib/systemd/system
    install -Dm644 -t "$units" packaging/systemd/hirdir.service \
        packaging/systemd/hirdir-backup.service packaging/systemd/hirdir-backup.timer

    local doc=$STAGE/usr/share/doc/hirdir
    install -Dm644 packaging/debian/copyright "$doc/copyright"
    install -Dm644 packaging/debian/lintian-overrides "$STAGE/usr/share/lintian/overrides/hirdir"
    local maintainer
    maintainer=$(sed -n 's/^Maintainer: //p' packaging/debian/control)
    printf '%s\n' "hirdir ($HIRDIR_VERSION) unstable; urgency=medium" "" \
        "  * Release $HIRDIR_VERSION." "" \
        " -- $maintainer  $(date -u -R -d "@$SOURCE_DATE_EPOCH")" |
        gzip -9 --no-name >"$doc/changelog.gz"
    # The fictional inventory of examples/, as CSV and as JSON: something to try an
    # import with, and the columns of each kind of record to start a file of one's own.
    # Its README is among the HTML pages, as examples/index.html.
    local examples=(examples/*.csv examples/*.json)
    [ -f "${examples[0]}" ] || die "there is no examples/ directory with its CSV files"
    install -Dm644 -t "$doc/examples" "${examples[@]}"
    if [ -f html/index.html ]; then
        cp -r html "$doc/html"
        # A marker for the site that publishes these pages; it means nothing here.
        rm -f "$doc/html/.nojekyll"
    else
        log "NOTE: there is no html/ directory, so the package has no HTML documentation (make docs)"
    fi
}

normalize_tree() {
    # The same modes and times whatever the umask and the clock of the build.
    chmod -R u+rwX,go+rX,go-w "$STAGE"
    # Shared libraries are mapped and the modules of the wheels are imported; neither
    # is ever executed. The standard library keeps the modes CPython gives it.
    find "$STAGE" -type f \( -name '*.so' -o -name '*.so.*' \) -exec chmod 0644 {} +
    find "$STAGE/opt/hirdir/venv/lib" -type f -name '*.py' -exec chmod 0644 {} +
    find "$STAGE/usr/share" "$STAGE/etc" -type f -exec chmod 0644 {} +
    find "$STAGE" -exec touch --no-dereference --date="@$SOURCE_DATE_EPOCH" {} +
}

check_tree() {
    log "checking the tree: no byte-code, no build paths, no binary needing a newer glibc"
    local found
    found=$(find "$STAGE" -name __pycache__ -o -name '*.pyc' | head -n 5)
    [ -z "$found" ] || die "byte-code from the build is in the package: $found"
    # /build and /in exist only in this container. grep exits 1 when it finds nothing.
    found=$(grep -rIlE '(^|[^A-Za-z0-9_./-])/(build|in)/(src|stage|wheel|python|out|requirements|source)' \
        "$STAGE" | head -n 5 || true)
    [ -z "$found" ] || die "a path of the build container is in the package: $found"
    local newest
    # readelf exits non-zero for the many files that are not ELF; only its output matters.
    newest=$({ find "$STAGE/opt" -type f -exec readelf -V --wide {} + 2>/dev/null || true; } |
        grep -oE 'Name: GLIBC_[0-9.]+' | sed 's/Name: GLIBC_//' | sort -uV | tail -n 1)
    [ -n "$newest" ] || die "found no ELF file that needs glibc; is readelf installed?"
    log "newest glibc symbol version needed: $newest; the package depends on libc6 (>= $GLIBC)"
    dpkg --compare-versions "$newest" le "$GLIBC" || die "a bundled binary needs glibc $newest"
}

verify_units() {
    log "systemd-analyze verify"
    local out
    out=$(systemd-analyze verify --man=no --recursive-errors=no \
        "$STAGE"/usr/lib/systemd/system/hirdir.service \
        "$STAGE"/usr/lib/systemd/system/hirdir-backup.service \
        "$STAGE"/usr/lib/systemd/system/hirdir-backup.timer 2>&1) ||
        die "systemd-analyze verify failed: $out"
    [ -z "$out" ] || die "systemd-analyze verify reported: $out"
}

write_control() {
    local size
    size=$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)
    sed -e "s/@VERSION@/$HIRDIR_VERSION/" -e "s/@SIZE@/$size/" -e "s/@GLIBC@/$GLIBC/" \
        packaging/debian/control >"$STAGE/DEBIAN/control"
    install -m755 packaging/debian/postinst packaging/debian/prerm packaging/debian/postrm \
        "$STAGE/DEBIAN/"
    # Every file under /etc is a conffile, so that local edits survive an upgrade.
    (cd "$STAGE" && find etc -type f | sed 's|^|/|' | LC_ALL=C sort) >"$STAGE/DEBIAN/conffiles"
    (cd "$STAGE" && find . -path ./DEBIAN -prune -o -type f -printf '%P\0' |
        LC_ALL=C sort -z | xargs -0 md5sum) >"$STAGE/DEBIAN/md5sums"
    chmod 0644 "$STAGE/DEBIAN/control" "$STAGE/DEBIAN/conffiles" "$STAGE/DEBIAN/md5sums"
    find "$STAGE/DEBIAN" -exec touch --date="@$SOURCE_DATE_EPOCH" {} +
}

package_and_lint() {
    local deb=/build/out/$NAME.deb report=/build/out/$NAME.lintian.txt status=0
    log "dpkg-deb --build -> $NAME.deb"
    dpkg-deb --build --root-owner-group -Zxz "$STAGE" "$deb" >/dev/null
    log "lintian"
    # lintian warns when it is run as root; it only needs to read the package.
    chmod 0644 "$deb"
    runuser -u nobody -- env HOME=/tmp lintian --fail-on error --tag-display-limit 0 \
        --show-overrides --info "$deb" >"$report" 2>&1 || status=$?
    # The full report goes beside the package: every tag raised (E, W) or overridden
    # (O), with lintian's explanation of each. Here: how often each tag appears.
    grep -E '^[EWIPXO]: ' "$report" | sed -E 's/^(.: [^:]+: [^ ]+).*/\1/' | sort | uniq -c || true
    cp "$report" /out/
    chown "${HOST_UID:-0}:${HOST_GID:-0}" "/out/$NAME.lintian.txt"
    [ "$status" -eq 0 ] ||
        die "lintian reported errors, so no package was written; see $NAME.lintian.txt"
    if ! grep -Eq '^[EW]: ' "$report"; then
        log "lintian: no error and no warning beyond the overrides in packaging/debian/lintian-overrides"
    fi
    cp "$deb" /out/
    chown "${HOST_UID:-0}:${HOST_GID:-0}" "/out/$NAME.deb"
    log "built $NAME.deb ($(du -h "$deb" | cut -f1))"
}

# The glibc of this container: the package is built against it and asks for no older.
GLIBC=$(dpkg-query -W -f '${Version}' libc6 | sed 's/-.*//')

unpack_source
install_python
install_venv
check_web_ui
smoke_test
stage_files
normalize_tree
check_tree
verify_units
write_control
package_and_lint
