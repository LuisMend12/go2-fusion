---
title: Decisions
parent: team
code: [docs/FUSION.md]
---

# Decisions

This page explains the big choices behind Oak's code and why we made them, so you never have to guess why something is the way it is.

Part of: [Team](team.md)

The full record lives in `docs/FUSION.md`. This page is the friendly summary.

## How this repo was born: the fusion

This repo combines two codebases:

- **Our team fork** of the Go2 ROS 2 SDK, with our Docker workflow, WSL fixes, support for newer robot firmware, and our own packages.
- **Riley Francis's [ROS2-LLM-Nav](https://github.com/RileyFrancis/ROS2-LLM-Nav)**, copied from his last commit on 2026-09-28. Riley built the YOLO detector, object navigation, the LLM agent and the speech-to-text tool.

Our fork is the base, because Riley's repo carried older copies of the same driver. Riley's own packages were copied in and changed only where the record says. The repo starts with a **fresh git history**, so old commits containing lab access details never leave the team fork.

## Key decisions from the fusion

1. **YOLO detector in, old detector stays for now.** YOLO is more accurate and gives rough positions. Its topic was renamed to `/detected_objects/poses` so it does not clash with `coco_detector`. See [Object detection](object-detection.md).
2. **Every drive source gets its own lane.** Before, the keyboard, agent and object navigation all shared Nav2's `/cmd_vel`, so whoever published last won. Now each has its own input on [twist_mux](twist-mux.md), and people outrank robots:

   | Priority | Topic | Who |
   | --- | --- | --- |
   | 10 | `/cmd_vel_joy` | Gamepad, only while LB is held |
   | 9 | `/cmd_vel_keyboard` | Keyboard and the RViz keyboard panel |
   | 5 | `/cmd_vel` | Nav2 (and the auto mapper and map viewers through it) |
   | 4 | `/cmd_vel_agent` | [LLM agent](llm-agent.md) |
   | 3 | `/cmd_vel_object_nav` | [Object navigation](object-navigation.md) |

3. **LLM agent brought in, but its paid-API libraries kept out of the image.** It builds but does not run (see below for why).
4. **Object navigation on the lowest priority**, because it has no obstacle avoidance.
5. **Riley's speech fixes taken:** smaller audio pieces tuned on the robot, plus three bug fixes. See [Voice](voice.md).
6. **Docker:** keep our image (dependencies only, code mounted in, built on start), default to Wi-Fi (`CONN_TYPE=webrtc`), and give it 1 GB of shared memory so camera images do not run out of room. See [Docker](docker.md).
7. **RViz's Map display stays off**, because it crashes under WSL. Luis's map viewer panel covers it.
8. **Riley's extras left out:** semantic-mapping experiments that need an NVIDIA GPU, demo audio scripts, and older stubs.
9. **Gamepad needs a held button (LB).** An idle gamepad sent "speed 0" 20 times a second and froze the agent and object navigation.
10. **Lab access details removed** from the repo. Ask a teammate privately.
11. **Keyboard sends only while a key is held**, plus one stop. Found on the robot on 2026-10-11: idle zeros blocked Nav2, the agent and object navigation. See [Test log](test-log.md).

The record numbers these 1 to 16; this list keeps the ones that shape daily work.

## Decided since

- **2026-10-08: rebuild the LLM agent on Claude.** Riley's agent needed close to a rewrite (fixed plans, lost turn direction, no stop). This is now **superseded** by the next decision.
- **Ollama agent direction** (Adib's branch, dated 2026-10-12; confirmed as the team's direction on 2026-10-22). The agent runs a free local Qwen model through Ollama, with no paid API key. Simulation is the default; real moves reuse `/cmd_vel_agent`. Voice and object navigation are out of scope for this first step. See [LLM agent](llm-agent.md).
- **2026-10-22: the wiki is a graph.** `README.md` is the center page, Oak. Hubs and one page per program live in `docs/wiki/`, and a check fails when code changes without its page.
- **2026-10-22: review only for merges into `master`.** Your own branches are a sandbox; merging into `master` needs one teammate's approval and green checks.

## Still open

From the record's follow-ups: confirm the lidar topic on the robot, maybe port the faster lidar decoder, retire `coco_detector`, retest everything on the robot, test the gamepad button with a real controller, and note that `webrtc_web.launch.py` skips twist_mux, so priorities do not apply there.

## Add a decision

When the team decides something that changes how code works, add it here with the date, what was chosen, and why. Put the detailed version in `docs/FUSION.md` if it touches the fusion.

<!-- sources: docs/FUSION.md (What this repo is, Decisions 1-16, twist_mux priorities, Left out, Decided after the fusion, Follow-ups); origin/adib/feat/llm-agent FUSION.md diff (2026-10-12 Ollama decision); 2026-10-22 decisions: Max via coordinator (contract), AGENTS.md Git and Wiki sections, scripts/wiki/README.md -->
