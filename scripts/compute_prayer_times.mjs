import pkg from 'adhan';
const { PrayerTimes, CalculationMethod, Coordinates } = pkg;
import process from 'process';

// Usage: node scripts/compute_prayer_times.mjs YYYY-MM-DD lat lon [method]
// method: Makkah, MWL, Karachi, ISNA, Egypt, Tehran, Jafari

const args = process.argv.slice(2);
if (args.length < 3) {
  console.error('Usage: node compute_prayer_times.mjs YYYY-MM-DD lat lon [method]');
  process.exit(2);
}

const [dateStr, latStr, lonStr, methodName='Makkah'] = args;
const [y,m,d] = dateStr.split('-').map(x => parseInt(x,10));
const lat = parseFloat(latStr);
const lon = parseFloat(lonStr);

let method = CalculationMethod.MuslimWorldLeague();
try {
  switch((methodName||'').toLowerCase()){
    case 'mwl': method = CalculationMethod.MuslimWorldLeague(); break;
    case 'isna': method = CalculationMethod.NorthAmerica(); break; // ISNA ~ NorthAmerica
    case 'egypt': method = CalculationMethod.Egyptian(); break;
    case 'makkah': method = CalculationMethod.UmmAlQura(); break;
    case 'karachi': method = CalculationMethod.Karachi(); break;
    case 'tehran': method = CalculationMethod.Tehran(); break;
    case 'dubai': method = CalculationMethod.Dubai(); break;
    default: method = CalculationMethod.MuslimWorldLeague();
  }
} catch(e) {
  method = CalculationMethod.MuslimWorldLeague();
}

const coords = new Coordinates(lat, lon);
const date = new Date(y, m-1, d);
const times = new PrayerTimes(coords, date, method);

function fmt(t){
  if(!t) return null;
  // return HH:MM (24h) in local timezone
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || process.env.TZ || 'UTC';
  const fmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz });
  return fmt.format(t);
}

const out = {
  date: dateStr,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  fajr: fmt(times.fajr),
  sunrise: fmt(times.sunrise),
  dhuhr: fmt(times.dhuhr),
  asr: fmt(times.asr),
  maghrib: fmt(times.maghrib),
  isha: fmt(times.isha)
};

console.log(JSON.stringify(out));
