# go2_map_viewer_julia

Live map dashboard written in Julia. It draws the SLAM map as a heatmap and
the robot's position in the map frame, using GLMakie. It is read-only: it
does not send navigation goals. The C++ viewer does that.

Julia has no `rclcpp` equivalent here, so this is not a colcon package and
it is not in the package table in [AGENTS.md](../AGENTS.md). It talks to
ROS 2 through `rosbridge_server` (JSON over WebSocket).

## What you need running first

- The robot stack, with SLAM publishing `/map` and TF publishing
  `map` → `odom` and `odom` → `base_link`.
  `ros2 launch go2_robot_sdk robot.launch.py` does this (`slam` defaults
  to true).
- `rosbridge_server`, started separately (commands below). The script
  connects to `ws://localhost:9090`.
- A display. Same rule as the C++ viewer: WSLg, or the Linux compose file
  which forwards X11. It will not open under
  `docker/docker-compose.windows.yml`. Use Foxglove there; see
  [WINDOWS_SETUP.md](../docs/WINDOWS_SETUP.md).

The first launch compiles GLMakie. That can take several minutes and looks
idle. Later launches are quick.

## Run it in Docker (Linux compose file, display forwarded)

Start the stack first (`docker compose up` from `docker/`). In a second
terminal, start rosbridge. It is installed in the image and is not started
by the entrypoint:

```shell
cd docker
docker compose exec unitree_ros bash -ic \
  "ros2 launch rosbridge_server rosbridge_websocket_launch.xml"
```

In a third terminal, run the viewer. Dependencies are baked into the image
at `/opt/go2_map_viewer_julia`. The script itself is the live-mounted file,
so editing `map_viewer.jl` does not need an image rebuild:

```shell
cd docker
docker compose exec unitree_ros bash -ic \
  "julia --threads=auto --project=/opt/go2_map_viewer_julia /ros2_ws/src/go2_map_viewer_julia/map_viewer.jl"
```

On a Windows host the command above needs the Linux compose file. Adding
`-f docker-compose.windows.yml` builds and runs the stack, but that
container has no display, so the GLMakie window cannot open.

## Run it in WSL2

rosbridge and the script both have to run inside the same Ubuntu distro,
with the ROS graph already up.

```shell
wsl -d Ubuntu-22.04
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

Another Ubuntu shell:

```shell
cd ~/go2_map_viewer_julia
julia --project=. -e 'import Pkg; Pkg.instantiate()'
julia --threads=auto --project=. map_viewer.jl
```

`Pkg.instantiate()` reads `Project.toml` and `Manifest.toml` and only has
to succeed once per machine (it downloads packages on the first run).
The window should appear on the Windows desktop through WSLg.

If rosbridge is not up yet, the status line says it is retrying. Leave the
window open; it connects on its own once port 9090 answers.

## What the window shows

| Piece | Meaning |
|---|---|
| Heatmap | `/map`. White is free, black is occupied, gray is unknown |
| Red dot | `base_link` in the `map` frame |
| Status line | Connection, map size, or the last rosbridge error |

The dot is placed by walking TF from `base_link` up to `map` (usually
`map` → `odom` → `base_link`), then converting that pose into heatmap
cells. `/odom` alone is not used: that pose is in the `odom` frame and
drifts relative to the map.

If the oldest transform in that chain hasn't updated in over 5 seconds
(e.g. SLAM died but odometry is still publishing), the status line adds
`(STALE: tf chain N.Ns old)` — the dot is still drawn, but don't trust its
position when you see that.

Start Julia with more than one thread (`julia --threads=2 ...`, or set
`JULIA_NUM_THREADS=2`) so a large `/map` message being processed on the
background connection doesn't stall the GLMakie window. With the default
single thread it still works, just cooperatively scheduled, so a very
large map can make the window briefly unresponsive while it's rasterized.

Close the window to quit. The script retries the WebSocket if rosbridge
drops.

## Updating Julia dependencies

Editing `map_viewer.jl` needs no rebuild. Adding a package does:

```shell
cd go2_map_viewer_julia
julia --project=. -e 'import Pkg; Pkg.add("SomePackage")'
```

Commit the updated `Project.toml` and `Manifest.toml`, then
`docker compose build` so the image picks up the new set.
