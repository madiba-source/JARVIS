# HUD Artifact Recovery Record

## Result

`JARVIS_HUD_APPROVED_REFERENCE`: RECOVERED

## Sources searched

- Current repository files and tracked paths
- Ignored working-tree paths and common asset directories
- `git log --all --name-status`
- `git rev-list --objects --all`
- unreachable Git commits and trees from `git fsck --no-reflogs --unreachable`
- project parent/workspace locations under `/home/master`
- targeted Desktop, Downloads, Documents, Pictures, and `.local/share` paths
- protected nested `JARVIS/` repository filenames, without modifying it

## Candidate review

`/home/master/Pictures/Screenshot_2026-09-16_05_01_38.png` was inspected. It
is a WhatsApp desktop screenshot, not an approved JARVIS HUD reference.

The exact approved PNG was subsequently supplied at
`/home/master/Desktop/JARVIS/assets/hud/approved-ui.png` and verified as a
512x343 RGB PNG with SHA-256
`10a788cef3a00614a37a7cf88d073fd6799635e0acae9f2fca1a2bfc48515a65`.
It is installed unchanged at `assets/hud/approved-ui.png`.

## Certification consequence

The visual base is loaded unchanged by `app/hud/runtime.py`. The PySide6
runtime adds only transparent, bounded motion layers and has no policy or tool
authority.