---
name: smart_home
description: "Home Assistant integration for smart home control — lights, climate, locks, and device state."
plugin_module: modules/smart_home
capabilities:
  - name: ha_turn_on
    description: "Turn on a smart home device (lights, fan, AC, TV, plug)."
    aliases:
      - "turn on the lights"
      - "lights on"
      - "switch on"
      - "turn on the fan"
  - name: ha_turn_off
    description: "Turn off a smart home device."
    aliases:
      - "turn off the lights"
      - "lights off"
      - "switch off"
      - "turn off the tv"
  - name: ha_get_state
    description: "Check the current state of a smart home device."
    aliases:
      - "is the door locked"
      - "is the light on"
      - "check the ac"
      - "what is the temperature"
  - name: ha_set_temperature
    description: "Set the target temperature for a climate device."
    aliases:
      - "set the ac to 22 degrees"
      - "set thermostat to"
      - "cool the room to"
---

# Smart Home Module

Controls Home Assistant devices via the local REST API. No cloud required.

## Setup

1. Open Home Assistant → Settings → User Profile → Long-Lived Access Tokens
2. Create a token and copy it.
3. Edit `config/home_assistant.yaml`:

```yaml
url: "http://homeassistant.local:8123"
token: "your-token-here"
aliases:
  bedroom lights: light.bedroom_main
  ac: climate.living_room_ac
  front door: lock.front_door
```

## Examples

```
Friday, turn on the bedroom lights
Friday, turn off the ac
Friday, is the front door locked?
Friday, set the ac to 22 degrees
Friday, what is the living room temperature?
```

## Entity Aliases

Add friendly names in the `aliases` section of `config/home_assistant.yaml`.
Without aliases, use full HA entity IDs (e.g. `light.bedroom_main`).
