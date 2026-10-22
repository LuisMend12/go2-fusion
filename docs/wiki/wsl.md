---
title: WSL and Windows
parent: lab-setup
code: [docs/RUNNING_IN_WSL.md, docs/WINDOWS_SETUP.md]
---

# WSL and Windows

Most of the team uses Windows, and this page shows the two ways to run Oak's container there, so you can pick the simple one or the one that shows RViz windows.

Part of: [Lab setup](lab-setup.md)

## Pick your path

**WSL2** is Linux running inside Windows. **WSLg** is the part of WSL2 that shows Linux app windows on your Windows desktop; it ships with Windows 11 and recent Windows 10.

| | Path A: Windows PowerShell | Path B: inside WSL2 |
| --- | --- | --- |
| Compose file | `docker-compose.windows.yml` (add `-f docker-compose.windows.yml` to every command) | the default `docker-compose.yml` |
| RViz and map viewer windows | No (unless you add the extra display flags in `docs/USEFUL_COMMANDS.md`) | Yes, through WSLg |
| Gamepad | No | Yes |
| See the data | Foxglove at `ws://localhost:8765` | RViz, or Foxglove |
| Best for | Keyboard driving, auto mapping, Foxglove | Anything with a window |

Both paths need Docker Desktop running. Only one container at a time can hold the robot's connection, so stop one before starting the other.

## Path A: Windows PowerShell

1. From the repo: `git submodule update --init --recursive`.
2. `cd docker`, then `docker compose -f docker-compose.windows.yml build` (slow the first time only).
3. In the lab, set the robot address (ask a teammate) and start: `$env:ROBOT_IP="<ask a teammate>"; docker compose -f docker-compose.windows.yml up -d --build`.
4. Follow the logs: `docker compose -f docker-compose.windows.yml logs -f unitree_ros`.

Success: `Robot 0 validated and ready`. To see data, open Foxglove (desktop app, or app.foxglove.dev in Chrome or Edge), choose Open connection, Foxglove WebSocket, `ws://localhost:8765`.

## Path B: inside WSL2

1. Install Ubuntu 22.04 once, in PowerShell: `wsl --install -d Ubuntu-22.04`.
2. Turn on Docker Desktop > Settings > Resources > WSL Integration > the toggle for `Ubuntu-22.04` > Apply & Restart. This is the step people miss.
3. Open the distro (`wsl -d Ubuntu-22.04`) and check `docker info` works there.
4. `cd` to your checkout's `docker/` folder (Windows drives appear under `/mnt/c`, `/mnt/g` and so on), then `docker compose build` and `docker compose up -d`.
5. Check a window can appear: `docker compose exec unitree_ros bash -ic "ros2 run go2_map_viewer_cpp map_viewer_node"`. A "Go2 Map Viewer" window should open (look in the taskbar; it can open behind others).

Run every Path B command inside the WSL shell, not PowerShell, or the display link will not work.

## Connects to

- [Docker](docker.md): the compose files and edit loop.
- [RViz panels](rviz-panels.md) and [Map viewers](map-viewers.md): the windows Path B can show.
- [Lab checklist](lab-checklist.md): connecting to Oak.

## How it breaks

| Symptom | Fix |
| --- | --- |
| `docker` not found, or `docker info` hangs inside WSL | WSL Integration toggle is off, or Docker Desktop needs a restart after turning it on |
| Window never appears, no error | In the container, `echo $DISPLAY` should not be empty. If it is, restart the WSL shell |
| `cannot open display` or X11 errors | `~/.Xauthority` does not exist yet: open any GUI app in WSL once, then retry |
| `rviz2 ... could not connect to display` on Path A | Expected: Path A has no display. Use Foxglove or Path B |
| `docker` commands return 500 or hang | Check free space on C:; Docker's disk lives there by default |
| Build crashes WSL | Out of memory: see [Docker](docker.md), or raise `memory=` in `.wslconfig` |
| RViz's built-in Map display crashes | Known with WSL's software graphics; it is off in our layout. Use the MapViewer panel |
| Closing RViz prints `context is invalid` and exit 139 | A crash during shutdown on Humble. Ignore it |

## Who's on it and what's next

TODO(owner): no owner. The source docs contain one teammate's machine-specific folder paths; adjust them to your own checkout.

## The code

Full guides in the repo: https://github.com/maxhawksby/go2-fusion/tree/master/docs (`WINDOWS_SETUP.md`, `RUNNING_IN_WSL.md`, `USEFUL_COMMANDS.md`).

<!-- sources: docs/RUNNING_IN_WSL.md; docs/WINDOWS_SETUP.md (why a separate compose file, Foxglove, troubleshooting); docs/RUNNING_TOOLS.md; docs/USEFUL_COMMANDS.md (rviz from PowerShell, exit 139); docker/docker-compose.yml and docker-compose.windows.yml; docs/FUSION.md row 7; docs/TEST_LOG.md open issue 5 -->
