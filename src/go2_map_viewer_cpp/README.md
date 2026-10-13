# go2_map_viewer_cpp

Interactive C++ map viewer. Opens an SFML window with the live SLAM map and
the robot's position. Click a cell to send the robot there through Nav2, or
cancel the goal with a key press.

This is a learning/demo project, not a replacement for RViz or Foxglove. It
shows the map, the robot, click-to-navigate, and cancel. It does not show
the camera or the point cloud.

## What you need running first

- The robot stack, with SLAM publishing `/map` and Nav2 offering
  `/navigate_to_pose`. `ros2 launch go2_robot_sdk robot.launch.py` does both
  (`slam` defaults to true).
- A display. WSLg provides one on Windows 11 with WSL2. The Linux compose
  file (`docker/docker-compose.yml`) forwards X11. The Windows compose file
  (`docker/docker-compose.windows.yml`) has no display, so this window
  cannot open there. Use Foxglove for that setup; see
  [WINDOWS_SETUP.md](../WINDOWS_SETUP.md).

SFML comes from the `sfml-dev` rosdep key in `package.xml`. The Docker image
and `rosdep install --from-paths src --ignore-src -y` install it. Do not
`apt-get install` it by hand.

## Run it in WSL2

From PowerShell:

```powershell
wsl -d Ubuntu-22.04
```

Then, in Ubuntu, after the stack is up and the workspace has been built once:

```shell
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 run go2_map_viewer_cpp map_viewer_node
```

A window titled "Go2 Map Viewer" should show up on the Windows desktop.
"Waiting for map..." means `/map` is not being published yet.

## Run it in Docker (Linux compose file, display forwarded)

The container has to already be running (`docker compose up` from `docker/`).

```shell
cd docker
docker compose exec unitree_ros bash -ic \
  "ros2 run go2_map_viewer_cpp map_viewer_node"
```

## Controls

| Input | Action |
|---|---|
| Left-click on the map | Send a Nav2 goal to that point |
| Click on the dark border or the hint text | Nothing |
| `C` or `Esc` | Cancel the current navigation goal |
| Close the window | Quit |

The map is scaled to fit the window, including maps larger than the
window. Resizing the window scales the map with it. Clicks use that same
scale, including on a high-DPI display.

## How it works

- Subscribes to `/map` (`nav_msgs/OccupancyGrid`) with latched QoS
  (`transient_local`, `reliable`), so a map published before the viewer
  started is still received. Cells are white when free, black when occupied,
  and gray when unknown.
- Looks up `map` → `base_link` with tf2 and draws the robot as a red dot.
- On click, converts that pixel back into the `map` frame and sends a
  `NavigateToPose` goal on `/navigate_to_pose`, the same action RViz's
  "Nav2 Goal" tool uses.
- ROS spins on a background thread. The SFML loop runs on the main thread
  at up to 30 FPS. The view stays in window pixels, which is the coordinate
  space SFML mouse events use.

## Rebuild after a C++ change

Python packages in this repo hot-reload. This one does not.

WSL2:

```shell
cd ~/ros2_ws
colcon build --packages-select go2_map_viewer_cpp
source install/setup.bash
```

Docker, from `docker/`. On a Windows host add `-f docker-compose.windows.yml`.
Building inside that container works; opening the window still needs a display.

```shell
docker compose exec unitree_ros bash -ic "cbs go2_map_viewer_cpp"
```

`cbs` is the container alias for `colcon build --packages-select`.
