---
name: smart-home-scenes
description: "Composite Home Assistant scenes — 'movie mode', 'good night', area lookups."
source: "hermes-agent skills/smart-home (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - turn_on
  - turn_off
  - set_temperature
  - get_state
---

# smart-home scenes

## When to use

The user wants to flip multiple devices at once with a single command — "movie mode", "good night", "wake up", "I'm leaving". Or they want to ask about an area rather than a specific entity — "are any bedroom lights on?", "what's the temperature upstairs?".

Single-device commands ("turn on the bedroom lights") go through the plain `turn_on/off` capabilities — no scene needed.

## Scene definitions

Scenes are declared in `config/home_assistant.yaml` under a `scenes:` block:
```yaml
scenes:
  movie_mode:
    description: "Dim the lights and turn on the TV."
    actions:
      - { service: light.turn_on, entity: light.living_room, data: { brightness: 60 } }
      - { service: switch.turn_off, entity: switch.lamp_corner }
      - { service: media_player.turn_on, entity: media_player.living_room_tv }
  good_night:
    description: "Lights off, thermostat 18°C, doors confirmed locked."
    actions:
      - { service: light.turn_off, entity: light.all_main }
      - { service: climate.set_temperature, entity: climate.main, data: { temperature: 18 } }
      - { service: lock.lock, entity: lock.front_door }
  i_am_leaving:
    description: "Everything off, set away mode."
    actions:
      - { service: light.turn_off, entity: light.all_main }
      - { service: climate.set_preset_mode, entity: climate.main, data: { preset_mode: away } }
```

## How to use

### Activate a scene
1. Match the user's phrase to the scene `description` (substring, case-insensitive).
2. Execute the actions in order via `ha_call_service`. Failures are reported but don't abort the rest.
3. Reply with what was actually changed: "Lights down to 60%, TV on. Couldn't reach the corner lamp."

### Area query
1. Pull all entities tagged with the area via `get_state`.
2. Aggregate: "3 lights on, 2 off, AC at 22°C".
3. For long lists (>5 entities) summarise; the user can ask for details.

## Examples

- "Friday, movie mode."
- "Friday, good night."
- "Friday, any bedroom lights still on?"
- "Friday, what's the temperature upstairs?"

## Common failures and recovery

- **One device in a scene fails** → continue with the rest; surface the failure in the reply.
- **Scene name not recognised** → list available scenes with `clarify`: "I have movie_mode, good_night, i_am_leaving — which one?"
- **HA unreachable** → "Home Assistant isn't responding. Skipping scene." Don't retry in a tight loop.
