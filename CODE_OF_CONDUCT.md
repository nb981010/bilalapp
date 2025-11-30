Bilal App — Code of Conduct (Operational Rules)

Purpose
-------
This file documents operational rules and expected behavior for the Bilal app front-end and back-end interaction, defaults, fallbacks, testing, and service management. It is authoritative for developers and operators unless a separate governance document supersedes it.

App structure
-------------
1. Front-end is a read/write UI only; it displays and updates what is stored in the database. The front-end never performs application logic or calculations itself — it only issues requests to the backend and renders database values.
2. The front-end contains three main parts:
   - Dashboard: primary view; shows data from the DB.
   - Settings: persisted configuration editor; updates DB settings.
   - Testing: a sandbox/editor to make test-only DB changes and run test flows against the server app or test DB.
3. On the Dashboard there is a gear/settings icon; clicking it opens the Settings and Testing panes/tabs.

Data, defaults and precedence
-----------------------------
4. Dashboard page takes its displayed values from the database. The front-end must not infer or override settings beyond what the DB provides.
5. The Settings page modifies production database settings. Changes here are considered authoritative for normal operation.
6. The Testing page modifies test database settings only (or uses clearly-separated test keys/config). The Testing tab must be explicitly isolated from production settings.
7. When the Test page runs flows it must use a server or server mode that accepts test values (test DB, test API keys, or test endpoints) and must not alter production state unless explicitly requested and authorized.

Services and components
-----------------------
8. The application deploys as multiple services: `bilalapp.service`, `Bilal.beapp.service`, and `bilal.feapp.service`. Systemd or orchestration manifests should reflect which component each service runs.
9. All prayer/time calculations depend on three configuration values:
   - `location`
   - `calculation method`
   - `ASR Madhab` (school of thought, e.g., Standard/Shafi)
10. Default configuration values (used when no DB setting exists):
   - location: `Dubai`
   - calculation method: `IACAD`
   - ASR Madhab: `Standard` (Shafi)
11. If database settings exist (set via the Settings tab), they override the defaults. If a DB setting is missing, the app must fall back to the defaults above.

Online / offline strategies and fallbacks
---------------------------------------
12. CSS (media/style controls or similar external service) has two modes: online and off-line. Default should be online; if the online method fails, fall back to the off-line method automatically.
13. Adhaan (prayer time) calculation has two modes: API-based (online) and off-line. Use API-based calculation as the default; on failure or unreachable API, fall back to the off-line calculation library implemented in the backend.
14. All calculations (whether online API or off-line library) must be executed in the backend; the front-end only requests results and displays them.
15. Sonos control has two modes: cloud API (online) and SoCo (local/off-line). Prefer cloud API, fall back to SoCo when cloud is unavailable.

Test page options and behavior
-----------------------------
16. The Testing page must provide explicit toggles/options for each of the following so operators can exercise combinations safely:
   - CSS mode: `online` / `off-line`
   - Adhan calculation mode: `online` / `off-line`
   - Calculation execution mode: `online` / `off-line` (i.e., whether to call remote calculation API or use the backend off-line library)
   Each toggle in Testing mode must operate on a test-config context and must not change production settings.

Service start/stop and process management
----------------------------------------
17. When starting or stopping services the operator tooling must:
   - Check ports in use before attempting start. If a required port is in use, report the PID and service owner and do not blindly kill unrelated processes.
   - Only terminate (kill) processes that belong to this app (e.g., processes whose command line or service unit name includes `bilal`, or run as the expected system user). Do not kill unrelated system processes.
   - Ensure clean shutdown and restart: stop the service unit, wait for termination, verify the port is free, then start the service unit and verify the process is listening on the expected port.

Operational guidance and safety
-------------------------------
- Always keep production settings and test settings separated. The Settings tab writes production DB; Testing tab writes only to test DB or test context.
- Backups: Before applying changes to production settings that affect calculations (location/method/ASR), take a configuration backup or snapshot of the DB keys modified.
- Logging: All calculation mode decisions (API vs offline), fallbacks, and errors must be logged server-side with enough context to reproduce and investigate.

Enforcement & scope
--------------------
This document is a technical code of conduct for the Bilal app's runtime and developer/operator behavior. It is intended for maintainers, operators, and developers. Violations (for example, tests that accidentally modify production settings) should be reported and corrected.

18. CI / Server-side enforcement: Add CI checks or server-side enforcement to ensure the Testing UI cannot modify production settings.
   - CI: include static checks or tests that flag front-end code calling production endpoints without providing the required authentication header (see server enforcement below).
   - Server: provide an optional enforcement switch (environment variable `BILAL_ENFORCE_SETTINGS_API`) that, when enabled, requires the header `X-BILAL-PASSCODE` with the current passcode for any POST to `/api/settings`.
   - Purpose: these controls prevent accidental or malicious UI/test flows from altering production configuration. Keep test settings endpoints (`/api/test/settings`) separate and auditable.

19. Dashboard Schedule visibility: Today's Schedule shown on the Dashboard must display only scheduler-calculated schedules.
   - The Dashboard's "Today's Schedule" should not include ad-hoc or test-inserted play entries; it must show jobs produced by the scheduler (whether calculated via online API or by the import/off-line adhan calculation in the backend).
   - If a test flow needs to preview schedules, it must do so in the Testing view or against the test settings endpoint; production dashboard must not surface test-only or manually inserted entries.
   - Operators may enable `BILAL_ENFORCE_SETTINGS_API` in production to ensure the front-end cannot write production settings without the passcode header.

How to use this file
---------------------
- Developers: Implement front-end behavior so that the UI obeys the separation between Dashboard, Settings, and Testing described above.
- Operators: Use the service names listed under Services and follow the start/stop process checks described in Service start/stop and process management.
- Maintainers: When adding features that change how calculations or fallbacks are chosen, update this document and add server-side logging to make decisions auditable.

Next steps (recommended)
------------------------
- Optionally add a short link to this file from `README.md` so operators can read these rules quickly.
- Add server-side checks that ensure requests coming from the Testing UI are confined to test modes/endpoints.

Contact
-------
For questions about this document or to propose changes, open an issue or a PR in this repository and tag the maintainers.
