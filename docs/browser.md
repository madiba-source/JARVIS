# Phase 08 Browser

## Status

Implemented: typed URL validation, bounded request schemas, isolated provider lifecycle, bounded DOM observations, untrusted-content labeling, policy registration, action limits, cancellation, and explicit unavailable behavior.

Partial: Playwright integration is optional. The current environment has Firefox but does not have the Python Playwright package or verified Playwright browser binaries. The provider reports a deterministic unavailable state until the optional dependency and browser runtime are explicitly installed.

## Boundary

Browser operations are registered as `browser_read` and `browser_action` in `Phase04PolicyService`. The agent sees executor-free catalog metadata. Execution still passes through policy evaluation, confirmation where required, resource admission, HMAC permits, execution leases, and the private registry executor.

No model-facing API exposes Playwright objects, cookies, credentials, arbitrary JavaScript, shell commands, downloads, or the user's existing browser profile.

## Trust and privacy

URLs accept only `http` and `https`. Page text, titles, DOM metadata, screenshots, and redirects are `UNTRUSTED_EXTERNAL_DATA`; they cannot authorize actions or modify policy. Observations are bounded and carry an observation identity and content hash. Browser content is not automatically written to memory.

## Explicit setup

Install the optional Python dependency with the project's normal package workflow, then install only the required Playwright Firefox browser binary explicitly. JARVIS does not download browser binaries automatically. Browser operation remains degraded when either dependency is absent.

Authentication is manual. Saved passwords, cookies, tokens, autofill, and browser history are not read. Downloads and uploads are not exposed by this phase.

## Limits

`BrowserConfig` bounds sessions, pages, actions, redirects, navigation/action timeouts, extracted text, DOM elements, screenshot bytes, and task duration metadata. There is no unrestricted crawler or continuous page loop.