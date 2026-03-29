#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_VERSION="${1:-$(uname -r)}"
KERNEL_BUILD="/lib/modules/$KERNEL_VERSION/build"
OUT_DIR="$REPO_DIR/test-module"

if [[ ! -d "$KERNEL_BUILD" ]]; then
    echo "Kernel build tree not found: $KERNEL_BUILD" >&2
    exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

cp "$REPO_DIR/oxpec.superx.c" "$OUT_DIR/oxpec_superx.c"

cat > "$OUT_DIR/Makefile" <<EOF_MAKE
obj-m := oxpec_superx.o

all:
	\$(MAKE) -C $KERNEL_BUILD M=\$(CURDIR) modules

clean:
	\$(MAKE) -C $KERNEL_BUILD M=\$(CURDIR) clean
EOF_MAKE

make -C "$OUT_DIR"

echo
echo "Built module:"
echo "  $OUT_DIR/oxpec_superx.ko"
