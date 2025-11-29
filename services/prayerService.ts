import { Coordinates, CalculationMethod, PrayerTimes, Madhab } from 'adhan';
import { DUBAI_COORDS } from '../constants.ts';
import { PrayerName, PrayerSchedule } from '../types.ts';

// Try to prefer the backend scheduler as single source-of-truth. If scheduler jobs
// are not available for a prayer we fall back to local adhan calculation.
export const getPrayerTimes = async (date: Date): Promise<PrayerSchedule[]> => {
  const dateStr = date.toISOString().slice(0, 10); // YYYY-MM-DD

  // Helper: build local adhan-based schedule
  const buildLocal = (): PrayerSchedule[] => {
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

  try {
    const res = await fetch(`/api/scheduler/jobs`);
    if (!res.ok) return buildLocal();

    const body = await res.json();
    const jobs: Array<{ id: string; next_run_time: string }> = body.jobs || [];

    const prayers: PrayerSchedule[] = [];
    const order = [
      PrayerName.Fajr,
      PrayerName.Sunrise,
      PrayerName.Dhuhr,
      PrayerName.Asr,
      PrayerName.Maghrib,
      PrayerName.Isha,
    ];

    for (const p of order) {
      const jobId = `azan-${dateStr}-${p.toString().toLowerCase()}`;
      const job = jobs.find(j => j.id === jobId);
      if (job && job.next_run_time) {
        // Normalize to an ISO-like string for Date parsing
        const iso = job.next_run_time.replace(' ', 'T');
        const dt = new Date(iso);
        if (!isNaN(dt.getTime())) {
          prayers.push({ name: p, time: dt, isNext: false });
          continue;
        }
      }
      // Fallback to local calculation for this prayer only
      const local = buildLocal().find(lp => lp.name === p);
      if (local) prayers.push(local);
    }

    return prayers;
  } catch (e) {
    return buildLocal();
  }
};

// Returns the source used for prayer times: 'Scheduler' when backend scheduler
// provides jobs for the date, otherwise 'Local'.
export const getPrayerSource = async (date: Date): Promise<'Scheduler' | 'Local'> => {
  const dateStr = date.toISOString().slice(0, 10);
  try {
    const res = await fetch(`/api/scheduler/jobs`);
    if (!res.ok) return 'Local';
    const body = await res.json();
    const jobs: Array<{ id: string }> = body.jobs || [];
    // If any job for the date exists, prefer Scheduler as the source
    const found = jobs.some(j => j.id?.startsWith(`azan-${dateStr}-`));
    return found ? 'Scheduler' : 'Local';
  } catch (e) {
    return 'Local';
  }
};

export const getNextPrayer = (schedule: PrayerSchedule[]): PrayerSchedule | null => {
  const now = new Date();
  // Filter out Sunrise as we usually don't play Azan for Sunrise, strictly speaking, but listed for reference.
  // Usually Azan is played for Fajr, Dhuhr, Asr, Maghrib, Isha.
  const prayers = schedule.filter(p => p.name !== PrayerName.Sunrise);
  
  return prayers.find(p => p.time > now) || null;
};