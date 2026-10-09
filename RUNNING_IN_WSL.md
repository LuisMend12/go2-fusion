# Running the container from inside WSL2 (with a display)

There are two ways to run this repo's Docker container on Windows:

- **From Windows directly**, via `docker-compose.windows.yml` — see
  [WINDOWS_SETUP.md](WINDOWS_SETUP.md). Simpler, but no GUI windows (RViz,
  `go2_map_viewer_cpp`, the Julia viewer).
- **From inside WSL2**, via the default `docker/docker-compose.yml` — this
  file. More setup, but GUI windows show up on your Windows desktop via
  WSLg, the same mechanism Linux GUI apps on WSL2 always use.

Use this path specifically when you need one of the GUI tools. For
everything else (keyboard control, auto-mapping, Foxglove), the Windows
path in WINDOWS_SETUP.md is simpler and this isn't needed.

## One-time setup

1. **WSL2 with a Linux distro.** This repo was set up against
   `Ubuntu-22.04`:
   ```powershell
   wsl --install -d Ubuntu-22.04
   ```
   (Already done on this machine — `wsl -l -v` should show it.)

2. **Docker Desktop's WSL integration for that distro.** This is the step
   that's easy to miss: Docker Desktop → Settings → Resources → WSL
   Integration → enable the toggle next to `Ubuntu-22.04` → Apply &
   Restart. Without this, the `docker` CLI isn't even reachable from
   inside the distro — you'll see `docker info` hang or fail there even
   though it works fine from Windows PowerShell.

   Verify it worked:
   ```shell
   wsl -d Ubuntu-22.04
   docker info
   ```
   If that returns real output (not a connection error), you're set.

3. Nothing else — WSLg (the X11/GUI forwarding) ships with WSL2 by
   default on Windows 11 and recent Windows 10 updates. You don't install
   or configure it separately; it's what already makes RViz work if
   you've used a native (non-Docker) ROS install in this same distro.

## Build and run

All commands below run **inside the WSL shell**, not Windows PowerShell —
that's what makes the X11 socket path (`/tmp/.X11-unix`) resolve to
WSLg's, instead of nothing.

```shell
wsl -d Ubuntu-22.04
cd "/mnt/g/broswer download/go2_ros2_sdk/docker"
docker compose build        # first time only; slow (ROS deps, torch, open3d)
docker compose up -d
docker compose logs -f unitree_ros   # Ctrl+C to stop following, container keeps running
```

Success looks like `Robot 0 validated and ready`.

Open a shell in the running container to run tools:
```shell
docker compose exec unitree_ros bash
```

Stop it:
```shell
docker compose down
```

## Verifying the display actually works

Quick sanity check before trying one of the real tools:
```shell
docker compose exec unitree_ros bash -ic "ros2 run go2_map_viewer_cpp map_viewer_node"
```
A window titled "Go2 Map Viewer" should appear on your Windows desktop
(check the taskbar — WSLg windows sometimes open behind others, not
always on top). If it doesn't, see Troubleshooting below.

For the full list of tools and their commands, see
[RUNNING_TOOLS.md](RUNNING_TOOLS.md).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker: command not found`, or `docker info` hangs/errors inside WSL | WSL integration toggle (step 2 above) isn't enabled, or Docker Desktop needs restarting after enabling it. |
| Window never appears, no error either | Check `echo $DISPLAY` inside the container — should be non-empty. If empty, the `DISPLAY` env var didn't make it from the host; restart the WSL shell and retry (WSLg sets this per-session). |
| `cannot open display` / X11 connection errors | `~/.Xauthority` may not exist yet on the host. Run any GUI app once outside Docker first (e.g. `xeyes` if installed, or just open a native app) to let WSLg create it, then retry. |
| Robot won't connect (`con_notify` timeout) | Same cause as the Windows path — PC isn't on the robot's Wi-Fi (`isl2`), or the Unitree app is still connected. Not specific to running via WSL. |
| Works in Windows path but not here, or vice versa | The two paths use different compose files and are otherwise independent — a container started one way doesn't affect the other. Only one can hold the robot's WebRTC connection at a time, though, so stop one before starting the other. |
