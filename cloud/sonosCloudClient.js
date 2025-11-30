// sonosCloudClient.js
// Minimal Sonos Cloud client scaffold. Stores tokens in local SQLite DB and provides
// placeholder cloud actions. Intended to be expanded with real Sonos Cloud API calls.

import sqlite3pkg from 'sqlite3';
import path from 'path';
import fs from 'fs';

const sqlite3 = sqlite3pkg.verbose();
const DB_PATH = process.env.BILAL_DB_PATH || path.join(new URL('..', import.meta.url).pathname, 'bilal_jobs.sqlite');

function ensureDbDirExists() {
  const dir = path.dirname(DB_PATH);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function initDb() {
  ensureDbDirExists();
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

async function refreshTokenIfNeeded() {
  const tokens = await getTokens();
  if (!tokens) return false;
  const now = Math.floor(Date.now() / 1000);
  if (tokens.expires_at && tokens.expires_at - now < 60) {
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
    return true;
  } catch (e) {
    console.warn('isCloudAvailable error', e);
    return false;
  }
}

async function discoverDevices() {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  return [];
}

async function play(url) {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  throw new Error('Not implemented: Cloud play');
}

async function stop() {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  throw new Error('Not implemented: Cloud stop');
}

async function setVolume(level) {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  throw new Error('Not implemented: Cloud setVolume');
}

async function groupSpeakers(speakerIds = []) {
  if (!await isCloudAvailable()) throw new Error('Cloud unavailable');
  throw new Error('Not implemented: Cloud groupSpeakers');
}

export {
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
};
