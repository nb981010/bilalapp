import { PrayerName, PrayerSchedule } from '../types.ts';

const toSchedule = (raw: any): PrayerSchedule[] => {
  // raw times are ISO date-ish strings returned by backend in local timezone
  // Backend returns values like 'HH:MM' and a `date` key; parse into Date objects
  const dateStr = raw?.date || new Date().toISOString().slice(0,10);
  const [y, m, d] = dateStr.split('-').map((s: string) => parseInt(s, 10));

  const mk = (hhmm: string | undefined) => {
    if (!hhmm) return new Date(0);
    const [hh, mm] = hhmm.split(':').map((s: string) => parseInt(s, 10));
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
  // Backend is authoritative for prayer times. Frontend will only query `/api/prayertimes`
  const dateStr = date.toISOString().slice(0,10);
  const res = await fetch(`/api/prayertimes?date=${dateStr}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch prayertimes: ${res.status}`);
  }
  const data = await res.json();
  return toSchedule(data);
};

export const getNextPrayer = (schedule: PrayerSchedule[]): PrayerSchedule | null => {
  const now = new Date();
  const prayers = schedule.filter(p => p.name !== PrayerName.Sunrise);
  return prayers.find(p => p.time > now) || null;
};