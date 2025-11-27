import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import { DUBAI_COORDS } from '../constants.ts';
import { PrayerName, PrayerSchedule } from '../types.ts';

const toSchedule = (raw: any): PrayerSchedule[] => {
  // raw times are strings "HH:MM"; convert to Date objects for today
  const today = new Date();
  const dateStr = raw?.date || today.toISOString().slice(0,10);
  const [y, m, d] = dateStr.split('-').map((s: string) => parseInt(s, 10));
  const mk = (hhmm: string | undefined) => {
    if (!hhmm) return new Date();
    const [hh, mm] = hhmm.split(':').map((s: string) => parseInt(s, 10));
    return new Date(y, m - 1, d, hh || 0, mm || 0, 0);
  };
  return [
    { name: PrayerName.Fajr, time: mk(raw.fajr), isNext: false },
    { name: PrayerName.Sunrise, time: mk(raw.sunrise), isNext: false },
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

  // Fallback to local adhan computation
  const coords = new Coordinates(DUBAI_COORDS.latitude, DUBAI_COORDS.longitude);
  const dubaiParams = CalculationMethod.Dubai();
  const params = Object.assign(Object.create(Object.getPrototypeOf(dubaiParams)), dubaiParams);
  params.madhab = Madhab.Shafi;
  const prayerTimes = new PrayerTimes(coords, date, params);
  return [
    { name: PrayerName.Fajr, time: prayerTimes.fajr, isNext: false },
    { name: PrayerName.Sunrise, time: prayerTimes.sunrise, isNext: false },
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