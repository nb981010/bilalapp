# Design Instructions

This document maps feature requirements into three sections and indicates current implementation status and pointers to code where applicable.

## 1) Front-end

- Front only shows what is there in the database front and doesn't control backend.
  - Implementation: Front-end should be read-only for production settings. Any mutation endpoints require explicit server-side authorization. See `server.py` test-token enforcement for endpoints that perform test/force actions.

- Front has three parts: Dashboard, Settings, Testing.
  - Dashboard displays schedules and system status pulled from the DB via backend APIs.
  - Settings updates persisted configuration in the DB only (server-side validation required).
  - Testing is a UI that talks to a test-only API surface and must not be allowed to modify production settings.

- On the dashboard, a gear icon opens the Settings and Testing tabs.
  - Implementation detail: front UI should navigate to settings/testing routes client-side; backend exposes read-only APIs used by dashboard.

- Dashboard page takes input from database.

- Settings page changes database settings.

- Testing page changes database settings only for a test database or when explicitly allowed with a testing token.

- Test page uses server app, but with test values or test database (must not affect production DB).

Notes / Files:
- Server-side enforcement for testing endpoints is implemented in `server.py` — these endpoints require a matching `X-Testing-Token` header to perform changes.

## 2) Backend

- The app is separated into three services: `bilalapp.main.service`, `bilalapp.be.service`, `bilalapp.fe.service`.
  - Systemd unit: `deploy/bilal-server.service` manages the backend (BE) service.
  - `tools/manage_app.sh` manages stopping/starting the frontend and backend and checks ports before binding.

- All calculations depend on three values: location, calculation method, and ASR madhab.
  - Defaults: location = Dubai, calculation method = IACAD, ASR madhab = Shafi (standard).
  - When settings are missing, the backend falls back to these defaults but will persist configured values when provided.

- Two CSS modes: online (default) with offline fallback.
- Two Adhan calculation methods: online API based with offline fallback.
- All calculations are performed by the backend (regardless of online/offline source).

- Two Sonos control modes: cloud API (online) and SoCo (offline) fallback.

- Start/stop service behavior:
  - Ports are checked before starting; existing processes on ports are inspected and only processes belonging to this app (or matching server command) are stopped.
  - `tools/manage_app.sh` implements these safeguards; it will only kill processes whose command line matches the app directory or `server.py`/`npm` patterns.

- Add stricter watchdog: playback duration verification and coordinator track info logging.
  - Implementation note: We have added a playback monitor in `playback.py` and enhanced logging; further instrumentation can be added to persist coordinator track periodically.

- When azan plays, ensure other playback is stopped and azan resumes if interrupted.
  - Backend playback logic attempts robust recovery and attempts to restore/ungroup other players after playback.

- Create history of scheduled/ran/completed jobs in DB.
  - Implementation: APScheduler jobstore is persisted to `jobs.sqlite`. Play markers/history are recorded to `logs/played_markers.json` and `logs/play_history.json`. Consider migrating these to a proper DB table as next step.

Notes / Files:
- `server.py` — scheduler, playback, API routes.
- `tools/manage_app.sh` — process management helper (improved to verify process ownership/command line before kill).
- `deploy/bilal-server.service` — systemd unit.

## 3) DB and Other

- Default behavior when no settings present: use defaults (Dubai, IACAD, Shafi) and accept settings from the Settings page to persist them.

- Testing UI must not modify production settings:
  - Server-side enforcement: mutating/testing endpoints require a `X-Testing-Token` matching `TESTING_TOKEN` env var. Without that, the server returns HTTP 403 for test/force operations.

- CI Checks / Server enforcement suggestion:
  - Add CI tests that exercise the Settings API and ensure that test endpoints require the testing token.
  - Add server-side logging and alarms if settings are modified outside of authorized channels.

- Multiple audio backends:
  - 1) on-board audio
  - 2) Sonos cloud API (preferred) with SoCo fallback
  - 3) TOA system

Implementation status summary
- Design updated in this document and server-side testing enforcement implemented.
- Process management script hardened.
- Remaining work suggestions:
  - Migrate play history and markers into a persisted DB table for stronger queries and retention.
  - Add CI tests as part of pipeline to validate testing-ui protections.
  - Add optional DB-backed settings model and endpoints if not already present (recommended).
