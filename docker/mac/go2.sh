#!/bin/bash
# Run from any directory on the Mac. No Git commands or robot commands here.
set -euo pipefail
mac_dir="$(cd "$(dirname "$0")" && pwd)"
compose=(docker compose -f "$mac_dir/compose.yaml")
action="${1:-help}"
if [ "$#" -gt 0 ]; then shift; fi
if [ "$action" = help ]; then
    echo "Usage: bash docker/mac/go2.sh {auth|build|check|up|shell|rviz|rebuild <package>|logs|status|down}"
    exit 0
fi
if [ "$action" = auth ]; then exec bash "$mac_dir/mac-xauth.sh"; fi
if ! docker info >/dev/null 2>&1; then
    echo "Start Docker Desktop on the Mac, then retry." >&2
    exit 1
fi
case "$action" in
    build) "${compose[@]}" build "$@" ;;
    check) "${compose[@]}" run --rm unitree_ros true ;;
    up) bash "$mac_dir/mac-xauth.sh"; "${compose[@]}" up -d "$@" ;;
    shell) "${compose[@]}" exec unitree_ros bash ;;
    rviz) "${compose[@]}" exec unitree_ros bash -ic '
        if [ ! -f /root/.rviz2/fusion-sensors.rviz ]; then
            cp /ros2_ws/src/docker/mac/rviz-sensors.rviz /root/.rviz2/fusion-sensors.rviz
        fi
        exec mac-gui rviz2 -d /root/.rviz2/fusion-sensors.rviz' ;;
    rebuild)
        if [ "$#" -eq 0 ]; then echo "Specify a package to rebuild." >&2; exit 2; fi
        "${compose[@]}" exec unitree_ros bash -ic 'cbs "$@"' bash "$@" ;;
    logs) "${compose[@]}" logs --tail=40 "$@" ;;
    status) "${compose[@]}" ps "$@" ;;
    down) "${compose[@]}" down "$@" ;;
    *) echo "Unknown action: $action. Run with help for the commands." >&2; exit 2 ;;
esac
