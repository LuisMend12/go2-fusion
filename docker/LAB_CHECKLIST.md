# ISL Lab Checklist - Running the Go2 via Docker

Quick steps for connecting to the ISL lab's Unitree Go2 using the Docker setup in this folder.

## Before going to the lab

- [ ] Find the dog's firmware version (Unitree app: Device -> Data).
- [ ] If firmware is **1.1.15 or newer**, get the dog's AES key ahead of time.
      See "Go2 firmware >= 1.1.15" in the main [upstream README](https://github.com/abizovnuralem/go2_ros2_sdk#go2-firmware--1115-webrtc-local-connection).
- [ ] Don't run `docker system prune` or delete images. That wipes the built
      image and forces a ~15 min rebuild.

## At the lab

1. **Network first.** Connect Windows to the **ISL2** wifi, then check:
   ```shell
   ping 192.168.50.150
   ```
   If the ping fails, fix the network before anything else. Docker can't fix a network problem.
2. **Close the Unitree phone app.** The dog only accepts one WebRTC connection at a time.
3. **Launch:**
   ```shell
   cd docker
   ROBOT_IP=192.168.50.150 CONN_TYPE=webrtc docker compose up --build
   ```
   If firmware is >= 1.1.15, add the key to the front:
   ```shell
   ROBOT_AES_KEY=<key> ROBOT_IP=192.168.50.150 CONN_TYPE=webrtc docker compose up --build
   ```

## Reading the result

| What you see | What it means |
| --- | --- |
| rviz opens, lidar/camera data appears | Connected |
| `Connection error when requesting http://192.168.50.150:9991/con_notify` | Can't reach the dog - check wifi / ping (step 1) |
| Same `con_notify` error, but the ping works | The dog wasn't ready when the driver tried. The driver retries on its own, waiting 5 s, then 10 s, doubling up to 60 s between tries. Wait for the next try, or run `docker compose restart unitree_ros` to try now |
| RSA / key error during the handshake | Firmware >= 1.1.15 - needs `ROBOT_AES_KEY` |
| Connects then drops, or refuses | Phone app is probably still connected (step 2) |

## Build habits

- **Always launch with `docker compose up --build`.** The image holds only the
  dependencies, so the build is a no-op unless one changed. Code changes never
  need it - `src/` is mounted live (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- **If a build looks stuck, read the step name in the output** to see what
  it's downloading. A multi-GB `nvidia-*` download means torch is pulling the
  GPU build again - the Dockerfile should install it from the CPU-only index.
