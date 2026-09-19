# Phase 08 Computer Use

## Status

Implemented: typed computer actions, bounded coordinate validation, observation identity checks, action limits, and an LLM-independent emergency stop.

Partial: no input injection backend is enabled. Coordinate actions are rejected when the executor is unavailable. DOM and accessibility methods remain preferred over coordinates.

## Action hierarchy

Use an API first, then DOM/accessibility, then browser actions, then screenshot observation, and coordinates only as a last resort. A coordinate action must reference the current observation ID and stay within that observation's dimensions. Old screenshot coordinates are rejected.

## Authorization and lifecycle

This controller validates safety properties but does not authorize actions. Any production executor must be registered through the Phase 04 trusted registry and policy gateway. JARVIS disable and emergency stop must cancel owned work and release owned resources only; normal desktop, keyboard, mouse, browser, and terminal use remain unaffected.

## Verification and limitations

The controller does not claim an action succeeded. A future executor must provide deterministic postconditions and return verification failure or unavailable when the result cannot be established. No arbitrary shell, JavaScript, credential access, upload, download, or system-wide input lock is implemented.