import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import { DUBAI_COORDS } from '../constants.ts';
import { PrayerName, PrayerSchedule } from '../types.ts';

export const getPrayerTimes = (date: Date): PrayerSchedule[] => {
  const coords = new Coordinates(DUBAI_COORDS.latitude, DUBAI_COORDS.longitude);
  
  // Dubai (IACAD) Method
  const dubaiParams = CalculationMethod.Dubai();
  
  // Create a mutable copy of the parameters to avoid "Attempting to change value of a readonly property"
  // We copy the prototype and properties to ensure it passes any internal instance checks while allowing mutation
  const params = Object.assign(Object.create(Object.getPrototypeOf(dubaiParams)), dubaiParams);
  
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