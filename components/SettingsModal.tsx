import React, { useState, useEffect } from 'react';
import { X, Settings, Zap, Server } from 'lucide-react';
import { PrayerName } from '../types';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  addLog: (level: string, message: string) => void;
  setZones: (fn: any) => void;
  refreshSchedule: () => void;
};

const DEFAULT_PASSCODE = '1234';

const SettingsModal: React.FC<Props> = ({ isOpen, onClose, addLog, setZones, refreshSchedule }) => {
  const [unlocked, setUnlocked] = useState(false);
  const [passcode, setPasscode] = useState('');
  const [activeTab, setActiveTab] = useState<'settings'|'testing'>('settings');

  // Settings state
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
                <div className="grid grid-cols-2 gap-2">
                  <input value={lat} onChange={e=>setLat(e.target.value)} className="p-2 bg-slate-800 rounded" placeholder="Latitude" />
                  <input value={lon} onChange={e=>setLon(e.target.value)} className="p-2 bg-slate-800 rounded" placeholder="Longitude" />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <select value={calcMethod} onChange={e=>setCalcMethod(e.target.value)} className="p-2 bg-slate-800 rounded">
                    <option value="IACAD">IACAD (Dubai)</option>
                    <option value="ISNA">ISNA</option>
                    <option value="Makkah">Makkah</option>
                    <option value="Egypt">Egypt</option>
                  </select>
                  <select value={asrMadhab} onChange={e=>setAsrMadhab(e.target.value)} className="p-2 bg-slate-800 rounded">
                    <option>Shafi</option>
                    <option>Hanafi</option>
                  </select>
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
