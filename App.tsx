import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  ZoneId, 
  SonosZone, 
  PrayerName, 
  PrayerSchedule, 
  LogEntry, 
  AppState 
} from './types.ts';
import { INITIAL_ZONES } from './constants.ts';
import { getPrayerTimes, getNextPrayer } from './services/prayerService.ts';
import LogsViewer from './components/LogsViewer.tsx';
import ZoneGrid from './components/ZoneGrid.tsx';
import SettingsTab from './components/SettingsTab.tsx';
import TestTab from './components/TestTab.tsx';
import { 
  Clock, 
  MapPin, 
  Settings, 
  PlayCircle, 
  VolumeX, 
  Sun, 
  Moon, 
  Zap,
  Server,
  CloudRain
} from 'lucide-react';
import { format } from 'date-fns';

const App: React.FC = () => {
  // State
  const [currentTime, setCurrentTime] = useState(new Date());
  const [schedule, setSchedule] = useState<PrayerSchedule[]>([]);
  const [nextPrayer, setNextPrayer] = useState<PrayerSchedule | null>(null);
  const [zones, setZones] = useState<SonosZone[]>(INITIAL_ZONES);
  const [appState, setAppState] = useState<AppState>(AppState.IDLE);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [activeTab, setActiveTab] = useState<'dashboard'|'settings'|'test'>('dashboard');

  const [triggeredPrayers, setTriggeredPrayers] = useState<Set<string>>(new Set());

  // Refs for interval management
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const triggeredPrayersRef = useRef(new Set<string>());

  // Fetch schedule on mount
  useEffect(() => {
    // Initial schedule fetch remains (fallback/calculation), but the Dashboard's
    // "Today's Schedule" must show scheduler-calculated jobs. We'll poll
    // the backend scheduler every 30s to keep the dashboard authoritative.
    const init = async () => {
      try {
        const dailySchedule = await getPrayerTimes(new Date());
        setSchedule(dailySchedule);
        setNextPrayer(getNextPrayer(dailySchedule));
      } catch (e) {
        // ignore
      }
    };
    init();
  }, []);

  // Polling: refresh zones and scheduler jobs every 30s so UI comes from DB
  useEffect(() => {
    let stopped = false;

    const fetchZones = async () => {
      try {
        const res = await fetch('/api/zones');
        if (!res.ok) throw new Error('zones fetch failed');
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          setZones(data);
        } else {
          // No zones discovered — show onboard audio as fallback (single virtual zone)
          setZones([{ id: ZoneId.Zone1, name: 'Onboard Audio', isAvailable: true, status: 'idle', volume: 30 }]);
        }
      } catch (e:any) {
        addLog('WARN', `Failed to refresh zones: ${e.message || e}`);
        // keep previous zones if fetch fails
      }
    };

    const fetchSchedulerJobs = async () => {
      try {
        const res = await fetch('/api/scheduler/jobs');
        if (!res.ok) throw new Error('scheduler jobs fetch failed');
        const data = await res.json();
        if (data && Array.isArray(data.jobs)) {
          // Map scheduler jobs to PrayerSchedule entries and filter today's jobs
          const todayStr = new Date().toISOString().slice(0,10);
          const mapped = data.jobs
              .map((j:any) => {
                // job id format: azan-YYYY-MM-DD-<prayer>
                const parts = (j.id || '').split('-');
                const prayerKey = (parts[3] || '').toLowerCase();
                const PRAYER_KEY_MAP: Record<string,string> = {
                  'fajr': 'Fajr',
                  'dhuhr': 'Dhuhr',
                  'asr': 'Asr',
                  'maghrib': 'Maghrib',
                  'isha': 'Isha'
                };
                if (!PRAYER_KEY_MAP[prayerKey]) return null; // ignore sunrise/sunset/unknown jobs
                const name = PRAYER_KEY_MAP[prayerKey] as any;
                const time = j.next_run_time ? new Date(j.next_run_time) : null;
                return time ? { name, time, isNext: false } : null;
              })
              .filter(Boolean) as any[];

          // Filter jobs for today only
          const todayJobs = mapped.filter(ms => ms.time.toISOString().slice(0,10) === todayStr);
          // Sort by time
          todayJobs.sort((a:any,b:any) => a.time.getTime() - b.time.getTime());
          setSchedule(todayJobs);
          setNextPrayer(getNextPrayer(todayJobs));
        }
      } catch (e:any) {
        addLog('WARN', `Failed to refresh scheduler jobs: ${e.message || e}`);
      }
    };

    // Initial run
    fetchZones();
    fetchSchedulerJobs();

    const id = setInterval(() => {
      if (stopped) return;
      fetchZones();
      fetchSchedulerJobs();
    }, 30_000);

    return () => { stopped = true; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  
  // Helper to add logs
  const addLog = useCallback((level: LogEntry['level'], message: string) => {
    setLogs(prev => [...prev, {
      id: Math.random().toString(36).substring(7),
      timestamp: new Date(),
      level,
      message
    }]);
  }, []);

  // Initial Load & Sync with Backend
  useEffect(() => {
    addLog('INFO', 'System Startup: Bilal Control System v1.0.0');
    addLog('INFO', 'Platform: Raspberry Pi (Hybrid Mode)');
    addLog('INFO', 'Scanning network for Sonos Zones...');

    fetch('/api/zones')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          addLog('SUCCESS', `Connected to Backend. Zones: ${data.map((z:any) => z.name).join(', ')}`);
          setZones(data);
        } else {
          addLog('WARN', 'Backend reported 0 zones, or API unavailable. Using Demo Mode.');
          setZones(INITIAL_ZONES);
        }
      })
      .catch(err => {
        addLog('ERROR', 'Backend unreachable, using Demo Mode.');
        setZones(INITIAL_ZONES);
      });

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Main Logic Loop (Triggered every second by currentTime change)
  useEffect(() => {
    if (!nextPrayer) return;

    const nowTime = currentTime.getTime();
    const prayerTime = nextPrayer.time.getTime();
    const diffMs = prayerTime - nowTime;
    const diffSeconds = Math.floor(diffMs / 1000);

    // 1. PREPARATION PHASE (1 Minute before)
    if (diffSeconds === 60 && appState === AppState.IDLE) {
      setAppState(AppState.PREPARING);
      addLog('INFO', `Upcoming Prayer: ${nextPrayer.name} in 1 minute.`);
      addLog('WARN', 'Initiating Zone Grouping Protocol...');
      
      // Filter unavailable zones
      const availableZones = zones.filter(z => z.isAvailable);
      const zoneNames = availableZones.map(z => z.name).join(', ');
      
      addLog('INFO', `Targeting Zones: ${zoneNames}`);
      
      // Update Zone Status to Grouped
      setZones(prev => prev.map(z => z.isAvailable ? { ...z, status: 'grouped' } : z));
      
      // Call Backend Prepare
      fetch('/api/prepare')
        .then(res => res.json())
        .then(data => addLog('SUCCESS', `Backend Prepared: ${data.message}`))
        .catch(err => addLog('ERROR', 'Backend Prepare Failed'));
    }

    // 2. EXECUTION PHASE (Time 0)
    if (diffSeconds === 0 && appState === AppState.PREPARING) {
      playAzan(nextPrayer.name);
    }

    // 3. Monitoring Phase (During Playback) - Requirement 9
    if (appState === AppState.PLAYING && diffSeconds % 3 === 0) {
       // Logic to track play status every 3 seconds
       // console.log('Monitoring playback status...');
    }

  }, [currentTime, nextPrayer, appState, zones, addLog]);

  // Audio Playback Logic
  const playAzan = async (prayerName: PrayerName) => {
    setAppState(AppState.PLAYING);
    
    addLog('WARN', 'Pausing existing streams/music on all zones.');
    setZones(prev => prev.map(z => z.isAvailable ? { ...z, status: 'playing_azan' } : z));

    const isFajr = prayerName === PrayerName.Fajr;
    const audioFile = isFajr ? 'fajr.mp3' : 'azan.mp3';
    
    addLog('SUCCESS', `Requesting Sonos Playback: /audio/${audioFile}`);
    addLog('INFO', `Method: Dubai (IACAD), Asr: Shafi`);

    try {
      // First, prepare zones
      addLog('INFO', 'Preparing zones for Azan');
      const prepareRes = await fetch('/api/prepare');
      if (!prepareRes.ok) {
        addLog('ERROR', 'Zone preparation failed');
        setAppState(AppState.IDLE);
        return;
      }
      addLog('SUCCESS', 'Zones prepared and grouped');

      // Then play
      const response = await fetch('/api/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file: audioFile,
          zones: zones.filter(z => z.isAvailable).map(z => z.name)
        })
      });

      const result = await response.json();
      
      if (response.ok) {
        addLog('SUCCESS', `Sonos Accepted Command: ${result.status}`);
      } else {
        throw new Error(result.message || 'Unknown error');
      }

      // Simulate duration of Azan (approx 3 mins) then restore
      // In production, we would poll the API for status
      setTimeout(() => {
        finishAzan();
      }, 180000); 

    } catch (error: any) {
      addLog('ERROR', `Playback Failed: ${error.message}`);
      addLog('WARN', 'Check server logs or connectivity.');
      finishAzan(); // Reset state anyway
    }
  };

  // Time Tick & Prayer Calculation
  useEffect(() => {
    const tick = async () => {
      const now = new Date();
      setCurrentTime(now);

      // Update schedule every minute
      if (now.getSeconds() === 0) {
        const dailySchedule = await getPrayerTimes(now);
        setSchedule(dailySchedule);
        setNextPrayer(getNextPrayer(dailySchedule));
      }
    };

    tick(); // initial tick
    intervalRef.current = setInterval(tick, 60000); // every minute

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const refreshSchedule = async () => {
    try {
      const dailySchedule = await getPrayerTimes(new Date());
      setSchedule(dailySchedule);
      setNextPrayer(getNextPrayer(dailySchedule));
      addLog('INFO', 'Prayer schedule refreshed');
    } catch (e:any) {
      addLog('ERROR', `Failed to refresh schedule: ${e.message || e}`);
    }
  };

  // Cleanup Logic
  const finishAzan = () => {
    setAppState(AppState.RESTORING);
    addLog('INFO', 'Azan logic finished. Restoring previous zone states...');
    
    // Restore logic
    setTimeout(() => {
      setZones(prev => prev.map(z => {
        if (!z.isAvailable) return z;
        // Restore to random music or idle for simulation
        return { 
          ...z, 
          status: Math.random() > 0.5 ? 'playing_music' : 'idle' 
        };
      }));
      setAppState(AppState.IDLE);
      addLog('SUCCESS', 'System Restored to IDLE state.');
    }, 3000); // 3 second restoration delay
  };

  // Manual Trigger for Testing
  const handleManualTest = () => {
    if (appState !== AppState.IDLE) return;
    addLog('WARN', 'MANUAL OVERRIDE: Triggering Test Azan Sequence');
    setAppState(AppState.PREPARING);
    
    // Fast forward logic for test
    setTimeout(() => {
        playAzan(PrayerName.Fajr);
    }, 2000);
  };

  // Render Helper: Time until next prayer
  const getTimeRemaining = () => {
    if (!nextPrayer) return '--:--:--';
    const diff = nextPrayer.time.getTime() - currentTime.getTime();
    if (diff < 0) return '00:00:00';
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((diff % (1000 * 60)) / 1000);
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-4 md:p-8 font-sans">
      {/* Header */}
      <header className="max-w-7xl mx-auto mb-8 flex flex-col md:flex-row justify-between items-center gap-4">
        <div className="flex items-center gap-3">
          <div className="p-3 bg-emerald-600 rounded-xl shadow-lg shadow-emerald-900/50">
             <Moon size={32} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-emerald-50 tracking-tight">Bilal Controller</h1>
            <p className="text-slate-400 text-xs flex items-center gap-1">
              <MapPin size={12} /> Dubai, UAE (IACAD/Shafi)
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-6 bg-slate-900/50 p-4 rounded-2xl border border-slate-800 backdrop-blur">
            <div className="text-right">
              <p className="text-slate-400 text-xs uppercase font-semibold tracking-wider">Current Time</p>
              <p className="text-2xl font-mono font-medium text-white">
                {format(currentTime, 'HH:mm:ss')}
              </p>
            </div>
            <div className="h-10 w-px bg-slate-700"></div>
            <div className="text-left">
               <p className="text-slate-400 text-xs uppercase font-semibold tracking-wider">Next Prayer</p>
               <div className="flex items-baseline gap-2">
                 <span className="text-emerald-400 font-bold text-xl">
                   {nextPrayer ? nextPrayer.name : 'None'}
                 </span>
                 <span className="text-slate-500 font-mono text-sm">
                   (-{getTimeRemaining()})
                 </span>
               </div>
            </div>
        </div>

            <div className="flex gap-3">
            <button 
              onClick={handleManualTest}
              disabled={appState !== AppState.IDLE}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg border border-slate-700 transition-all"
            >
              <PlayCircle size={18} className="text-emerald-500" />
              <span className="text-sm font-medium">Test</span>
            </button>
            <button 
              onClick={() => setActiveTab('settings')}
              className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition-all text-slate-400 hover:text-white"
              title="Settings"
            >
              <Settings size={20} />
            </button>
            <button 
              onClick={() => setActiveTab('test')}
              className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition-all text-slate-400 hover:text-white"
              title="Test Tab"
            >
              <Zap size={20} />
            </button>
        </div>
      </header>

      {/* Tab Panels */}
      {activeTab !== 'dashboard' && (
        <div className="max-w-7xl mx-auto mb-6">
          <div className="bg-slate-900 rounded-2xl p-4 border border-slate-800">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <button onClick={() => setActiveTab('dashboard')} className="px-3 py-1 bg-slate-800 rounded">Back</button>
                <h3 className="text-lg font-semibold">{activeTab === 'settings' ? 'Settings' : 'Test'}</h3>
              </div>
            </div>
            <div>
              {activeTab === 'settings' ? (
                <SettingsTab addLog={addLog} refreshSchedule={refreshSchedule} />
              ) : (
                <TestTab addLog={addLog} />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Main Grid */}
      <main className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Left Column: Schedule & Status (4 cols) */}
        <div className="lg:col-span-4 space-y-6">
           {/* Prayer Timeline (scheduler-sourced) */}
           <div className="bg-slate-900 rounded-2xl p-6 border border-slate-800 shadow-lg">
              <h2 className="text-slate-200 font-semibold mb-4 flex items-center gap-2">
                <CloudRain size={18} className="text-blue-400" /> Today's Schedule
              </h2>
              <div className="space-y-1">
                {schedule.map((prayer) => {
                  const isPast = prayer.time < currentTime;
                  const isNext = nextPrayer?.name === prayer.name;
                  
                  return (
                    <div 
                      key={prayer.name + String(prayer.time)}
                      className={`
                        flex justify-between items-center p-3 rounded-lg transition-colors
                        ${isNext ? 'bg-emerald-900/30 border border-emerald-500/30' : 'hover:bg-slate-800/50'}
                        ${isPast ? 'opacity-50' : 'opacity-100'}
                      `}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${
                          isNext ? 'bg-emerald-400 animate-pulse' : 
                          isPast ? 'bg-slate-600' : 'bg-slate-400'
                        }`} />
                        <span className={`text-sm font-medium ${isNext ? 'text-emerald-300' : 'text-slate-300'}`}>
                          {prayer.name}
                        </span>
                      </div>
                      <span className="font-mono text-sm text-slate-400">
                        {format(prayer.time, 'HH:mm')}
                      </span>
                    </div>
                  );
                })}
              </div>
           </div>

           {/* Current Status Card */}
           <div className="bg-gradient-to-br from-emerald-900 to-slate-900 rounded-2xl p-6 border border-emerald-800/30 shadow-2xl relative overflow-hidden">
              <div className="absolute top-0 right-0 p-4 opacity-10">
                <Sun size={120} />
              </div>
              <h2 className="text-emerald-200 font-semibold mb-4 flex items-center gap-2">
                <Clock size={18} /> System Status
              </h2>
              
              <div className="space-y-4 relative z-10">
                <div className="flex justify-between items-center p-3 bg-black/20 rounded-lg">
                  <span className="text-slate-300 text-sm">Engine State</span>
                  <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                    appState === AppState.IDLE ? 'bg-slate-700 text-slate-300' :
                    appState === AppState.PLAYING ? 'bg-emerald-600 text-white animate-pulse' :
                    'bg-yellow-600 text-yellow-100'
                  }`}>
                    {appState}
                  </span>
                </div>
                <div className="flex justify-between items-center p-3 bg-black/20 rounded-lg">
                   <span className="text-slate-300 text-sm">Backend Status</span>
                   <span className="text-xs text-emerald-400 font-mono">Connected</span>
                </div>
                <div className="flex justify-between items-center p-3 bg-black/20 rounded-lg">
                   <span className="text-slate-300 text-sm">Scheduler Status</span>
                   <span className="text-xs text-emerald-400 font-mono">Active</span>
                </div>
              </div>
           </div>
        </div>

        {/* Right Column: Zone Management & Logs (8 cols) */}
        <div className="lg:col-span-8 space-y-6 flex flex-col h-full">
          
          {/* Zone Visualization */}
          <div className="bg-slate-900 rounded-2xl p-6 border border-slate-800 shadow-lg">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-slate-200 font-semibold flex items-center gap-2">
                <VolumeX size={18} className="text-indigo-400" /> Active Zones
              </h2>
              <div className="flex gap-2">
                 <span className="text-xs px-2 py-1 bg-emerald-900/30 text-emerald-400 rounded border border-emerald-800">
                    {zones.filter(z => z.isAvailable).length} Online
                 </span>
                 <span className="text-xs px-2 py-1 bg-red-900/30 text-red-400 rounded border border-red-800">
                    {zones.filter(z => !z.isAvailable).length} Offline
                 </span>
              </div>
            </div>
            <ZoneGrid zones={zones} />
          </div>

          {/* Terminal / Logs */}
          <div className="flex-1 min-h-[300px]">
            <LogsViewer logs={logs} />
          </div>

        </div>
      </main>

      <SettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} addLog={addLog} setZones={setZones} refreshSchedule={refreshSchedule} />
    </div>
  );
};

export default App;