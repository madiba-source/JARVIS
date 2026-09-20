# Proactive Workflows

Phase 15 release version: `0.15.0`.

Phase 15 adds a bounded local notification scheduler in `app.proactive`. It is persistent, offline-capable, and separate from the model. The scheduler normalizes internal events, evaluates due persisted workflows, emits a local notification event, records execution history, and never treats model output as authorization.

## Supported triggers

The existing calendar subsystem supports calendar reminders, calendar event triggers, recurring calendar data, and timetable queries. The Phase 15 scheduler adds deterministic one-time notification workflows with timezone-aware timestamps. Application, filesystem, system, and internal events may be normalized as typed `ProactiveEvent` values, but observation alone does not create a workflow or execute an action.

## Workflow contract

Every proactive workflow has a UUID, name, timezone-aware trigger time, bounded notification text, enabled state, retry limit, runtime limit, creation time, and failure state. Runs are persisted with start/end time, duration, state, retry count, and failure category. Duplicate execution is prevented by an atomic pending-to-running claim and terminal state.

The current Phase 15 scheduler performs notifications only. Consequential actions such as application launch, filesystem mutation, browser actions, network requests, and privileged operations must continue through their existing typed policy capabilities and confirmation rules. There is no arbitrary scheduled command interface.

## Resource and safety behavior

There is one daemon scheduler thread per JARVIS core, an event wait while idle, a bounded queue of 128 pending workflows, at most 32 due items per cycle, and a maximum retry count of three. Retry exhaustion marks the workflow failed and emits a failure event. The scheduler has no infinite retry path and does not continuously poll the system.

`JarvisCore.disable()` activates the proactive kill switch, stops the scheduler, cancels pending/running Jarvis workflows, and leaves the operating system untouched. `enable()` restores only workflows cancelled by that global disable; user-cancelled workflows remain cancelled. Shutdown joins the scheduler thread.

## Recovery and limitations

Workflow rows and run history share the application SQLite database and use migration version 4. Database backup/restore therefore includes proactive schedules with calendar and memory state. A restart reloads pending workflows from SQLite. Calendar scheduler behavior remains governed by `CalendarConfig`; the proactive scheduler does not replace it. Filesystem watchers, resource-threshold triggers, voice commands, and consequential autonomous actions are not enabled by this phase.
