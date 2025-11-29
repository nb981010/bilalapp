import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
const coords = new Coordinates(25.2048, 55.2708);

// Direct params
const paramsDirect = CalculationMethod.Dubai();
paramsDirect.madhab = Madhab.Shafi;
const d = new Date();
const ptDirect = new PrayerTimes(coords, d, paramsDirect);

// Copied params like frontend
const dubaiParams = CalculationMethod.Dubai();
const paramsCopy = Object.assign(Object.create(Object.getPrototypeOf(dubaiParams)), dubaiParams);
paramsCopy.madhab = Madhab.Shafi;
const ptCopy = new PrayerTimes(coords, d, paramsCopy);

const pad = (n)=>String(n).padStart(2,'0');
function fmt(dt){ return `${pad(dt.getHours())}:${pad(dt.getMinutes())}`; }

console.log('Direct Fajr', fmt(ptDirect.fajr));
console.log('Copy   Fajr', fmt(ptCopy.fajr));
console.log('Direct Sunrise', fmt(ptDirect.sunrise));
console.log('Copy   Sunrise', fmt(ptCopy.sunrise));
console.log('Direct Dhuhr', fmt(ptDirect.dhuhr));
console.log('Copy   Dhuhr', fmt(ptCopy.dhuhr));
