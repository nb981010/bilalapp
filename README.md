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
