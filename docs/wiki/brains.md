---
title: Brains
parent: oak
---

# Brains

The higher-level behaviour: plain-English commands, walking to objects, voice and posture.

Part of: [Oak](../../README.md)

## Pages

- [LLM agent](llm-agent.md) - Turns plain-English commands into robot actions; built by Riley on GPT-4o-mini and being rebuilt on Claude, so it builds but does not run yet.
- [Object navigation](object-navigation.md) - Walks toward an object that object detection has seen (`/navigate_to_object`), on twist_mux priority 3; it has no obstacle avoidance.
- [Voice](voice.md) - Speech in and out: `host_tools/speech_to_text` sends microphone transcripts to the LLM agent, and `speech_processor` speaks `/tts` through the robot's speaker.
- [Posture](posture.md) - Leg and posture commands: `sit_controller` sends a real Sit command, while `front_leg_controller` is still a placeholder.

<!-- TODO: content -->
