#!/bin/bash
# End to end: pack both examples with aember-pack, add them to an aember
# checkout's x64 overlay, pack aember and boot it in QEMU; both containers
# must run and print. The overlay is restored afterwards (and re-packed).
#
# Run inside the aember dev container (docker CLI, mksquashfs, the SDK):
#   tests/e2e/aember-qemu.sh [/aember_ws/aember]
set -euo pipefail

HELPER="$(cd "$(dirname "$0")/../.." && pwd)"
AEMBER="${1:-/aember_ws/aember}"
ARCH=x64-poky-linux
OVERLAY="$AEMBER/resources/$ARCH/rootfs"
SDK_ENV="$(ls "$AEMBER"/build/aember-resources/$ARCH/sdk/environment-setup-* | head -1)"
WORK="$HELPER/build/e2e"
LOG="$WORK/boot.log"
export PATH=/venv/bin:$PATH:/usr/sbin

[ -d "$OVERLAY/etc/aember" ] || { echo "no aember overlay at $OVERLAY" >&2; exit 2; }
rm -rf "$WORK" && mkdir -p "$WORK"
cp "$OVERLAY/etc/aember/containers.json" "$WORK/containers.json.orig"

restore() {
  echo "e2e: restoring the aember overlay"
  cp "$WORK/containers.json.orig" "$OVERLAY/etc/aember/containers.json"
  rm -rf "$OVERLAY/var/lib/aember/hello-docker" "$OVERLAY/var/lib/aember/hello-cmake"
  (cd "$AEMBER" && aember app pack >/dev/null 2>&1) || echo "e2e: re-pack failed" >&2
}
trap restore EXIT

echo "e2e: 1/4 hello-docker (Dockerfile → container)"
(cd "$HELPER/examples/hello-docker" && "$HELPER/aember-pack" build -o "$WORK/out")

echo "e2e: 2/4 hello-cmake (aember SDK, CMake, libs from the SDK sysroot)"
(
  set +u  # the SDK's environment scripts use unset variables
  # shellcheck disable=SC1090
  source "$SDK_ENV"
  set -u
  cmake -S "$HELPER/examples/hello-cmake" -B "$WORK/hello-cmake" \
    -DCMAKE_BUILD_TYPE=Release -DAEMBER_BUILD_HELPER="$HELPER" >/dev/null
  cmake --build "$WORK/hello-cmake" --target hello-cmake-aember-container
)
cp -r "$WORK/hello-cmake/aember-out/hello-cmake" "$WORK/out/"

echo "e2e: 3/4 install into $OVERLAY, aember app pack"
for name in hello-docker hello-cmake; do
  m="$HELPER/examples/$name/aember-container.json"
  "$HELPER/aember-pack" install -m "$m" -o "$WORK/out" "$AEMBER"
done
(cd "$AEMBER" && aember app pack >/dev/null)

echo "e2e: 4/4 boot in QEMU (100 s); the debug shell prints the containers' logs"
(
  sleep 70
  printf d
  sleep 5
  D=/var/log/aember-container-hello-docker.log C=/var/log/aember-container-hello-cmake.log
  printf 'head -n 1 %s; tail -n 2 %s; tail -n 2 %s; exit\n' "$D" "$D" "$C"
  sleep 40
) | (cd "$AEMBER" && timeout 160 aember app launch --headless --timeout 100) >"$LOG" 2>&1 || true
CLEAN="$WORK/boot.clean.log"
sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$LOG" | tr -d '\r' >"$CLEAN"

fail=0
check() {
  if grep -a -q -- "$1" "$CLEAN"; then echo "  ok   $2"; else echo "  FAIL $2"; fail=1; fi
}
check "Container 'hello-docker' started successfully" "hello-docker started"
check "Container 'hello-cmake' started successfully" "hello-cmake started"
check "hello-docker \[running\] (container)" "hello-docker running (heartbeat)"
check "hello-cmake \[running\] (container)" "hello-cmake running (heartbeat)"
check "hello-docker: hello from a Dockerfile" "hello-docker's output (console log)"
check "hello-docker: up on x86_64, net: .*eth0" "hello-docker sees aember's network (host)"
check "hello-cmake: hello #[0-9]* from CMake" "hello-cmake's output (C++23, SDK libraries)"
if grep -a -q "Container 'hello-.*' .*exited unexpectedly" "$CLEAN"; then
  echo "  FAIL a hello container exited"; fail=1
fi
echo "e2e: boot log: $LOG"
exit $fail
