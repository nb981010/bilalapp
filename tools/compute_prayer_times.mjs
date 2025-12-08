import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import process from 'process';

// Usage: node compute_prayer_times.mjs YYYY-MM-DD lat lon TZ
// Example: node compute_prayer_times.mjs 2025-11-29 25.2048 55.2708 Asia/Dubai

function usage() {
  console.error('Usage: node compute_prayer_times.mjs YYYY-MM-DD lat lon [TZ]');
  process.exit(2);
}

if (process.argv.length < 5) usage();

const dateStr = process.argv[2];
const lat = parseFloat(process.argv[3]);
const lon = parseFloat(process.argv[4]);
const tz = process.argv[5] || 'Asia/Dubai';

// Set TZ for Node so Date objects are produced in that local timezone
process.env.TZ = tz;

const parts = dateStr.split('-').map(x => parseInt(x, 10));
const year = parts[0], month = parts[1], day = parts[2];
const date = new Date(year, month - 1, day);

const coords = new Coordinates(lat, lon);
const params = CalculationMethod.Dubai();
params.madhab = Madhab.Shafi;

const times = new PrayerTimes(coords, date, params);

const out = {
  fajr: times.fajr ? times.fajr.toISOString() : null,
  sunrise: times.sunrise ? times.sunrise.toISOString() : null,
  dhuhr: times.dhuhr ? times.dhuhr.toISOString() : null,
  asr: times.asr ? times.asr.toISOString() : null,
  maghrib: times.maghrib ? times.maghrib.toISOString() : null,
  isha: times.isha ? times.isha.toISOString() : null,
  sunset: times.sunset ? times.sunset.toISOString() : null
};

console.log(JSON.stringify(out));
