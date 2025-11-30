// backend/server.js
// Node Express backend that prefers Sonos Cloud control and falls back to a local
// SoCo microservice when cloud actions are unavailable or fail.

const express = require('express');
const fetch = require('node-fetch');
const bodyParser = require('body-parser');
const cloud = require('../cloud/sonosCloudClient');

const LOCAL_BASE = process.env.LOCAL_SONO_BASE || 'http://127.0.0.1:5001';
const PORT = process.env.SONOS_NODE_PORT || 3001;

const app = express();
app.use(bodyParser.json());

async function controlWithFallback(actionName, cloudFn, localPath, reqBody = {}) {
  try {
    const cloudOk = await cloud.isCloudAvailable();
    if (cloudOk) {
      try {
        const r = await cloudFn();
        return {source: 'cloud', result: r};
      } catch (err) {
        console.warn(`cloud ${actionName} failed:`, err.message || err);
      }
    }
  } catch (err) {
    console.warn('cloud availability check failed', err.message || err);
  }

  // fallback to local SoCo microservice
  try {
    const res = await fetch(`${LOCAL_BASE}${localPath}`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify(reqBody),
    });
    const json = await res.json();
    return {source: 'local', result: json};
  } catch (err) {
    console.error('local fallback failed', err.message || err);
    throw err;
  }
}

app.get('/sonos/health', async (req, res) => {
  const cloudOk = await cloud.isCloudAvailable();
  const localOk = await (async () => {
    try {
      const r = await fetch(`${LOCAL_BASE}/local/health`);
      const j = await r.json();
      return j.status === 'ok' || j.count > 0;
    } catch (e) {
      return false;
    }
  })();
  res.json({cloud: cloudOk, local: localOk});
});

app.post('/api/sonos/play', async (req, res) => {
  const {url, opts} = req.body || {};
  if (!url) return res.status(400).json({error: 'missing url'});
  try {
    const result = await controlWithFallback('play', () => cloud.play(url, opts), '/local/play', {url});
    res.json(result);
  } catch (e) {
    res.status(500).json({error: e.message || String(e)});
  }
});

app.post('/api/sonos/stop', async (req, res) => {
  try {
    const result = await controlWithFallback('stop', () => cloud.stop(), '/local/stop', {});
    res.json(result);
  } catch (e) {
    res.status(500).json({error: e.message || String(e)});
  }
});

app.post('/api/sonos/volume', async (req, res) => {
  const {level} = req.body || {};
  if (level === undefined) return res.status(400).json({error: 'missing level'});
  try {
    const result = await controlWithFallback('setVolume', () => cloud.setVolume(level), '/local/volume', {level});
    res.json(result);
  } catch (e) {
    res.status(500).json({error: e.message || String(e)});
  }
});

app.post('/api/sonos/group', async (req, res) => {
  const {group} = req.body || {};
  if (!Array.isArray(group)) return res.status(400).json({error: 'group must be array'});
  try {
    const result = await controlWithFallback('group', () => cloud.groupSpeakers(group), '/local/group', {group});
    res.json(result);
  } catch (e) {
    res.status(500).json({error: e.message || String(e)});
  }
});

app.post('/api/sonos/force-local', async (req, res) => {
  // For debugging: clear tokens / force local-only by removing access token
  try {
    await new Promise((resolve, reject) => cloud.setToken({access_token: null, refresh_token: null, expires_at: null}, (err) => (err ? reject(err) : resolve())));
    res.json({status: 'ok', message: 'cleared cloud token; local-only until re-auth'});
  } catch (e) {
    res.status(500).json({error: e.message || String(e)});
  }
});

app.listen(PORT, () => {
  console.log(`Sonos backend listening on port ${PORT}, local base ${LOCAL_BASE}`);
  // ensure DB table creation for cloud client
  try { cloud.initDb(); } catch (e) { console.warn('cloud.initDb failed', e); }
});
