---
title: Test log
parent: lab-setup
code: [docs/TEST_LOG.md]
---

# Test log

The test log is Oak's lab notebook: one section per session with the real robot, recording what we tested, whether it passed, and what is still broken.

Part of: [Lab setup](lab-setup.md)

## How it works

The log lives in `docs/TEST_LOG.md`. Newest session first.
Each test gets one of these results: **pass**, **fail**, **partial**, or **not run**, plus a short note on what we saw.
An **Open issues** list at the bottom carries over between sessions until each issue is fixed and retested on Oak.
During a session, the note-taker (often Claude, from Max's feedback and its own measurements) updates the log and commits it at the end.

It matters because robot time is scarce: one dog, one connection at a time. The log tells you what is already known, so you test what is new.

## The latest session: 2026-10-11

Over Wi-Fi, on `master` plus the keyboard fix branch:

- **Passed:** build in Docker (after limiting parallel jobs), connecting with camera and RViz, lidar at about 6.8 Hz, YOLO object detection at about 4.5 frames per second on CPU, and the [twist_mux](twist-mux.md) priority order.
- **Failed, then fixed:** on old code Oak **kept walking and hit a wall**, because the driver dropped every stop command. On new code the stop arrived. Both keyboard tools sent stop commands nonstop and blocked Nav2; fixed.
- **Partial:** keyboard driving worked but "really isn't that good".
- **Failed:** a Nav2 goal ("starting point in lethal space": the lidar saw Oak's own body as an obstacle). A fix is in; retest pending.
- **Not run:** gamepad (no Xbox-style pad in the lab; the team now uses the Oak ROS2 pad, so this test is no longer needed), map click-to-walk, object navigation to a chair, sit and stand, the auto mapper, text-to-speech, the AI agent.

## Open issues (from the log)

1. Retest Nav2 goals and MapViewer click-to-walk on new code.
2. Retest keyboard driving feel with both teleop fixes.
3. Find out what starts `lidar_to_pointcloud` and whether its input topic is right.
4. Confirm by eye that Oak stops cleanly when a drive source goes quiet.
5. WSL had 7.4 GB of RAM: keep builds at `-j4` and 2 workers, or raise `memory=` in `.wslconfig`.
6. Gamepad LB test: no longer required; the team uses the Oak ROS2 pad. TODO(Max): how the Oak ROS2 pad connects (does it publish /joy into ROS, or talk to Oak directly?)

## Connects to

- [Lab checklist](lab-checklist.md): how to get connected for a session.
- [Roadmap](roadmap.md) and the [Oak](../../README.md) front page: open issues show up there.
- Program pages such as [Keyboard teleop](keyboard-teleop.md), [Nav2](nav2.md) and [Go2 driver](go2-driver.md) quote these results in their "How it breaks" sections.

## How it breaks

- **It goes stale.** The last recorded session is 2026-10-11. Luis's auto mapper work and later fixes have no logged robot session yet. TODO(owner): add sessions since then.

## How to add a session

Add a new `## <date> - <place>, Oak, <Wi-Fi or Ethernet>` section at the top, name the code you ran (branch and commit), then one table row per test. Never write network names, addresses or keys in it. Move fixed items out of Open issues only after a retest on Oak.

## Who's on it and what's next

Max keeps the log. Next: the retests above, and Luis's full exploration tests with the auto mapper.

## The code

https://github.com/maxhawksby/go2-fusion/tree/master/docs (`TEST_LOG.md`)

<!-- sources: docs/TEST_LOG.md (whole file); docs/FUSION.md "Follow-ups for the team" 4; README.md open issues; team update 2026-10-18 (Luis next: full exploration tests); git log c18ca87 -->
