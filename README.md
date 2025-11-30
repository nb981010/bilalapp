<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/drive/1h2MqFMXz1PFufOfwJTaOQWwAQGMgjgHE

## Run Locally

**Prerequisites:**  Node.js


1. Install dependencies:
   `npm install`
2. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key
3. Run the app:
   `npm run dev`

## Azan Playback Behavior

- The server enforces a single-attempt policy for automatic Azan playback: when `/api/play` is called for a scheduled Azan, the server will try to start playback once and verify it started. If the start fails, it will return an error and will not retry automatically.
- If you need to force a playback (for debugging or manual override), use the existing force mechanism/endpoints which can resume or force-play Azan until completion.

This prevents repeated, in‑vain restarts if the speaker fails to accept the Azan URI. See `server.py` for implementation details.

## Diagnostics & Debugging Endpoints

The backend exposes a few helpful endpoints for diagnosing scheduler state and testing:

- `GET /api/scheduler/jobs` : lists scheduled jobs (IDs and next run times).
- `POST /api/scheduler/force-schedule` : forces a rescan and scheduling run for today.
- `POST /api/scheduler/simulate-play` : append a simulated play-history event for testing scheduling logic. JSON body example: `{"file":"azan.mp3","ts":"2025-11-27T18:31:00+04:00"}`.

## Settings & Testing (UI)

The app includes a passcode-protected Settings modal (click the gear icon in the header).

- Default passcode: `1234` (change via the Settings -> General -> Change Passcode UI).
- General tab: change latitude, longitude, calculation method, and Asr madhab — these are saved to `localStorage` and used by the client prayer-time calculator.
- Testing tab: run a Test Azan in `simulate` mode (UI-only), or trigger server test plays.
- `Append Play History` will call the backend's test endpoint and insert play-history entries used by scheduler logic.

Server exposes a test endpoint for controlled test behavior:

- `POST /api/test/play` : simulate a play on the server by appending a play-history entry. JSON body example: `{"file":"azan.mp3","volume":50}`. This endpoint does not attempt real Sonos control and is safe for testing.

Backend settings endpoints (stored in SQLite `bilal_jobs.sqlite` by default):

- `GET /api/settings` : returns current production settings (falls back to defaults: Dubai coords, IACAD, Shafi, CSS/adahn/sonos modes = online).
- `POST /api/settings` : update production settings. JSON body example: `{"prayer_lat":"25.2048","prayer_lon":"55.2708","calc_method":"IACAD","asr_madhab":"Shafi","css_mode":"online","adhan_mode":"online","sonos_mode":"online"}`.
- `GET /api/test/settings` and `POST /api/test/settings` : same schema but stored separately for test environment.

When the Settings UI saves values they are written to `settings` (production) or `test_settings` (testing) DB tables. The server's scheduling and prayer calculations prefer DB-configured values and will fall back to the defaults when missing.


Use `journalctl -u bilal-beapp.service -f` to follow Gunicorn/server logs (they are sent to journald).

Quick links
- `CODE_OF_CONDUCT.md`: Operational rules, defaults, fallbacks, testing isolation, and safe service handling.
