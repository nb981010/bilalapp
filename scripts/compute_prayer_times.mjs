import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import process from 'process';

function computeForDate(dateStr) {
  const coords = new Coordinates(25.2048, 55.2708);
  const params = CalculationMethod.Dubai();
  params.madhab = Madhab.Shafi;
  const date = dateStr ? new Date(dateStr) : new Date();
  const pt = new PrayerTimes(coords, date, params);
  const fmt = (dt) => {
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  };
  const out = {
    date: date.toISOString().slice(0,10),
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
