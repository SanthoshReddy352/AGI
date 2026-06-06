# FRIDAY Hand Gesture Control System

## Overview

This document defines a cross-platform hand gesture control subsystem for FRIDAY. The system allows users to control windows, media playback, desktop navigation, browser actions, and FRIDAY modes using webcam-based hand gestures.

Example activation flow:

- User: "Friday, enable gestures"
- FRIDAY activates gesture mode
- Webcam tracking pipeline starts
- Hand gestures are recognized in real time
- Actions are mapped to OS/window controls

The system should integrate with FRIDAY's existing event-driven architecture, capability broker, workflow orchestration, and tool execution pipeline.

---

# 1. Goals

The gesture subsystem should:

- Work on Linux, Windows, and macOS
- Run locally without cloud dependency
- Support real-time gesture recognition
- Integrate with voice activation
- Support configurable gesture mappings
- Support multi-mode gesture workflows
- Minimize CPU usage and latency
- Support future AI gesture learning
- Be modular and extensible

---

# 2. High-Level Architecture

```text
Voice Command
    ↓
Gesture Manager
    ↓
Camera Stream
    ↓
Hand Detection
    ↓
Landmark Extraction
    ↓
Gesture Recognition
    ↓
Gesture Event Bus
    ↓
Capability Broker
    ↓
Tool Execution
    ↓
OS / Application Control
```

---

# 3. Recommended Technology Stack

## Core Technologies

| Component              | Recommendation                 |
| ---------------------- | ------------------------------ |
| Webcam Access          | OpenCV                         |
| Hand Tracking          | MediaPipe Hands                |
| ML Runtime             | ONNX Runtime / TensorFlow Lite |
| Gesture Classification | Rule-based + ML Hybrid         |
| OS Automation          | PyAutoGUI + pynput             |
| Window Management      | platform-specific APIs         |
| Async Runtime          | threading / asyncio            |
| Event System           | FRIDAY EventBus                |

---

# 4. Why MediaPipe Hands

MediaPipe Hands provides:

- 21 3D hand landmarks
- Real-time tracking
- CPU-efficient inference
- Cross-platform support
- Offline operation
- Multi-hand tracking
- Stable gesture coordinates

Hand landmarks include:

- Wrist
- Thumb joints
- Index joints
- Middle joints
- Ring joints
- Pinky joints

These landmarks allow:

- Finger state detection
- Distance calculation
- Direction estimation
- Rotation detection
- Motion path tracking

---

# 5. Cross-Platform Feasibility

| Feature                 | Linux   | Windows | macOS   |
| ----------------------- | ------- | ------- | ------- |
| Webcam Access           | Yes     | Yes     | Yes     |
| Gesture Tracking        | Yes     | Yes     | Yes     |
| Mouse Control           | Yes     | Yes     | Yes     |
| Keyboard Events         | Yes     | Yes     | Yes     |
| Window Management       | Yes     | Yes     | Partial |
| Virtual Desktop Control | Partial | Yes     | Partial |
| Media Controls          | Yes     | Yes     | Yes     |
| Browser Automation      | Yes     | Yes     | Yes     |

---

# 6. Gesture Activation Flow

## Voice Activation

User says:

```text
Friday, enable gestures
```

Pipeline:

```text
STT
    ↓
IntentRecognizer
    ↓
CapabilityBroker
    ↓
GestureManager.enable()
```

Suggested new capabilities:

- enable\_gesture\_mode
- disable\_gesture\_mode
- pause\_gesture\_mode
- resume\_gesture\_mode
- switch\_gesture\_profile
- calibrate\_gestures

---

# 7. Gesture Modes

Gesture recognition should support multiple modes.

## 7.1 Desktop Navigation Mode

Controls:

- Mouse movement
- Clicks
- Dragging
- Scrolling
- Window switching

## 7.2 Media Mode

Controls:

- Play
- Pause
- Next track
- Previous track
- Volume
- Fullscreen

## 7.3 Browser Mode

Controls:

- Scroll
- Tab switching
- Back/forward
- Zoom
- Refresh

## 7.4 Presentation Mode

Controls:

- Next slide
- Previous slide
- Laser pointer mode
- Annotation trigger

## 7.5 Smart Window Mode

Controls:

- Minimize
- Maximize
- Snap left/right
- Switch windows
- Close windows

---

# 8. Hand Gesture Categories

The system should support:

## Static Gestures

Single-frame poses.

Examples:

- Open palm
- Fist
- Two fingers
- Pinch
- Thumbs up

## Dynamic Gestures

Motion-based gestures.

Examples:

- Swipe left
- Swipe right
- Circle motion
- Push gesture
- Pull gesture

---

# 9. Core Hand Gestures and Actions

# 9.1 Open Palm

## Recognition

All fingers extended.

## Actions

- Wake gesture system
- Pause cursor movement
- Stop media
- Emergency cancel

## Implementation

```python
if all_fingers_open:
    gesture = "open_palm"
```

---

# 9.2 Closed Fist

## Recognition

All fingers folded.

## Actions

- Hold drag
- Grab window
- Pause playback
- Lock cursor

## Implementation

```python
if all_fingers_closed:
    gesture = "fist"
```

---

# 9.3 Index Finger Only

## Recognition

Only index finger extended.

## Actions

- Mouse movement
- Precision pointer mode

## Implementation

```python
cursor_x = hand_landmarks[index_tip].x
cursor_y = hand_landmarks[index_tip].y
```

---

# 9.4 Pinch Gesture

## Recognition

Thumb tip and index tip close together.

## Actions

- Left click
- Drag start
- Select
- Resize windows

## Implementation

```python
if distance(thumb_tip, index_tip) < threshold:
    gesture = "pinch"
```

---

# 9.5 Double Pinch

## Actions

- Double click
- Open application
- Maximize window

---

# 9.6 Swipe Left

## Recognition

Fast horizontal motion left.

## Actions

- Previous tab
- Previous workspace
- Browser back
- Previous slide

## Implementation

Track landmark trajectory over time.

```python
velocity_x < -threshold
```

---

# 9.7 Swipe Right

## Actions

- Next tab
- Browser forward
- Next workspace
- Next slide

---

# 9.8 Swipe Up

## Actions

- Maximize window
- Show desktop overview
- Open launcher

---

# 9.9 Swipe Down

## Actions

- Minimize window
- Exit fullscreen
- Hide overlays

---

# 9.10 Two Finger Gesture

## Recognition

Index + middle finger open.

## Actions

- Scroll mode
- Switch tabs
- Zoom mode

---

# 9.11 Three Finger Gesture

## Actions

- Task switching
- Alt+Tab mode
- Workspace switching

---

# 9.12 Four Finger Gesture

## Actions

- Open system dashboard
- Open FRIDAY overlay
- Launch quick menu

---

# 9.13 Thumbs Up

## Actions

- Confirm action
- Accept dialog
- Resume playback

---

# 9.14 Thumbs Down

## Actions

- Cancel action
- Reject dialog
- Stop operation

---

# 9.15 OK Sign

## Recognition

Thumb + index connected, others extended.

## Actions

- Select item
- Open file
- Confirm selection

---

# 9.16 Circular Motion

## Recognition

Circular hand movement.

## Actions

- Volume control
- Brightness control
- Timeline scrubbing

## Implementation

Track angle trajectory.

---

# 9.17 Push Gesture

## Recognition

Hand moving toward camera.

## Actions

- Open focused window
- Enter fullscreen
- Execute command

---

# 9.18 Pull Gesture

## Recognition

Hand moving away from camera.

## Actions

- Close focused window
- Exit fullscreen

---

# 9.19 Air Tap

## Actions

- Click
- Play/Pause
- Confirm interaction

---

# 9.20 Hand Rotation

## Recognition

Rotation angle change.

## Actions

- Volume adjustment
- Window resize
- Zoom

---

# 10. Window Management Gestures

| Gesture            | Action              |
| ------------------ | ------------------- |
| Pinch + Move       | Drag window         |
| Swipe Up           | Maximize            |
| Swipe Down         | Minimize            |
| Swipe Left         | Snap left           |
| Swipe Right        | Snap right          |
| Three Finger Left  | Previous desktop    |
| Three Finger Right | Next desktop        |
| Fist Hold          | Grab focused window |
| Push Gesture       | Bring forward       |
| Pull Gesture       | Send backward       |

---

# 11. Media Control Gestures

| Gesture                 | Action         |
| ----------------------- | -------------- |
| Open Palm               | Pause          |
| Air Tap                 | Play/Pause     |
| Swipe Right             | Next track     |
| Swipe Left              | Previous track |
| Circle Clockwise        | Volume up      |
| Circle Counterclockwise | Volume down    |
| Two Finger Up           | Seek forward   |
| Two Finger Down         | Seek backward  |

---

# 12. Browser Control Gestures

| Gesture           | Action          |
| ----------------- | --------------- |
| Swipe Left        | Browser back    |
| Swipe Right       | Browser forward |
| Two Finger Scroll | Scroll page     |
| Pinch Out         | Zoom in         |
| Pinch In          | Zoom out        |
| Open Palm         | Stop loading    |
| Air Tap           | Open link       |

---

# 13. Gesture Recognition Strategies

## 13.1 Rule-Based Recognition

Fastest approach.

Use:

- Finger angles
- Landmark distances
- Finger states
- Motion vectors

Advantages:

- Lightweight
- Low latency
- Easy debugging
- Offline

Recommended for:

- Basic FRIDAY gestures

---

## 13.2 ML-Based Classification

Use sequence models:

- LSTM
- GRU
- Temporal CNN
- Transformer

Input:

- Landmark sequences
- Velocity vectors
- Motion history

Advantages:

- Better dynamic gestures
- User-customized gestures
- Adaptive learning

Recommended later phase.

---

# 14. Recommended Initial MVP

Phase 1 should implement:

- Open palm
- Fist
- Pinch
- Swipe left/right
- Index pointer
- Two finger scroll

Mapped actions:

- Mouse move
- Click
- Scroll
- Volume control
- Window switching
- Media controls

---

# 15. Gesture Smoothing and Stability

Raw landmarks are noisy.

Required stabilization:

## Temporal Filtering

Use:

- Moving average
- Kalman filter
- Exponential smoothing

## Debouncing

Prevent repeated triggers.

```python
if current_time - last_trigger > cooldown:
    execute_action()
```

## Confidence Thresholds

Only execute high-confidence gestures.

---

# 16. Latency Targets

| Component           | Target |
| ------------------- | ------ |
| Webcam capture      | <10ms  |
| Hand tracking       | <20ms  |
| Gesture recognition | <10ms  |
| Action dispatch     | <5ms   |
| Total latency       | <50ms  |

---

# 17. CPU and GPU Considerations

## CPU-Only Mode

Recommended for:

- Lightweight systems
- Laptop operation
- Cross-platform compatibility

## GPU Acceleration

Optional:

- CUDA
- OpenCL
- Metal

Useful for:

- Multi-hand tracking
- ML gesture models
- High FPS cameras

---

# 18. Proposed FRIDAY Module Structure

```text
modules/
└── gesture_control/
    ├── gesture_manager.py
    ├── camera_stream.py
    ├── hand_tracker.py
    ├── gesture_classifier.py
    ├── gesture_actions.py
    ├── gesture_profiles.py
    ├── smoothing.py
    ├── calibration.py
    ├── overlays.py
    └── gestures/
        ├── static_gestures.py
        └── dynamic_gestures.py
```

---

# 19. Suggested Capability Registration

Suggested capabilities:

```python
register_tool({
    "name": "enable_gesture_mode",
    "description": "Enable hand gesture controls"
})

register_tool({
    "name": "disable_gesture_mode",
    "description": "Disable hand gesture controls"
})

register_tool({
    "name": "switch_gesture_profile",
    "description": "Switch active gesture profile"
})
```

This integrates cleanly with the existing capability registry architecture.

---

# 20. Integration with IntentRecognizer

Example parsing rules:

```python
if "enable gestures" in clause_lower:
    return {
        "tool": "enable_gesture_mode",
        "args": {}
    }
```

Additional commands:

- "Friday, disable gestures"
- "Friday, presentation mode"
- "Friday, media gestures"
- "Friday, calibrate gestures"




# 21. Gesture Runtime Manager

The Gesture Runtime Manager is responsible for:

* Starting/stopping camera pipelines
* Managing gesture modes
* Switching profiles
* Tracking gesture state
* Dispatching gesture events
* Managing cooldowns
* Handling camera failures
* Power optimization

Suggested structure:

```python
class GestureManager:
    def __init__(self):
        self.enabled = False
        self.current_mode = "desktop"
        self.active_profile = "default"
        self.camera = None
        self.classifier = None
```

Responsibilities:

```text
GestureManager
    ├── Camera lifecycle
    ├── Mode management
    ├── Profile switching
    ├── Event publishing
    ├── Runtime telemetry
    └── Gesture arbitration
```

---

# 22. Camera Pipeline Design

The camera pipeline should run independently from:

* STT
* TTS
* Main assistant loop
* Tool execution

Recommended threading model:

```text
Main Thread
    ├── Voice System
    ├── Tool Runtime
    └── Gesture Thread
            ├── Camera Capture
            ├── Landmark Tracking
            └── Gesture Recognition
```

Recommended FPS targets:

| Camera FPS | Recommendation  |
| ---------- | --------------- |
| 15 FPS     | Minimum         |
| 24 FPS     | Good            |
| 30 FPS     | Recommended     |
| 60 FPS     | Advanced setups |

---

# 23. Gesture State Machine

The system should maintain gesture states.

## States

```text
IDLE
TRACKING
GESTURE_DETECTED
ACTION_PENDING
ACTION_EXECUTED
COOLDOWN
```

## Example Flow

```text
Hand Detected
    ↓
Gesture Candidate
    ↓
Confidence Validation
    ↓
Cooldown Check
    ↓
Execute Action
    ↓
Cooldown
```

---

# 24. Gesture Confidence Scoring

Each gesture should have:

* Recognition confidence
* Temporal consistency
* Landmark stability
* Motion confidence

Example:

```python
confidence = (
    landmark_score * 0.4 +
    temporal_score * 0.3 +
    motion_score * 0.3
)
```

Suggested thresholds:

| Confidence | Action         |
| ---------- | -------------- |
| <0.50      | Ignore         |
| 0.50–0.70  | Soft candidate |
| 0.70–0.85  | Valid gesture  |
| >0.85      | Strong gesture |

---

# 25. Cursor Control System

## Mapping Hand Position to Cursor

Index fingertip coordinates:

```python
screen_x = hand_x * screen_width
screen_y = hand_y * screen_height
```

## Smoothing Required

Without smoothing:

* Cursor jitter
* Unstable movement
* Oversensitivity

Recommended smoothing:

```python
smooth_x = prev_x + (target_x - prev_x) * 0.2
smooth_y = prev_y + (target_y - prev_y) * 0.2
```

---

# 26. Multi-Hand Support

The system should support:

* Single hand mode
* Dual hand mode
* Dominant hand selection
* Left-handed users

## Suggested Usage

| Hands      | Function          |
| ---------- | ----------------- |
| Right hand | Cursor control    |
| Left hand  | Modifier gestures |
| Both hands | Advanced commands |

Examples:

* Two-hand zoom
* Two-hand rotate
* Window resizing
* Gesture combinations

---

# 27. Gesture Profiles

Profiles allow context-specific controls.

## Example Profiles

### Desktop Profile

* Cursor
* Window management
* Scrolling

### Gaming Profile

* Push-to-talk
* Media shortcuts
* Macro gestures

### Presentation Profile

* Slide control
* Laser pointer
* Annotation tools

### Editing Profile

* Timeline scrubbing
* Zoom
* Playback control

---

# 28. Profile Switching

Profiles can switch automatically.

## Examples

```text
If PowerPoint active:
    presentation profile

If browser active:
    browser profile

If VLC active:
    media profile
```

Detection methods:

* Focused window detection
* Process name detection
* User command
* Activity inference

---

# 29. Overlay and Visual Feedback

Users need feedback.

Recommended overlays:

* Hand skeleton
* Active gesture name
* Confidence percentage
* Current mode
* Cooldown timers
* FPS counter

Optional:

* Cursor trails
* Gesture history
* Heatmaps

---

# 30. Gesture HUD Design

Suggested overlay regions:

```text
+--------------------------------+
| FPS       Mode       Profile   |
|                                |
|                                |
|      Hand Tracking Area        |
|                                |
|                                |
| Gesture: Pinch                 |
| Confidence: 92%                |
+--------------------------------+
```

---

# 31. Gesture Arbitration

Sometimes multiple gestures may match.

Example:

* Pinch vs OK sign
* Swipe vs cursor motion
* Open palm vs five finger scroll

The system should:

* Prioritize high-confidence gestures
* Use temporal context
* Use gesture cooldowns
* Apply mode-specific restrictions

---

# 32. Dynamic Gesture Recognition

Dynamic gestures require motion analysis.

## Required Components

* Landmark history buffer
* Velocity tracking
* Direction estimation
* Motion segmentation

Example:

```python
trajectory.append(index_tip_position)
```

Track:

* Motion vectors
* Acceleration
* Path curvature
* Duration

---

# 33. Gesture Sequence Recognition

Support chained gestures.

Examples:

```text
Open Palm → Swipe Right
```

Meaning:

```text
Activate desktop switching mode
```

Another example:

```text
Fist → Push
```

Meaning:

```text
Throw window to another workspace
```

---

# 34. Gesture Cooldown System

Cooldowns prevent accidental repeated execution.

Example:

```python
cooldowns = {
    "pinch": 0.3,
    "swipe": 0.8,
    "fullscreen": 1.5
}
```

Recommended cooldown ranges:

| Gesture Type      | Cooldown   |
| ----------------- | ---------- |
| Cursor gestures   | 0ms        |
| Click gestures    | 200–300ms  |
| Window gestures   | 700–1000ms |
| Dangerous actions | 1500ms+    |

---

# 35. Power Optimization

Continuous webcam tracking consumes power.

Optimization strategies:

## Adaptive FPS

Lower FPS during inactivity.

## Idle Sleep

Disable tracking if no hand detected.

## Resolution Scaling

Lower camera resolution dynamically.

## Detection Zones

Only process center regions.

---

# 36. Recommended Camera Settings

| Setting        | Recommended |
| -------------- | ----------- |
| Resolution     | 640x480     |
| FPS            | 30          |
| Color Space    | RGB         |
| Exposure       | Auto        |
| Tracking Hands | 1 initially |

Advanced setups:

* 720p
* Stereo cameras
* Depth cameras
* IR cameras

---

# 37. Supported Hardware

## Standard Webcams

Supported.

## Laptop Cameras

Supported.

## External USB Cameras

Recommended.

## Depth Cameras

Optional future enhancement.

Examples:

* Intel RealSense
* Azure Kinect
* Leap Motion

---

# 38. Window Management Implementation

Cross-platform window management is difficult.

## Linux

Possible libraries:

* wmctrl
* xdotool
* pyautogui
* python-xlib

## Windows

Possible libraries:

* pywin32
* ctypes
* pygetwindow

## macOS

Possible libraries:

* pyobjc
* Quartz APIs

---

# 39. Browser Integration

Browser-specific gesture support:

## Chrome / Chromium

Use:

* Keyboard shortcuts
* Accessibility APIs
* Browser automation

## Firefox

Use:

* Selenium
* Keyboard automation

## Edge

Use:

* Chromium-compatible automation

---

# 40. Media Integration

Media control can use:

* Media keys
* OS media sessions
* Browser media APIs
* VLC APIs
* Spotify APIs

Recommended abstraction:

```python
class MediaController:
    def play_pause(self):
        pass
```

---

# 41. Accessibility Mode

Accessibility-focused gesture mode should include:

* Large gesture zones
* Lower sensitivity
* Fewer accidental triggers
* Slow-motion recognition
* Audio confirmations

Optional:

* Haptic feedback
* Visual accessibility overlays

---

# 42. Calibration System

Users have:

* Different hand sizes
* Different camera distances
* Different lighting
* Different motion speed

Calibration should measure:

* Hand size
* Reach area
* Motion speed
* Gesture comfort zones

---

# 43. Gesture Training Workflow

Future enhancement:

Users train custom gestures.

Workflow:

```text
User performs gesture
    ↓
Landmark recording
    ↓
Feature extraction
    ↓
Gesture labeling
    ↓
Profile storage
```

Possible storage:

```json
{
  "gesture": "custom_zoom",
  "samples": [...],
  "threshold": 0.84
}
```

---

# 44. Logging and Telemetry

The system should log:

* Gesture detections
* Confidence values
* FPS
* Latency
* Failure events
* Camera disconnects

Suggested metrics:

| Metric               | Purpose     |
| -------------------- | ----------- |
| Recognition accuracy | Quality     |
| FPS stability        | Performance |
| Trigger frequency    | UX tuning   |
| False positives      | Reliability |

---

# 45. Debugging Tools

Developer tools should include:

* Landmark visualizer
* Gesture replay
* Motion trajectory viewer
* Confidence graphs
* Latency analyzer
* FPS monitor

---

# 46. Security and Permission Handling

The gesture system should:

* Ask for camera permission
* Allow disabling camera instantly
* Restrict dangerous gestures
* Avoid hidden background recording

Sensitive actions requiring confirmation:

* Shutdown
* Restart
* Closing unsaved applications
* Deleting files

---

# 47. Failure Recovery

Possible failure cases:

* Camera disconnected
* Tracking lost
* FPS drops
* Gesture instability
* Lighting failure

Recovery actions:

```text
Attempt reconnect
    ↓
Lower FPS
    ↓
Reset tracking
    ↓
Fallback to idle mode
```

---

# 48. Environmental Challenges

Gesture tracking is affected by:

* Poor lighting
* Motion blur
* Background clutter
* Camera angle
* Occlusions
* Multiple people

Mitigation:

* Adaptive thresholds
* Background segmentation
* Hand priority tracking
* Confidence gating

---

# 49. Future AI Enhancements

## Context-Aware Gestures

Example:

```text
Swipe right in browser → next tab
Swipe right in VLC → next video
```

## Personalized Gesture Models

Train per-user gesture patterns.

## Reinforcement Learning

Adapt gesture thresholds over time.

## Intent Prediction

Combine:

* Voice
* Gesture
* Context
* Active application

---

# 50. Final Architecture Recommendation

Recommended implementation strategy:

## Phase 1

Implement:

* MediaPipe Hands
* Static gestures
* Cursor control
* Click gestures
* Media controls

## Phase 2

Implement:

* Dynamic gestures
* Window management
* Gesture profiles
* Overlay system

## Phase 3

Implement:

* Multi-hand support
* Gesture sequences
* Context-aware profiles
* Calibration system

## Phase 4

Implement:

* ML gesture classification
* Custom gesture training
* Adaptive learning
* AI-assisted gesture prediction

---

#

