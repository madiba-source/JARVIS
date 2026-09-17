# Desktop Control Operations

Phase 04 desktop control is backend-only and local-first. Capabilities are registered before the policy registry freezes and are invoked through `Phase04PolicyService.execute()`.

Application discovery reads XDG `.desktop` files and accepts only entries whose executable resolves through `PATH`, contains no field codes or shell metacharacters, and is executable. Launch and close operate only on discovered application IDs tracked by the manager; arbitrary PIDs and commands are not accepted.

Graceful close is an L1 reversible capability. Forceful termination is isolated as a separate L3 capability and always requires confirmation.

JARVIS disable invalidates new execution leases. It does not restrict the user's normal desktop, browser, terminal, or manual filesystem use.

Known limitations: application discovery is read-only metadata parsing; process identity is scoped to manager-owned `Popen` handles; no privileged operations are exposed.
