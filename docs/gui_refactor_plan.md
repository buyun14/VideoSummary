# GUI Refactor Plan

## Goal
Prepare the current Tkinter control panel for long-term maintainability while keeping behavior stable.

## Current Pain Points
- `src/videosummary/gui.py` mixes UI layout, state persistence, command assembly, runtime process management, and network testing in one file.
- VLM/LLM channel logic is duplicated across UI state and command builders.
- Testing logic is embedded in widget handlers and hard to unit test.

## Target Architecture
1. `gui/app.py`
- App bootstrap and root window lifecycle.

2. `gui/state.py`
- Dataclass-based state model.
- Load/save `.videosummary_gui.json`.
- Preset CRUD.

3. `gui/model_channels.py`
- Channel config abstraction (`ModelChannelConfig`) for VLM/LLM.
- Provider defaults and channel-level validation.

4. `gui/commands.py`
- Build CLI command arrays for run-all/phase1/phase2/phase3/phase4.
- Build runtime env injection map.

5. `gui/connectivity.py`
- `/v1/models` + minimal chat/completions probes.
- Unified error formatting and timeout handling.

6. `gui/views/main_panel.py`
- Tkinter widgets only.
- Event delegation to a controller/service layer.

## Suggested Incremental Steps
1. Extract provider default + channel config to `model_channels.py`.
2. Extract command builders and add snapshot tests.
3. Extract connectivity tester and add mock HTTP tests.
4. Move settings persistence and preset logic to `state.py`.
5. Keep `src/videosummary/gui.py` as a thin compatibility wrapper.

## Acceptance Criteria
- Existing GUI workflows unchanged for users.
- `python -m videosummary.cli gui` remains the entrypoint.
- Connection tests and run-all still support split VLM/LLM providers.
- New modules have basic unit tests for pure logic paths.
