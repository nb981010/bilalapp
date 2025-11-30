#!/usr/bin/env node
/*
  Simple Sonos Cloud microservice (Express)
  - OAuth user flow endpoints to obtain tokens
  - Stores tokens in SQLite (BILAL_DB_PATH)
  - Exposes control endpoints: /cloud/discover, /cloud/play, /cloud/stop, /cloud/setVolume, /cloud/group
  - Exposes /cloud/health and /cloud/is_available

  Environment variables:
    SONOS_CLIENT_ID, SONOS_CLIENT_SECRET, SONOS_REDIRECT_URI
    BILAL_DB_PATH (defaults to ../bilal_jobs.sqlite)
    SONOS_API_BASE (optional override)
    PORT (default 6000)

  Note: this is a convenience shim; adapt Sonos Cloud API endpoints as needed.
*/

const express = require('express');
const fetch = global.fetch || require('node-fetch');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const { URLSearchParams } = require('url');

const APP_DIR = path.join(__dirname, '..');
const DB_PATH = process.env.BILAL_DB_PATH || path.join(APP_DIR, 'bilal_jobs.sqlite');
const CLIENT_ID = process.env.SONOS_CLIENT_ID || '';
const CLIENT_SECRET = process.env.SONOS_CLIENT_SECRET || '';
const REDIRECT_URI = process.env.SONOS_REDIRECT_URI || 'http://localhost:6000/cloud/oauth/callback';
const API_BASE = process.env.SONOS_API_BASE || 'https://api.sonos.com';
const PORT = parseInt(process.env.PORT || '6000', 10);

function openDb() {
  return new sqlite3.Database(DB_PATH);
}

function ensureTable() {
  const db = openDb();
  db.run(`CREATE TABLE IF NOT EXISTS sonos_cloud_tokens (
    id INTEGER PRIMARY KEY,
    access_token TEXT,
    refresh_token TEXT,
    expires_at INTEGER
  )`);
  db.close();
}

async function getTokenRow() {
  return new Promise((resolve, reject) => {
    const db = openDb();
    db.get('SELECT * FROM sonos_cloud_tokens WHERE id=1', (err, row) => {
      db.close();
      if (err) return reject(err);
      resolve(row);
    });
  });
}

async function saveTokenRow({ access_token, refresh_token, expires_at }) {
  return new Promise((resolve, reject) => {
    const db = openDb();
    db.run(`INSERT OR REPLACE INTO sonos_cloud_tokens (id, access_token, refresh_token, expires_at) VALUES (1, ?, ?, ?)`, [access_token, refresh_token, expires_at], function (err) {
      db.close();
      if (err) return reject(err);
      resolve(true);
    });
  });
}

async function exchangeCodeForToken(code) {
  const tokenUrl = 'https://api.sonos.com/login/v3/oauth/access';
  const body = new URLSearchParams();
  body.append('grant_type', 'authorization_code');
  body.append('code', code);
  body.append('redirect_uri', REDIRECT_URI);
  const auth = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');
  const res = await fetch(tokenUrl, { method: 'POST', body: body.toString(), headers: { 'Authorization': `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' } });
  if (!res.ok) throw new Error(`Token exchange failed: ${res.status}`);
  return res.json();
}

async function refreshAccessToken(refresh_token) {
  const tokenUrl = 'https://api.sonos.com/login/v3/oauth/access';
  const body = new URLSearchParams();
  body.append('grant_type', 'refresh_token');
  body.append('refresh_token', refresh_token);
  const auth = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');
  const res = await fetch(tokenUrl, { method: 'POST', body: body.toString(), headers: { 'Authorization': `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' } });
  if (!res.ok) throw new Error(`Token refresh failed: ${res.status}`);
  return res.json();
}

async function ensureValidToken() {
  ensureTable();
  const row = await getTokenRow();
  if (!row) return null;
  const now = Math.floor(Date.now() / 1000);
  if (row.expires_at && row.expires_at - 60 > now) {
    return row.access_token;
  }
  // refresh
  try {
    const data = await refreshAccessToken(row.refresh_token);
    const expires_at = Math.floor(Date.now() / 1000) + (data.expires_in || 3600);
    await saveTokenRow({ access_token: data.access_token, refresh_token: data.refresh_token || row.refresh_token, expires_at });
    return data.access_token;
  } catch (e) {
    console.warn('refreshAccessToken failed', e.message || e);
    return null;
  }
}

const app = express();
app.use(express.json());

app.get('/cloud/health', async (req, res) => {
  try {
    const tok = await ensureValidToken();
    if (!tok) return res.json({ cloud: 'offline' });
    // test a lightweight API call
    const r = await fetch(`${API_BASE}/control/api/v1/players`, { headers: { Authorization: `Bearer ${tok}` } });
    if (r.ok) return res.json({ cloud: 'online' });
    return res.json({ cloud: 'offline' });
  } catch (e) {
    return res.json({ cloud: 'offline', error: e.message });
  }
});

app.get('/cloud/is_available', async (req, res) => {
  try {
    const tok = await ensureValidToken();
    return res.json({ available: !!tok });
  } catch (e) {
    return res.json({ available: false });
  }
});

app.get('/cloud/oauth/url', (req, res) => {
  const authUrl = `https://api.sonos.com/login/v3/oauth/authorize?client_id=${encodeURIComponent(CLIENT_ID)}&response_type=code&scope=playback-control-all&redirect_uri=${encodeURIComponent(REDIRECT_URI)}`;
  res.json({ url: authUrl });
});

app.get('/cloud/oauth/callback', async (req, res) => {
  try {
    const code = req.query.code;
    if (!code) return res.status(400).send('Missing code');
    const data = await exchangeCodeForToken(code);
    const expires_at = Math.floor(Date.now() / 1000) + (data.expires_in || 3600);
    await saveTokenRow({ access_token: data.access_token, refresh_token: data.refresh_token, expires_at });
    res.send('OK - tokens saved');
  } catch (e) {
    res.status(500).send('OAuth callback error: ' + (e.message || e));
  }
});

// Discover devices via Sonos Cloud players endpoint
app.get('/cloud/discover', async (req, res) => {
  try {
    const tok = await ensureValidToken();
    if (!tok) return res.status(503).json({ error: 'no_token' });
    const r = await fetch(`${API_BASE}/control/api/v1/players`, { headers: { Authorization: `Bearer ${tok}` } });
    if (!r.ok) return res.status(r.status).send(await r.text());
    const data = await r.json();
    res.json(data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Helper to call cloud control for an action - placeholder endpoints
app.post('/cloud/play', async (req, res) => {
  try {
    const { device_id, url } = req.body || {};
    const tok = await ensureValidToken();
    if (!tok) return res.status(503).json({ error: 'no_token' });
    if (!device_id || !url) return res.status(400).json({ error: 'missing device_id or url' });
    // Build play command according to Sonos cloud control API
    const body = { play: { playerId: device_id, action: { uri: url } } };
    // This is a simplification — replace with actual Sonos Cloud Control API calls
    const r = await fetch(`${API_BASE}/control/api/v1/players/${device_id}/playback/play`, { method: 'POST', headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ uri: url }) });
    if (!r.ok) return res.status(r.status).send(await r.text());
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/cloud/stop', async (req, res) => {
  try {
    const { device_id } = req.body || {};
    const tok = await ensureValidToken();
    if (!tok) return res.status(503).json({ error: 'no_token' });
    if (!device_id) return res.status(400).json({ error: 'missing device_id' });
    const r = await fetch(`${API_BASE}/control/api/v1/players/${device_id}/playback/stop`, { method: 'POST', headers: { Authorization: `Bearer ${tok}` } });
    if (!r.ok) return res.status(r.status).send(await r.text());
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/cloud/setVolume', async (req, res) => {
  try {
    const { device_id, level } = req.body || {};
    const tok = await ensureValidToken();
    if (!tok) return res.status(503).json({ error: 'no_token' });
    if (!device_id || typeof level === 'undefined') return res.status(400).json({ error: 'missing device_id or level' });
    const r = await fetch(`${API_BASE}/control/api/v1/players/${device_id}/volume`, { method: 'POST', headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ volume: level }) });
    if (!r.ok) return res.status(r.status).send(await r.text());
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/cloud/group', async (req, res) => {
  try {
    const { group } = req.body || {};
    const tok = await ensureValidToken();
    if (!tok) return res.status(503).json({ error: 'no_token' });
    if (!Array.isArray(group) || group.length < 2) return res.status(400).json({ error: 'invalid group list' });
    // Sonos cloud grouping API may differ; here we call a placeholder endpoint
    // Implement actual grouping per Sonos Cloud API documentation
    res.json({ ok: true, group });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => {
  ensureTable();
  console.log(`Sonos Cloud microservice listening on port ${PORT}`);
});
