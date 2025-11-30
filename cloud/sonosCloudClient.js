// sonosCloudClient.js
// Minimal Sonos Cloud client scaffold. Stores tokens in local SQLite DB and provides
// placeholder cloud actions. Intended to be expanded with real Sonos Cloud API calls.

const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');

const DB_PATH = process.env.BILAL_DB_PATH || path.join(__dirname, '..', 'bilal_jobs.sqlite');

function initDb() {
  const dir = path.dirname(DB_PATH);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const db = new sqlite3.Database(DB_PATH);
  db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS sonos_cloud_tokens (
      id INTEGER PRIMARY KEY,
      access_token TEXT,
      refresh_token TEXT,
      expires_at INTEGER
    )`);
    // ensure a single row exists for id=1
    db.get('SELECT id FROM sonos_cloud_tokens WHERE id=1', (err, row) => {
      if (!row) db.run('INSERT INTO sonos_cloud_tokens (id) VALUES (1)');
    });
  });
  return db;
}

const db = initDb();

function getToken(cb) {
  db.get('SELECT access_token, refresh_token, expires_at FROM sonos_cloud_tokens WHERE id=1', (err, row) => {
    if (err) return cb(err);
    cb(null, row);
  });
}

function setToken({ access_token, refresh_token, expires_at }, cb) {
  db.run('UPDATE sonos_cloud_tokens SET access_token=?, refresh_token=?, expires_at=? WHERE id=1', [access_token, refresh_token, expires_at], function (err) {
    if (cb) cb(err);
  });
}

async function isCloudAvailable() {
  // Placeholder: check if access_token exists and not expired
  return new Promise((resolve, reject) => {
    getToken((err, row) => {
      if (err) return resolve(false);
      if (!row || !row.access_token) return resolve(false);
      const now = Math.floor(Date.now() / 1000);
      if (row.expires_at && row.expires_at < now) return resolve(false);
      resolve(true);
    });
  });
}

// Placeholder cloud actions - these should be implemented using Sonos Cloud Control API
async function discoverDevices() {
  // TODO: call Sonos cloud API to list households/devices
  return [];
}

async function play(url, opts = {}) {
  // TODO: call Sonos cloud API to start playback on a target speaker
  throw new Error('cloud play not implemented');
}

async function stop(opts = {}) {
  // TODO: implement
  throw new Error('cloud stop not implemented');
}

async function setVolume(level, opts = {}) {
  throw new Error('cloud setVolume not implemented');
}

async function groupSpeakers(speakerIds = []) {
  throw new Error('cloud groupSpeakers not implemented');
}

function initDb() {
  const db = new sqlite3.Database(DB_PATH);
  db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS sonos_cloud_tokens (
      id INTEGER PRIMARY KEY,
      access_token TEXT,
      refresh_token TEXT,
      expires_at INTEGER
    )`);
  });
  db.close();
}

async function getTokens() {
  return new Promise((resolve, reject) => {
    const db = new sqlite3.Database(DB_PATH);
    db.get('SELECT access_token,refresh_token,expires_at FROM sonos_cloud_tokens WHERE id = 1', (err, row) => {
      db.close();
      if (err) return reject(err);
      resolve(row || null);
    });
  });
}

async function saveTokens({ access_token, refresh_token, expires_at }) {
  return new Promise((resolve, reject) => {
    const db = new sqlite3.Database(DB_PATH);
    db.run('INSERT OR REPLACE INTO sonos_cloud_tokens (id, access_token, refresh_token, expires_at) VALUES (1,?,?,?)', [access_token, refresh_token, expires_at], function (err) {
      db.close();
      if (err) return reject(err);
      resolve(true);
    });
  });
}

// Placeholder: real Sonos Cloud API endpoints and OAuth flows are required.
// This implementation demonstrates structure and token storage/refresh handling.

async function refreshTokenIfNeeded() {
  const tokens = await getTokens();
  if (!tokens) return false;
  const now = Math.floor(Date.now() / 1000);
  // If token expires within 60 seconds, attempt refresh (placeholder)
  if (tokens.expires_at && tokens.expires_at - now < 60) {
    // TODO: call Sonos OAuth token endpoint with refresh_token
    console.warn('Token refresh required - no implementation provided');
    return false;
  }
  return true;
}

async function isCloudAvailable() {
  try {
    const ok = await refreshTokenIfNeeded();
    if (!ok) return false;
    const tokens = await getTokens();
    if (!tokens || !tokens.access_token) return false;
    // Optionally call a lightweight status endpoint on Sonos Cloud to verify connectivity.
    return true;
  } catch (e) {
    console.warn('isCloudAvailable error', e);
    return false;
  }
}

async function discoverDevices() {
  // Placeholder: call Sonos Cloud /household endpoints.
  // Return array of devices: { id, name, model, cloudState }
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  // TODO: implement actual discovery via Sonos Cloud API
  return [];
}

async function play(url) {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  // TODO: send play command via Sonos Cloud API for appropriate household/device
  throw new Error('Not implemented: Cloud play');
}

async function stop() {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  // TODO: send stop command via Sonos Cloud API
  throw new Error('Not implemented: Cloud stop');
}

async function setVolume(level) {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  // TODO: volume set via Sonos Cloud
  throw new Error('Not implemented: Cloud setVolume');
}

module.exports = {
  initDb,
  getTokens,
  saveTokens,
  refreshTokenIfNeeded,
  isCloudAvailable,
  discoverDevices,
  play,
  stop,
  setVolume,
  groupSpeakers,
  getToken,
  setToken,
};
