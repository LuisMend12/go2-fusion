# Running the keyboard controller and the map visualizers

Quick reference for the two interactive tools built on top of this repo.
Both need the main robot stack already running and connected — see
[WINDOWS_SETUP.md](WINDOWS_SETUP.md) for that part. Full details for each
tool are in its own package README, linked below; this file is just the
copy-paste version.

## Keyboard controller

No display needed — works through `docker-compose.windows.yml` as-is.

```powershell
cd docker
docker compose -f docker-compose.windows.yml exec unitree_ros bash -ic "ros2 run keyboard_teleop keyboard_teleop"
```

Controls: `W`/`S` forward-back, `A`/`D` turn, `Q`/`E` strafe, `Z`/`X` speed
down/up, `Space` stop, `Esc` quit. Full details: [keyboard_teleop/README.md](../src/keyboard_teleop/README.md).

## Map visualizers (C++ and Julia)

These open a window, which `docker-compose.windows.yml` can't show (no
display forwarding). They need:

1. **Docker Desktop's WSL integration enabled**, one-time: Docker Desktop →
   Settings → Resources → WSL Integration → enable the toggle for
   `Ubuntu-22.04` → Apply & Restart. Without this, `docker` isn't even
   reachable from inside WSL.
2. Running through the **default** `docker/docker-compose.yml` (not the
   Windows one), from **inside** a WSL2 shell — that's what provides the
   X11 socket (via WSLg) the container needs for a window to actually
   appear on your Windows desktop.

```powershell
wsl -d Ubuntu-22.04
```

Then, inside that shell:

```shell
cd "/mnt/g/broswer download/go2_ros2_sdk/docker"
docker compose up -d
```

**C++ viewer** — click the map to send a Nav2 goal, `C`/`Esc` to cancel:
```shell
docker compose exec unitree_ros bash -ic "ros2 run go2_map_viewer_cpp map_viewer_node"
```
Details: [go2_map_viewer_cpp/README.md](../src/go2_map_viewer_cpp/README.md).

**Julia viewer** — read-only map heatmap with an approximate robot marker.
Start `rosbridge_server` first (not started automatically), then the
viewer itself:
```shell
docker compose exec unitree_ros bash -ic "ros2 launch rosbridge_server rosbridge_websocket_launch.xml"
```
```shell
docker compose exec unitree_ros bash -ic "julia --project=/opt/go2_map_viewer_julia /ros2_ws/src/go2_map_viewer_julia/map_viewer.jl"
```
Details, including the odom-vs-map-frame caveat: [go2_map_viewer_julia/README.md](../go2_map_viewer_julia/README.md).

**No GUI integration yet?** Foxglove works either way, no WSL toggle
needed — see the "View the data" section of [WINDOWS_SETUP.md](WINDOWS_SETUP.md).
It won't let you click-to-navigate like the C++ viewer does, but it shows
the same map and sensor data.

## Autonomous mapping

Not a display tool, but commonly run alongside these — drives the robot
on its own via Nav2 while building the SLAM map. Only run it when you're
physically present and watching the robot:

```shell
docker compose exec unitree_ros bash -ic "ros2 run go2_auto_mapper explorer"
```
Details: [go2_auto_mapper/README.md](../src/go2_auto_mapper/README.md).
