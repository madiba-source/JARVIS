# Approved HUD

The canonical immutable base is `assets/hud/approved-ui.png`.

- Format: PNG, 512x343, RGB 8-bit
- SHA-256: `10a788cef3a00614a37a7cf88d073fd6799635e0acae9f2fca1a2bfc48515a65`
- UI technology: PySide6
- Runtime: `app/hud/runtime.py`

`HudRuntime` preserves the image as the base layer and draws only transparent
motion overlays: central breathing, slow sphere/ring rotation, deterministic
particle drift, synchronized brightness response, and global energy modulation.
The camera is the locked QWidget viewport. The timer is bounded at 33 ms and
stops on disable or shutdown. Asset integrity is checked before startup.

The HUD has no shell, tool, policy, or authorization authority. It is owned by
`JarvisCore` and degrades safely when Qt or rendering resources are unavailable.