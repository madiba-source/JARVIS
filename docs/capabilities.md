# Capability Registry

Phase 14 exposes discovery metadata through the existing deterministic Phase 04 policy gateway. Discovery is observation only; it does not execute a discovered application or Kali tool.

## Application discovery

`ApplicationManager` reads `.desktop` entries from the user's local application directory and `/usr/share/applications`. It accepts only visible `Type=Application` entries whose executable resolves through `PATH`; shell wrappers, field substitutions, pipelines, redirections, and terminal entries are rejected.

Each record contains a display name, executable, desktop entry, aliases from `Keywords`, desktop categories, availability, supported lifecycle capabilities, risk level, and privilege requirement. Records are cached for 60 seconds. The policy operation `applications.refresh` explicitly invalidates the cache.

Launching remains the existing `application_control.launch` capability at L1 reversible risk and requires confirmation. It uses an argv tuple with `shell=False`, a bounded environment, and process observation. No discovered application is granted elevated privileges.

## Kali discovery

`KaliToolRegistry` checks a bounded classification catalogue against `PATH` with `shutil.which`. It reports only tools actually installed on the host. Current categories include information gathering, web, database, password/security auditing, wireless, reverse engineering, exploitation, sniffing/spoofing, and forensics. The catalogue is classification metadata, not an execution allowlist.

The policy operations are read-only:

```text
kali_capabilities.discover
kali_capabilities.refresh
```

They return executable paths, category, aliases, availability, risk level, and privilege metadata. No Kali tool is invoked by discovery. Network-capable or consequential operations remain unavailable until a separate typed capability is reviewed and registered through policy.

## Risk and confirmation

The existing levels remain authoritative:

- L0: read-only discovery, observation, and diagnostics
- L1: reversible application launch/close
- L2: user-data modification
- L3: destructive actions
- L4: privileged actions
- L5: external side effects

The policy engine decides allow, deny, resource admission, and confirmation. The coordinator cannot authorize itself. Global disable blocks discovery and execution alike.

## Limits and refresh

Discovery is bounded by the existing execution limits and does not continuously rescan. Application and Kali registries refresh on demand or after their cache TTL. Discovery metadata is not an authorization decision, and model-generated descriptions cannot expand the registry or terminal allowlist.
