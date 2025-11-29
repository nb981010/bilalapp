import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
const coords = new Coordinates(25.2048, 55.2708);
const params = CalculationMethod.Dubai();
params.madhab = Madhab.Shafi;
const d = new Date();
const pt = new PrayerTimes(coords, d, params);
const pad = (n)=>String(n).padStart(2,'0');
function fmt(dt){
  return `${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}
console.log('Fajr', fmt(pt.fajr));
console.log('Sunrise', fmt(pt.sunrise));
console.log('Dhuhr', fmt(pt.dhuhr));
console.log('Asr', fmt(pt.asr));
console.log('Maghrib', fmt(pt.maghrib));
console.log('Isha', fmt(pt.isha));
