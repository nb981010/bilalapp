import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import { DUBAI_COORDS } from '../constants.ts';
import { PrayerName, PrayerSchedule } from '../types.ts';

const toSchedule = (raw: any): PrayerSchedule[] => {
  // raw times are strings "HH:MM" in local timezone from backend
  // Convert to Date objects for today in local timezone
  const dateStr = raw?.date || new Date().toISOString().slice(0,10);
  const [y, m, d] = dateStr.split('-').map((s: string) => parseInt(s, 10));
  
  const mk = (hhmm: string | undefined) => {
    if (!hhmm) return new Date();
    const [hh, mm] = hhmm.split(':').map((s: string) => parseInt(s, 10));
    // Create Date object in local timezone
    return new Date(y, m - 1, d, hh, mm, 0);
  };
  
  return [
    { name: PrayerName.Fajr, time: mk(raw.fajr), isNext: false },
    { name: PrayerName.Dhuhr, time: mk(raw.dhuhr), isNext: false },
    { name: PrayerName.Asr, time: mk(raw.asr), isNext: false },
    { name: PrayerName.Maghrib, time: mk(raw.maghrib), isNext: false },
    { name: PrayerName.Isha, time: mk(raw.isha), isNext: false },
  ];
};

export const getPrayerTimes = async (date: Date): Promise<PrayerSchedule[]> => {
  // Try backend first
  try {
    const dateStr = date.toISOString().slice(0,10);
    const res = await fetch(`/api/prayertimes?date=${dateStr}`);
    if (res.ok) {
      const data = await res.json();
      return toSchedule(data);
    }
  } catch (e) {
    // ignore and fallback to local
  }
  // Fallback to local adhan computation but prefer server-side settings
  let lat = DUBAI_COORDS.latitude;
  let lon = DUBAI_COORDS.longitude;
  let calcMethod = 'Dubai';
  let asrMadhab = 'Shafi';
  try {
    const sres = await fetch('/api/settings');
    if (sres.ok) {
      const s = await sres.json();
      if (s.prayer_lat) lat = parseFloat(String(s.prayer_lat)) || lat;
      if (s.prayer_lon) lon = parseFloat(String(s.prayer_lon)) || lon;
      if (s.calc_method) calcMethod = String(s.calc_method) || calcMethod;
      if (s.asr_madhab) asrMadhab = String(s.asr_madhab) || asrMadhab;
    }
  } catch (e) {
    // ignore and fall back to defaults
  }

  const coords = new Coordinates(lat, lon);
  // Calculation method and madhab
  let methodParams: any;
  try {
    if (calcMethod === 'IACAD' || calcMethod === 'Dubai') methodParams = CalculationMethod.Dubai();
    else if (calcMethod === 'ISNA') methodParams = CalculationMethod.NorthAmerica();
    else if (calcMethod === 'Makkah') methodParams = CalculationMethod.UmmAlQura();
    else if (calcMethod === 'Egypt') methodParams = CalculationMethod.Egyptian();
    else if (calcMethod === 'Karachi') methodParams = CalculationMethod.Karachi();
    else if (calcMethod === 'Turkey') methodParams = CalculationMethod.Turkey();
    else methodParams = CalculationMethod.Dubai();
  } catch (e) {
    methodParams = CalculationMethod.Dubai();
  }
  const params = Object.assign(Object.create(Object.getPrototypeOf(methodParams)), methodParams);
  try {
    params.madhab = asrMadhab === 'Hanafi' ? Madhab.Hanafi : Madhab.Shafi;
  } catch (e) {
    params.madhab = Madhab.Shafi;
  }
  const prayerTimes = new PrayerTimes(coords, date, params);
  return [
    { name: PrayerName.Fajr, time: prayerTimes.fajr, isNext: false },
    { name: PrayerName.Dhuhr, time: prayerTimes.dhuhr, isNext: false },
    { name: PrayerName.Asr, time: prayerTimes.asr, isNext: false },
    { name: PrayerName.Maghrib, time: prayerTimes.maghrib, isNext: false },
    { name: PrayerName.Isha, time: prayerTimes.isha, isNext: false },
  ];
};

export const getNextPrayer = (schedule: PrayerSchedule[]): PrayerSchedule | null => {
  const now = new Date();
  const prayers = schedule.filter(p => p.name !== PrayerName.Sunrise);
  return prayers.find(p => p.time > now) || null;
};