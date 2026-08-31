#!/usr/bin/env bash
# Compiles PyTom's FRM (Fast Rotational Matching) alignment extension --
# _swig_frm.so + libsphkit.so -- and installs it into an existing pytom_env
# conda env. Not needed for stw's classification adapter (which always runs
# noalign); required for `stw align`'s real global-alignment feature.
#
# Why this exists at all: PyTom's own build (`pytomc/compile.py`) silently
# disables this piece ("Compilation of SH Alignment failed! Disable this
# functionality.") on any modern gcc, because the bundled 1997-era
# SpharmonicKit/Situs C source hits implicit-function-declaration and
# tentative-definition errors that pre-GCC-14 toolchains only warned about.
# The fix is a handful of relaxed C flags, not a rewrite -- confirmed by
# building it end-to-end and running a real alignment through it.
#
# Usage:
#   scripts/compile_pytom_frm.sh [conda_env_name]
#
# Defaults to `pytom_env`. Safe to re-run (always starts from a fresh clone).
set -euo pipefail

ENV_NAME="${1:-pytom_env}"
PYTOM_REPO="https://github.com/SBC-Utrecht/PyTom.git"
CFLAGS="-O2 -fPIC -std=gnu89 -fcommon -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion -Wno-return-type -Wno-incompatible-pointer-types"

log() { echo "[compile_pytom_frm] $*"; }

if ! conda env list | grep -qE "^\s*${ENV_NAME}\s"; then
    echo "ACHTUNG: conda env '${ENV_NAME}' not found. Install PyTom first (see docs/install/pytom.md)." >&2
    exit 1
fi

DEST="$(conda run -n "$ENV_NAME" python3 -c 'import pytom, os; print(os.path.join(os.path.dirname(pytom.__file__), "lib"))')"
if [[ ! -d "$DEST" ]]; then
    echo "ACHTUNG: expected PyTom's lib/ dir at $DEST but it doesn't exist -- is PyTom actually installed in '$ENV_NAME'?" >&2
    exit 1
fi
log "target install dir: $DEST"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
log "cloning PyTom into $TMPDIR (only need pytomc/sh_alignment/, --depth 1)"
git clone --depth 1 "$PYTOM_REPO" "$TMPDIR/PyTom" >/dev/null

# The repo root's own package directory is ALSO named "pytom" (PyTom/pytom/...,
# not PyTom/pytomc/... directly) -- easy to get wrong since "PyTom" and "pytom"
# look identical at a glance; verified against the actual clone layout.
PKG_ROOT="$TMPDIR/PyTom/pytom"
SH="$PKG_ROOT/pytomc/sh_alignment"
if [[ ! -d "$SH" ]]; then
    echo "ACHTUNG: $SH not found -- PyTom's source layout may have changed upstream." >&2
    exit 1
fi

log "building SpharmonicKit27 (legendre -> sphere -> shared)"
make -C "$SH/SpharmonicKit27" CFLAGS="$CFLAGS" legendre sphere shared >/dev/null

log "building frm/src (Situs) objects"
make -C "$SH/frm/src" CFLAGS="$CFLAGS" lib >/dev/null

log "regenerating SWIG wrapper + compiling + linking _swig_frm.so"
PY_INCLUDE="$(conda run -n "$ENV_NAME" python3 -c 'import sysconfig; print(sysconfig.get_path("include"))')"
PY_LIBDIR="$(conda run -n "$ENV_NAME" python3 -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
PY_VER="$(conda run -n "$ENV_NAME" python3 -c 'import sysconfig; print("python" + sysconfig.get_config_var("VERSION"))')"
NUMPY_INCLUDE="$(conda run -n "$ENV_NAME" python3 -c 'import numpy; print(numpy.get_include())')"
FFTW_INCLUDE="/usr/include"
FFTW_LIBDIR="/lib64"

pushd "$SH/frm/swig" >/dev/null
conda run -n "$ENV_NAME" swig -python frm.i
conda run -n "$ENV_NAME" gcc $CFLAGS -c frm.c frm_wrap.c \
    -I../src -I"$PY_INCLUDE" -I"$NUMPY_INCLUDE" -I"$FFTW_INCLUDE" -I../../SpharmonicKit27
# $ORIGIN rpath: libsphkit.so ends up copied next to _swig_frm.so in PyTom's own
# lib/ dir below, not on any default search path -- without this the extension
# imports (SWIG symbols resolve fine) but crashes at import time with
# "libsphkit.so: cannot open shared object file".
cc -shared -Wl,-rpath,'$ORIGIN' -L"$PY_LIBDIR" -l"$PY_VER" frm.o frm_wrap.o \
    -L"$FFTW_LIBDIR" -lfftw3 -lm \
    ../src/lib_vio.o ../src/lib_pio.o ../src/lib_std.o ../src/lib_eul.o \
    ../src/lib_pwk.o ../src/lib_vec.o ../src/lib_vwk.o ../src/lib_tim.o \
    -L"$PKG_ROOT/lib" -lsphkit -o _swig_frm.so
popd >/dev/null

log "installing into $DEST"
cp -f "$PKG_ROOT/lib/libsphkit.so" "$DEST/libsphkit.so"
cp -f "$SH/frm/swig/_swig_frm.so" "$DEST/_swig_frm.so"
cp -f "$SH/frm/swig/swig_frm.py" "$DEST/swig_frm.py"

log "verifying import"
conda run -n "$ENV_NAME" python3 -c "import pytom.lib._swig_frm; print('OK: pytom.lib._swig_frm imports cleanly')"
log "done -- stw check-env --package pytom should now show FRM alignment as available"
