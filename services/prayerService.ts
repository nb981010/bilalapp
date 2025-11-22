import { Coordinates, CalculationMethod, PrayerTimes, Madhab, DateComponents } from 'adhan';
import { DUBAI_COORDS } from '../constants';
import { PrayerName, PrayerSchedule } from '../types';

export const getPrayerTimes = (date: Date): PrayerSchedule[] => {
  const coords = new Coordinates(DUBAI_COORDS.latitude, DUBAI_COORDS.longitude);
  
  // Dubai (IACAD) Method
  const params = CalculationMethod.Dubai();
  
  // Shafi (Standard) for Asr
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
  // Filter out Sunrise as we usually don't play Azan for Sunrise, strictly speaking, but listed for reference.
  // Usually Azan is played for Fajr, Dhuhr, Asr, Maghrib, Isha.
  const prayers = schedule.filter(p => p.name !== PrayerName.Sunrise);
  
  return prayers.find(p => p.time > now) || null;
};