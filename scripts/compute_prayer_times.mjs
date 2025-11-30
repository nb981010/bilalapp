import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import process from 'process';

function computeForDate(dateStr) {
  const coords = new Coordinates(25.2048, 55.2708);
  const params = CalculationMethod.Dubai();
  params.madhab = Madhab.Shafi;
  
  // Parse date string as local Dubai date at noon
  let date;
  if (dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    // Create date at noon local time to ensure we're in the middle of the day
    date = new Date(y, m - 1, d, 12, 0, 0);
  } else {
    date = new Date();
  }
  
  const pt = new PrayerTimes(coords, date, params);
  
  // Format times in local timezone - adhan already returns Date objects in local time
  const fmt = (dt) => {
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  };
  
  const out = {
    date: dateStr || date.toISOString().slice(0,10),
    fajr: fmt(pt.fajr),
    sunrise: fmt(pt.sunrise),
    dhuhr: fmt(pt.dhuhr),
    asr: fmt(pt.asr),
    maghrib: fmt(pt.maghrib),
    isha: fmt(pt.isha)
  };
  return out;
}

const arg = process.argv[2];
try {
  const res = computeForDate(arg);
  console.log(JSON.stringify(res));
} catch (e) {
  console.error(JSON.stringify({ error: String(e) }));
  process.exit(2);
}
