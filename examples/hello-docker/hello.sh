#!/bin/sh
# Prints a line every 5 s; stops cleanly on SIGTERM (aember's graceful stop).
trap 'echo "hello-docker: stopping"; exit 0' TERM INT
echo "hello-docker: up on $(uname -m), net: $(ls /sys/class/net | tr '\n' ' ')"
while :; do
  echo "hello-docker: hello from ${GREETING:-aember} at $(date +%T)"
  sleep 5 &
  wait $!
done
