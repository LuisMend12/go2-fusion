# Running go2_ros2_sdk on Windows (Docker)

Tested with Docker Desktop on Windows 11, a Unitree Go2 on Wi-Fi, WebRTC connection, ROS2 Humble.
The upstream README assumes Ubuntu; this file covers what differs on Windows.

## What you need

- Docker Desktop (Linux containers) running
- The PC on the same network as the robot (Wi-Fi `isl2`, robot at `192.168.50.150`)
- The Unitree mobile app closed. The robot accepts only one WebRTC client at a time.
- Wi-Fi password and door codes: ask the lab. Do not commit them to this repo.

## One-time setup

```powershell
cd "G:\broswer download\go2_ros2_sdk"
git submodule update --init --recursive      # pulls src/go2_robot_sdk/external_lib/aioice
cd docker
docker compose -f docker-compose.windows.yml build   # slow the first time only (ROS packages, torch, open3d)
```

The image holds only the dependencies. Your checkout is mounted into the container and built when it
starts, so editing code never needs an image rebuild. See [CONTRIBUTING.md](CONTRIBUTING.md) for the edit loop.

## Run

Use the Windows compose file, not `docker-compose.yml`:

```powershell
cd docker
docker compose -f docker-compose.windows.yml up -d --build
docker logs -f docker-unitree_ros-1
```

Success looks like `Robot 0 validated and ready` in the logs.

Stop it:

```powershell
docker compose -f docker-compose.windows.yml down
```

### Why a separate compose file

[docker/docker-compose.yml](docker/docker-compose.yml) targets Linux hosts. On Windows:
- `devices: /dev/input` (joystick) does not exist
- the X11 socket and `~/.Xauthority` mounts do not apply (RViz cannot display)
- `network_mode: host` attaches to Docker's Linux VM, not your Windows adapter, so published ports such as Foxglove's 8765 are unreachable

[docker/docker-compose.windows.yml](docker/docker-compose.windows.yml) drops those and publishes port 8765 instead.
`ROBOT_IP` defaults to `192.168.50.150` and `CONN_TYPE` to `webrtc`; override with
`$env:ROBOT_IP="..."; $env:CONN_TYPE="..."` before `up`.

## View the data (Foxglove)

Open Foxglove (desktop app recommended, or https://app.foxglove.dev in Chrome/Edge), choose
Open connection, Foxglove WebSocket, and enter `ws://localhost:8765`.

Topics verified publishing:

| Data | Topic | Rate |
|---|---|---|
| IMU | `/imu` | ~19 Hz |
| Joint states | `/joint_states` | ~1 Hz (expected on firmware 1.1.7+) |
| Odometry | `/odom` | ~13 Hz |
| Camera | `/camera/image_raw` | ~10 Hz |
| Lidar point cloud | `/point_cloud2` | ~3 Hz |
| Laser scan | `/scan` | ~5 Hz |

The upstream README's names `/go2_camera/color/image` and `/pointcloud/aggregated` do not match this build.
`/pointcloud/aggregated`, `/pointcloud/filtered` and `/pointcloud/downsampled` published nothing in testing.

Send commands from a second shell:

```powershell
docker exec -it docker-unitree_ros-1 bash
ros2 topic pub /webrtc_req go2_interfaces/msg/WebRtcReq "{api_id: 1016, topic: 'rt/api/sport/request'}" --once
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `RSA key format is not supported` | Firmware 1.1.15+ needs a per-device AES key. Set `ROBOT_AES_KEY` (32 hex chars) in the compose file's environment. Fetching it needs the Unitree account the robot is registered to. |
| Handshake times out | PC is not on the robot's network, or the Unitree app is connected. Check `Test-NetConnection 192.168.50.150 -Port 9991`. |
| `docker` commands return 500 / hang | Check free disk space on C:. Docker's WSL disk on this machine was moved to `G:\broswer download\DockerData\wsl` (junction at `C:\Users\<user>\AppData\Local\Docker\wsl`) after C: filled up. |
| `rviz2 ... could not connect to display` | Expected, no display in the container. Use Foxglove. |
| `ElevenLabs API key not provided` | Text-to-speech node is not configured. Ignore. |
| `H264 ... failed to decode` warnings | Occasional dropped video packets. Harmless. |
| `lidar_to_pointcloud` exits cleanly | Lidar is still published on `/point_cloud2` by the driver. |

## Ethernet (CycloneDDS) instead of Wi-Fi

`CONN_TYPE=cyclonedds` uses DDS discovery over a direct Ethernet cable and needs no IP or AES key, but the PC's
Ethernet adapter must be on the robot's subnet, and discovery through Docker Desktop on Windows is untested.
Both `docker-compose.yml` and `docker-compose.windows.yml` default to `webrtc`, so set `CONN_TYPE=cyclonedds` explicitly for Ethernet.

## Native alternative (WSL2, no Docker)

An Ubuntu 22.04 WSL2 distro with ROS2 Humble and the workspace built at `~/ros2_ws` is installed on G:
(`G:\broswer download\WSL\Ubuntu-22.04`). Stop the Docker container first, then:

```powershell
wsl -d Ubuntu-22.04
export ROBOT_IP=192.168.50.150 CONN_TYPE=webrtc
ros2 launch go2_robot_sdk robot.launch.py
```

Only one of the Docker container or the native launch can hold the robot's WebRTC connection at a time.
