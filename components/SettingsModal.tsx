import React, { useState, useEffect } from 'react';
import { X, Settings, Zap, Server, MapPin } from 'lucide-react';
import { PrayerName } from '../types';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  addLog: (level: string, message: string) => void;
  setZones: (fn: any) => void;
  refreshSchedule: () => void;
};

const DEFAULT_PASSCODE = '1234';

// Preset locations with their specific calculation methods
const PRESET_LOCATIONS: Record<string, {lat: number, lon: number, calcMethod: string, asrMadhab: string}> = {
  'Dubai': { lat: 25.2048, lon: 55.2708, calcMethod: 'IACAD', asrMadhab: 'Shafi' },
  'AbuDhabi': { lat: 24.4539, lon: 54.3773, calcMethod: 'IACAD', asrMadhab: 'Shafi' },
  'Riyadh': { lat: 24.7136, lon: 46.6753, calcMethod: 'Makkah', asrMadhab: 'Shafi' },
  'Cairo': { lat: 30.0444, lon: 31.2357, calcMethod: 'Egypt', asrMadhab: 'Shafi' },
  'Karachi': { lat: 24.8607, lon: 67.0011, calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
  'Islamabad': { lat: 33.6844, lon: 73.0479, calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
  'Delhi': { lat: 28.6139, lon: 77.2090, calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
  'Lahore': { lat: 31.5204, lon: 74.3587, calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
  'Mumbai': { lat: 19.0760, lon: 72.8777, calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
  'Istanbul': { lat: 41.0082, lon: 28.9784, calcMethod: 'Turkey', asrMadhab: 'Hanafi' },
  'Ankara': { lat: 39.9208, lon: 32.8541, calcMethod: 'Turkey', asrMadhab: 'Hanafi' },
  'London': { lat: 51.5074, lon: -0.1278, calcMethod: 'ISNA', asrMadhab: 'Shafi' },
  'NewYork': { lat: 40.7128, lon: -74.0060, calcMethod: 'ISNA', asrMadhab: 'Shafi' },
  'Jakarta': { lat: -6.2088, lon: 106.8456, calcMethod: 'IACAD', asrMadhab: 'Shafi' },
  'Custom': { lat: 0, lon: 0, calcMethod: 'IACAD', asrMadhab: 'Shafi' }
};

// Top 15 cities to show in dropdown (order matters)
const TOP_CITIES = ['Dubai','AbuDhabi','Riyadh','Cairo','Karachi','Islamabad','Delhi','Lahore','Mumbai','Istanbul','Ankara','London','NewYork','Jakarta','Custom'];

const SettingsModal: React.FC<Props> = ({ isOpen, onClose, addLog, setZones, refreshSchedule }) => {
  const [unlocked, setUnlocked] = useState(false);
  const [passcode, setPasscode] = useState('');
  const [activeTab, setActiveTab] = useState<'settings'|'testing'>('settings');

  // Settings state
  const [selectedLocation, setSelectedLocation] = useState<string>('Dubai');
  const [lat, setLat] = useState<string>('25.2048');
  const [lon, setLon] = useState<string>('55.2708');
  const [calcMethod, setCalcMethod] = useState<string>('IACAD');
  const [asrMadhab, setAsrMadhab] = useState<string>('Shafi');
  const [cssMode, setCssMode] = useState<'online'|'offline'>('online');
  const [adhanMode, setAdhanMode] = useState<'online'|'offline'>('online');
  const [sonosMode, setSonosMode] = useState<'online'|'offline'>('online');

  // Testing state
  const [env, setEnv] = useState<string>('simulate');
  const [testFile, setTestFile] = useState<string>('azan.mp3');
  const [testVolume, setTestVolume] = useState<number>(50);
  const [simSilent, setSimSilent] = useState<boolean>(false);

  // Passcode change state (declare hooks unconditionally to preserve hook order)
  const [newPasscode, setNewPasscode] = useState('');
  const [confirmPasscode, setConfirmPasscode] = useState('');

  useEffect(() => {
    // load saved settings from server
    if (!isOpen) return;
    (async () => {
      try {
        const res = await fetch('/api/settings');
        if (!res.ok) return;
        const data = await res.json();
        if (data.prayer_lat) setLat(String(data.prayer_lat));
        if (data.prayer_lon) setLon(String(data.prayer_lon));
        if (data.calc_method) setCalcMethod(String(data.calc_method));
        if (data.asr_madhab) setAsrMadhab(String(data.asr_madhab));
        if (data.css_mode) setCssMode(data.css_mode === 'offline' ? 'offline' : 'online');
        if (data.adhan_mode) setAdhanMode(data.adhan_mode === 'offline' ? 'offline' : 'online');
        if (data.sonos_mode) setSonosMode(data.sonos_mode === 'offline' ? 'offline' : 'online');
      } catch (e) {
        // ignore
      }
    })();
  }, [isOpen]);

  if (!isOpen) return null;

  const tryUnlock = () => {
    (async () => {
      try {
        const res = await fetch('/api/settings');
        let stored = DEFAULT_PASSCODE;
        if (res.ok) {
          const data = await res.json();
          if (data.passcode) stored = String(data.passcode);
        }
        if (passcode === stored) {
          setUnlocked(true);
          addLog('SUCCESS', 'Settings unlocked');
        } else {
          addLog('ERROR', 'Incorrect passcode');
        }
      } catch (e:any) {
        addLog('ERROR', `Unlock failed: ${e.message || e}`);
      }
    })();
  };

  const handleLocationChange = (location: string) => {
    setSelectedLocation(location);
    if (location !== 'Custom') {
      const preset = PRESET_LOCATIONS[location as keyof typeof PRESET_LOCATIONS];
      setLat(String(preset.lat));
      setLon(String(preset.lon));
      setCalcMethod(preset.calcMethod);
      setAsrMadhab(preset.asrMadhab);
    }
  };

  const detectLocation = () => {
    if (!navigator.geolocation) {
      addLog('ERROR', 'Geolocation not supported by browser');
      return;
    }
    addLog('INFO', 'Detecting location...');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const detectedLat = position.coords.latitude.toFixed(4);
        const detectedLon = position.coords.longitude.toFixed(4);
        setLat(detectedLat);
        setLon(detectedLon);
        setSelectedLocation('Custom');
        // Default placeholders until reverse-geocode resolves
        setCalcMethod('IACAD');
        setAsrMadhab('Shafi');
        addLog('INFO', `Location detected: ${detectedLat}, ${detectedLon} (resolving country...)`);

        // Reverse geocode using Nominatim to determine country and pick appropriate calculation/madhab
        (async () => {
          try {
            const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${position.coords.latitude}&lon=${position.coords.longitude}`;
            const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!res.ok) {
              addLog('WARN', `Reverse geocode failed: ${res.status}`);
              return;
            }
            const json = await res.json();
            const cc = (json.address && json.address.country_code) ? String(json.address.country_code).toLowerCase() : '';
            // Country-based defaults
            const countryMap: Record<string, {calcMethod: string, asrMadhab: string}> = {
              'pk': { calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
              'in': { calcMethod: 'Karachi', asrMadhab: 'Hanafi' },
              'tr': { calcMethod: 'Turkey', asrMadhab: 'Hanafi' },
              'sa': { calcMethod: 'Makkah', asrMadhab: 'Shafi' },
              'ae': { calcMethod: 'IACAD', asrMadhab: 'Shafi' },
              'eg': { calcMethod: 'Egypt', asrMadhab: 'Shafi' },
              'us': { calcMethod: 'ISNA', asrMadhab: 'Shafi' },
              'gb': { calcMethod: 'ISNA', asrMadhab: 'Shafi' },
              'id': { calcMethod: 'IACAD', asrMadhab: 'Shafi' }
            };
            if (cc && countryMap[cc]) {
              setCalcMethod(countryMap[cc].calcMethod);
              setAsrMadhab(countryMap[cc].asrMadhab);
              addLog('SUCCESS', `Detected country ${json.address.country || cc.toUpperCase()}; using ${countryMap[cc].calcMethod} / ${countryMap[cc].asrMadhab}`);
            } else {
              addLog('INFO', `Detected country ${json.address && json.address.country ? json.address.country : cc}. Using default calculation method.`);
            }
          } catch (e:any) {
            addLog('WARN', `Reverse geocode error: ${e.message || e}`);
          }
        })();
      },
      (error) => {
        addLog('ERROR', `Failed to detect location: ${error.message}`);
      }
    );
  };

  const saveSettings = () => {
    (async () => {
      try {
        const payload = {
          prayer_lat: lat,
          prayer_lon: lon,
          calc_method: calcMethod,
          asr_madhab: asrMadhab,
          css_mode: cssMode,
          adhan_mode: adhanMode,
          sonos_mode: sonosMode
        };
        // Attach passcode header when unlocked so server can enforce production updates
        const headers: any = { 'Content-Type': 'application/json' };
        if (unlocked && passcode) headers['X-BILAL-PASSCODE'] = passcode;
        const res = await fetch('/api/settings', { method: 'POST', headers, body: JSON.stringify(payload) });
        if (res.ok) {
          addLog('SUCCESS', 'Saved settings');
          try { refreshSchedule(); } catch (e) {}
        } else {
          const d = await res.json().catch(()=>({}));
          addLog('ERROR', `Failed to save settings: ${d.message || res.statusText}`);
        }
      } catch (e:any) {
        addLog('ERROR', `Save failed: ${e.message || e}`);
      }
    })();
  };

  const savePasscode = () => {
    if (!newPasscode) { addLog('ERROR', 'New passcode cannot be empty'); return; }
    if (newPasscode !== confirmPasscode) { addLog('ERROR', 'Passcode confirmation does not match'); return; }
    try {
      // store passcode in DB settings
      (async () => {
        try {
          const headers: any = { 'Content-Type': 'application/json' };
          if (unlocked && passcode) headers['X-BILAL-PASSCODE'] = passcode;
          const res = await fetch('/api/settings', { method: 'POST', headers, body: JSON.stringify({ passcode: newPasscode }) });
          if (res.ok) {
            addLog('SUCCESS', 'Passcode updated');
            setNewPasscode(''); setConfirmPasscode('');
          } else {
            addLog('ERROR', 'Failed to update passcode');
          }
        } catch (e:any) { addLog('ERROR', `Failed to set passcode: ${e.message || e}`); }
      })();
    } catch (e:any) {
      addLog('ERROR', `Failed to set passcode: ${e.message || e}`);
    }
  };

  const doTestAzan = async () => {
    addLog('INFO', `Testing Azan: env=${env} file=${testFile} volume=${testVolume}`);
    if (env === 'simulate') {
      // local UI simulation: set zones to playing_azan and restore after short duration
      setZones((prev:any) => prev.map((z:any) => z.isAvailable ? { ...z, status: 'playing_azan', volume: testVolume } : z));
      addLog('SUCCESS', 'Simulated Azan started (local)');
      setTimeout(() => {
        setZones((prev:any) => prev.map((z:any) => z.isAvailable ? { ...z, status: Math.random() > 0.5 ? 'playing_music' : 'idle' } : z));
        addLog('SUCCESS', 'Simulated Azan finished (local)');
      }, 10000);
      return;
    }

    // Call backend for server-based testing. Use test endpoint when server_test is selected.
    try {
      const url = env === 'server_test' ? '/api/test/play' : '/api/play';
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: simSilent ? 'silent' : testFile, volume: testVolume })
      });
      const data = await res.json();
      if (res.ok) addLog('SUCCESS', `Server accepted test play: ${data.status || 'ok'}`);
      else addLog('ERROR', `Server failed test play: ${data.message || JSON.stringify(data)}`);
    } catch (e:any) {
      addLog('ERROR', `Test play request failed: ${e.message}`);
    }
  };

  const appendJobHistory = async (file = 'azan.mp3') => {
    try {
      const when = new Date().toISOString();
      // Use simulate-play (production) — test endpoint appends via /api/test/play if needed
      const res = await fetch('/api/scheduler/simulate-play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file, ts: when })
      });
      const data = await res.json();
      if (res.ok) addLog('SUCCESS', `Appended simulated play: ${file}`);
      else addLog('ERROR', `Failed to append simulated play: ${JSON.stringify(data)}`);
    } catch (e:any) {
      addLog('ERROR', `Failed to append play history: ${e.message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="bg-slate-900 text-white rounded-xl max-w-3xl w-full p-6 z-10">
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-3">
            <Settings />
            <h3 className="text-lg font-semibold">Settings</h3>
          </div>
          <button onClick={onClose} className="p-2 rounded hover:bg-slate-800"><X /></button>
        </div>

        {!unlocked ? (
          <div>
            <p className="text-sm text-slate-400 mb-4">Enter passcode to access settings.</p>
            <div className="flex gap-2">
              <input value={passcode} onChange={e => setPasscode(e.target.value)} className="flex-1 p-2 bg-slate-800 rounded" placeholder="Passcode" />
              <button onClick={tryUnlock} className="px-4 py-2 bg-emerald-600 rounded">Unlock</button>
            </div>
          </div>
        ) : (
          <div>
            <div className="flex gap-2 mb-4">
              <button onClick={() => setActiveTab('settings')} className={`px-3 py-2 rounded ${activeTab==='settings' ? 'bg-emerald-600' : 'bg-slate-800'}`}>General</button>
              <button onClick={() => setActiveTab('testing')} className={`px-3 py-2 rounded ${activeTab==='testing' ? 'bg-emerald-600' : 'bg-slate-800'}`}>Testing</button>
            </div>

            {activeTab === 'settings' ? (
              <div className="space-y-4">
                <h4 className="font-semibold">Prayer / Locale</h4>
                
                {/* Location Preset Dropdown */}
                <div className="space-y-2">
                  <label className="text-xs text-slate-400">Select Location</label>
                  <div className="flex gap-2">
                    <select 
                      value={selectedLocation} 
                      onChange={e => handleLocationChange(e.target.value)} 
                      className="flex-1 p-2 bg-slate-800 rounded"
                    >
                      {TOP_CITIES.map(key => {
                        const p = PRESET_LOCATIONS[key];
                        const label = key === 'NewYork' ? 'New York' : key === 'AbuDhabi' ? 'Abu Dhabi' : key;
                        const meta = key === 'Custom' ? 'Custom Location' : `${label} (${p.calcMethod}, ${p.asrMadhab})`;
                        return <option key={key} value={key}>{meta}</option>;
                      })}
                    </select>
                    <button 
                      onClick={detectLocation}
                      className="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded flex items-center gap-2 whitespace-nowrap"
                      title="Detect my location"
                    >
                      <MapPin size={16} />
                      Detect
                    </button>
                  </div>
                </div>

                {/* Coordinates */}
                <div className="grid grid-cols-2 gap-2">
                  <input 
                    value={lat} 
                    onChange={e => { setLat(e.target.value); setSelectedLocation('Custom'); }} 
                    className="p-2 bg-slate-800 rounded" 
                    placeholder="Latitude" 
                  />
                  <input 
                    value={lon} 
                    onChange={e => { setLon(e.target.value); setSelectedLocation('Custom'); }} 
                    className="p-2 bg-slate-800 rounded" 
                    placeholder="Longitude" 
                  />
                </div>

                {/* Calculation Methods */}
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-xs text-slate-400">Calculation Method</label>
                    <select value={calcMethod} onChange={e=>setCalcMethod(e.target.value)} className="w-full p-2 bg-slate-800 rounded">
                      <option value="IACAD">IACAD (Dubai)</option>
                      <option value="ISNA">ISNA (North America)</option>
                      <option value="Makkah">Makkah (Umm Al-Qura)</option>
                      <option value="Egypt">Egypt</option>
                      <option value="Karachi">Karachi (Pakistan/India)</option>
                      <option value="Turkey">Turkey</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Asr Madhab</label>
                    <select value={asrMadhab} onChange={e=>setAsrMadhab(e.target.value)} className="w-full p-2 bg-slate-800 rounded">
                      <option>Shafi</option>
                      <option>Hanafi</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2 mt-2">
                  <div>
                    <label className="text-xs text-slate-400">CSS Mode</label>
                    <select value={cssMode} onChange={e=>setCssMode(e.target.value as any)} className="p-2 bg-slate-800 rounded w-full">
                      <option value="online">Online (CDN)</option>
                      <option value="offline">Offline (compiled)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Adhan Mode</label>
                    <select value={adhanMode} onChange={e=>setAdhanMode(e.target.value as any)} className="p-2 bg-slate-800 rounded w-full">
                      <option value="online">Online (API)</option>
                      <option value="offline">Offline (local)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Sonos Mode</label>
                    <select value={sonosMode} onChange={e=>setSonosMode(e.target.value as any)} className="p-2 bg-slate-800 rounded w-full">
                      <option value="online">Cloud API</option>
                      <option value="offline">Local (SoCo)</option>
                    </select>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={saveSettings} className="px-4 py-2 bg-emerald-600 rounded">Save</button>
                  <button onClick={() => { localStorage.removeItem('bilal:passcode'); addLog('INFO','Passcode cleared') }} className="px-4 py-2 bg-slate-700 rounded">Clear Passcode</button>
                </div>
                <div className="mt-4 border-t border-slate-800 pt-3">
                  <h5 className="font-medium">Change Passcode</h5>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <input value={newPasscode} onChange={e=>setNewPasscode(e.target.value)} placeholder="New passcode" className="p-2 bg-slate-800 rounded" />
                    <input value={confirmPasscode} onChange={e=>setConfirmPasscode(e.target.value)} placeholder="Confirm passcode" className="p-2 bg-slate-800 rounded" />
                  </div>
                  <div className="mt-2">
                    <button onClick={savePasscode} className="px-3 py-2 bg-indigo-600 rounded">Save Passcode</button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <h4 className="font-semibold">Testing Environment</h4>
                <div className="grid grid-cols-2 gap-2">
                  <select value={env} onChange={e=>setEnv(e.target.value)} className="p-2 bg-slate-800 rounded">
                    <option value="simulate">Local Simulation</option>
                    <option value="server_test">Server (test)</option>
                    <option value="server">Server (live)</option>
                  </select>
                  <select value={testFile} onChange={e=>setTestFile(e.target.value)} className="p-2 bg-slate-800 rounded">
                    <option value="azan.mp3">azan.mp3</option>
                    <option value="fajr.mp3">fajr.mp3</option>
                    <option value="silent">Silent</option>
                  </select>
                </div>
                  <div className="grid grid-cols-3 gap-2 mt-2">
                    <div>
                      <label className="text-xs text-slate-400">CSS Mode (test)</label>
                      <select className="p-2 bg-slate-800 rounded w-full" value={cssMode} onChange={e=>setCssMode(e.target.value as any)}>
                        <option value="online">Online</option>
                        <option value="offline">Offline</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-slate-400">Adhan Mode (test)</label>
                      <select className="p-2 bg-slate-800 rounded w-full" value={adhanMode} onChange={e=>setAdhanMode(e.target.value as any)}>
                        <option value="online">Online</option>
                        <option value="offline">Offline</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-slate-400">Sonos Mode (test)</label>
                      <select className="p-2 bg-slate-800 rounded w-full" value={sonosMode} onChange={e=>setSonosMode(e.target.value as any)}>
                        <option value="online">Cloud</option>
                        <option value="offline">SoCo</option>
                      </select>
                    </div>
                  </div>
                  <div className="flex gap-2 mt-2">
                    <button onClick={async () => {
                      try {
                        const payload = { prayer_lat: lat, prayer_lon: lon, calc_method: calcMethod, asr_madhab: asrMadhab, css_mode: cssMode, adhan_mode: adhanMode, sonos_mode: sonosMode };
                        const res = await fetch('/api/test/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                        if (res.ok) addLog('SUCCESS', 'Saved test settings'); else addLog('ERROR', 'Failed to save test settings');
                      } catch (e:any) { addLog('ERROR', `Failed to save test settings: ${e.message || e}`); }
                    }} className="px-3 py-2 bg-emerald-600 rounded">Save Test Settings</button>
                  </div>
                <div>
                  <label className="text-sm text-slate-400">Volume: {testVolume}</label>
                  <input type="range" min={0} max={100} value={testVolume} onChange={e=>setTestVolume(parseInt(e.target.value))} className="w-full" />
                </div>
                <div className="flex gap-2">
                  <button onClick={doTestAzan} className="px-4 py-2 bg-emerald-600 rounded flex items-center gap-2"><Zap /> Test Azan</button>
                  <button onClick={() => appendJobHistory(testFile)} className="px-4 py-2 bg-slate-700 rounded">Append Play History</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default SettingsModal;
