# GUI Layout Optimization Plan

## Objective
Improve readability and interaction efficiency without changing CLI behavior.

## Visual Direction
- Keep desktop-first productivity panel style.
- Use grouped sections and stronger spacing rhythm.
- Reduce horizontal eye travel by splitting dense rows into cards.

## Proposed Layout
1. Top bar
- Input/output selectors.
- Preset actions and quick save.

2. Left column: ASR and Phase controls
- ASR model, local model path, HF and proxy options.
- Phase run buttons and stop button.

3. Right column: Model channels
- VLM card: provider/base/key env/no-auth/model + connection test.
- LLM card: provider/base/key env/no-auth/model + connection test.

4. Bottom panel
- Progress summary strip (last action, running state, exit code).
- Log console with filter level toggle (info/error).

## Interaction Improvements
- Disable all run buttons while a process is active.
- Highlight missing prerequisites for phase-only runs.
- Add lightweight status badge for VLM/LLM connectivity result.

## Style Tokens (Tkinter/ttk)
- Spacing scale: 4 / 8 / 12 / 16 px.
- Card padding: 10-12 px.
- Use ttk style names for section labels and primary buttons.
- Keep color usage minimal to preserve native theme compatibility.

## Implementation Sequence
1. Extract widget-building blocks into `gui_mod/views_*` modules.
2. Introduce `ttk.Notebook` tabs or two-column grid to reduce form density.
3. Add process-state binding (`running -> disable controls`).
4. Add connectivity status badges and optional tooltip text.
5. Add log filters and clear-log action.

## Definition of Done
- GUI remains functional for run-all and phase-by-phase modes.
- VLM/LLM connection tests remain accessible.
- Critical actions are reachable within two clicks from initial screen.
- No regressions in saved settings and presets.
