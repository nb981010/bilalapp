export enum ZoneId {
  Pool = 'Pool',
  Boy1 = 'Boy1',
  Zone1 = 'Zone1',
  Zone2 = 'Zone2',
  Zone3 = 'Zone3',
  Zone4 = 'Zone4',
  Zone5 = 'Zone5'
}

export interface SonosZone {
  id: ZoneId;
  name: string;
  isAvailable: boolean;
  status: 'idle' | 'playing_music' | 'grouped' | 'playing_azan';
  volume: number;
}

export enum PrayerName {
  Fajr = 'Fajr',
  Sunrise = 'Sunrise',
  Dhuhr = 'Dhuhr',
  Asr = 'Asr',
  Maghrib = 'Maghrib',
  Isha = 'Isha',
  None = 'None'
}

export interface PrayerSchedule {
  name: PrayerName;
  time: Date;
  isNext: boolean;
}

export interface LogEntry {
  id: string;
  timestamp: Date;
  level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS';
  message: string;
}

export enum AppState {
  IDLE = 'IDLE',
  PREPARING = 'PREPARING', // 1 min before
  PLAYING = 'PLAYING',
  RESTORING = 'RESTORING'
}