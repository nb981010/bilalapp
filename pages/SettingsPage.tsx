import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const SettingsPage: React.FC<{ addLog: (level:string, msg:string)=>void; refreshSchedule: ()=>void }> = ({ addLog, refreshSchedule }) => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen max-w-7xl mx-auto mb-6 px-4 lg:px-0">
      <div className="bg-slate-900 rounded-2xl p-6 border ring-1 ring-slate-800 shadow-sm min-h-[70vh]">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate('/')} className="px-3 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm transition">Back</button>
            <div>
              <h3 className="text-2xl font-semibold">Production Settings & Audio</h3>
              <div className="text-sm text-slate-400">Configure audio systems, zones and quick maintenance actions.</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => { try { refreshSchedule(); addLog('INFO','Triggered schedule refresh'); } catch (e){} }} className="px-3 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm transition">Refresh</button>
          </div>
        </div>

        <SettingsPanel addLog={addLog} refreshSchedule={refreshSchedule} />
      </div>
    </div>
  );
};

const SettingsPanel: React.FC<{ addLog: (level:string, msg:string)=>void; refreshSchedule: ()=>void }> = ({ addLog, refreshSchedule }) => {
  const [settings, setSettings] = React.useState<any>({});
  const [zones, setZones] = React.useState<any[]>([]);
  const [sonosEnabled, setSonosEnabled] = React.useState<boolean>(true);
  const [toaEnabled, setToaEnabled] = React.useState<boolean>(false);
  const [audioPriority, setAudioPriority] = React.useState<'online_first'|'offline_first'>('online_first');
  const [enabledZones, setEnabledZones] = React.useState<string[]>([]);
  const [playTol, setPlayTol] = React.useState<number>(5);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/settings');
        if (!res.ok) return;
        const data = await res.json();
        setSettings(data || {});
        setSonosEnabled(String(data.sonos_enabled || 'true') === 'true' || data.sonos_enabled === true);
        setToaEnabled(String(data.toa_enabled || 'false') === 'true' || data.toa_enabled === true);
        setAudioPriority(data.audio_priority || 'online_first');
        try {
          const ez = data.enabled_zones ? (typeof data.enabled_zones === 'string' ? JSON.parse(data.enabled_zones) : data.enabled_zones) : [];
          if (Array.isArray(ez)) setEnabledZones(ez);
          // load play tolerance (minutes) if present
          try {
            const p = Number(data.prayer_play_tolerance_min || data.prayer_play_tol_min || data.PRAYER_PLAY_TOL_MIN || data.play_tolerance_min);
            if (!isNaN(p) && p > 0) setPlayTol(p);
          } catch (e) {}
        } catch (e) {}
      } catch (e:any) { addLog('WARN', `Failed to load settings: ${e.message || e}`); }

      try {
        const rz = await fetch('/api/zones');
        if (rz.ok) {
          const zdata = await rz.json();
          setZones(zdata || []);
        }
      } catch (e:any) { addLog('WARN', `Failed to load zones: ${e.message || e}`); }
    })();
  }, [addLog]);

  const save = async () => {
    try {
      const payload:any = {
        sonos_enabled: sonosEnabled,
        toa_enabled: toaEnabled,
        audio_priority: audioPriority,
        enabled_zones: JSON.stringify(enabledZones || []),
        prayer_play_tolerance_min: Number(playTol || 5)
      };
      const headers:any = { 'Content-Type': 'application/json' };
      const pass = localStorage.getItem('bilal:passcode');
      if (pass) headers['X-BILAL-PASSCODE'] = pass;
      const res = await fetch('/api/settings', { method: 'POST', headers, body: JSON.stringify(payload) });
      if (res.ok) {
        addLog('SUCCESS', 'Saved audio settings');
        try { refreshSchedule(); } catch (e) {}
      } else {
        const d = await res.json().catch(()=>({}));
        addLog('ERROR', `Save failed: ${d.message || res.statusText}`);
      }
    } catch (e:any) { addLog('ERROR', `Save failed: ${e.message || e}`); }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2">
        <div className="bg-slate-800 p-4 rounded space-y-4">
          <h4 className="text-md font-semibold">Audio Systems</h4>

          <div className="space-y-3">
            <div className="flex items-center justify-between p-3 rounded bg-slate-700">
              <div>
                <div className="font-medium">Sonos</div>
                <div className="text-xs text-slate-400">Enable Sonos cloud/local control</div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" className="sr-only peer" checked={sonosEnabled} onChange={e=>setSonosEnabled(e.target.checked)} />
                <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:bg-emerald-500 transition-colors" />
                <span className={`ml-3 text-sm ${sonosEnabled ? 'text-white' : 'text-slate-400'}`}>{sonosEnabled ? 'On' : 'Off'}</span>
              </label>
            </div>

            <div className="flex items-center justify-between p-3 rounded bg-slate-700">
              <div>
                <div className="font-medium">TOA (amplifier)</div>
                <div className="text-xs text-slate-400">Fallback/TOA playback (no discovery)</div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" className="sr-only peer" checked={toaEnabled} onChange={e=>setToaEnabled(e.target.checked)} />
                <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:bg-emerald-500 transition-colors" />
                <span className={`ml-3 text-sm ${toaEnabled ? 'text-white' : 'text-slate-400'}`}>{toaEnabled ? 'On' : 'Off'}</span>
              </label>
            </div>

            <div>
              <label className="text-xs text-slate-400">Discovery Priority</label>
              <select value={audioPriority} onChange={e=>setAudioPriority(e.target.value as any)} className="p-2 bg-slate-800 rounded w-full mt-1">
                <option value="online_first">Online API First (default)</option>
                <option value="offline_first">Offline/Local First</option>
              </select>
              <div className="text-xs text-slate-500 mt-1">Choose whether to prefer cloud discovery or local discovery when finding audio systems.</div>
            </div>

            <div>
              <label className="text-xs text-slate-400">Enabled Zones</label>
              <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 max-h-56 overflow-y-auto">
                {zones.map(z => (
                  <div key={z.id} className="flex items-center justify-between p-2 rounded bg-slate-700">
                    <div>
                      <div className="font-medium">{z.name}</div>
                      <div className="text-xs text-slate-400">{z.isAvailable ? 'Available' : 'Offline'}</div>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input type="checkbox" className="sr-only peer" checked={enabledZones.includes(String(z.id))} onChange={e=>{
                        const id = String(z.id);
                        if (e.target.checked) setEnabledZones(prev => Array.from(new Set([...(prev||[]), id])));
                        else setEnabledZones(prev => (prev||[]).filter(x=>x!==id));
                      }} />
                      <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:bg-emerald-500 transition-colors" />
                    </label>
                  </div>
                ))}
                {zones.length === 0 ? <div className="text-xs text-slate-400">No zones discovered</div> : null}
              </div>
            </div>
            <div>
              <label className="text-xs text-slate-400">Playback Tolerance (minutes)</label>
              <input type="number" min={1} value={playTol} onChange={e => setPlayTol(Number(e.target.value || 0))} className="mt-1 p-2 bg-slate-800 rounded w-32" />
              <div className="text-xs text-slate-500 mt-1">Window to consider a play 'on time' for marking SUCCESS/FAILED.</div>
            </div>
          </div>

          <div className="flex items-center gap-3 mt-3">
            <button onClick={save} className="px-4 py-2 bg-emerald-600 rounded shadow">Save Audio Settings</button>
            <button onClick={() => { setSonosEnabled(false); setToaEnabled(false); addLog('INFO','Reset audio toggles'); }} className="px-3 py-2 bg-slate-700 rounded">Reset</button>
          </div>
        </div>
      </div>

      <div>
        <div className="bg-slate-800 p-4 rounded space-y-3">
          <h4 className="text-md font-semibold">Quick Actions</h4>
          <div className="text-sm text-slate-400">Helpful controls for testing and maintenance.</div>
          <div className="flex flex-col gap-2 mt-2">
            <button onClick={() => { refreshSchedule(); addLog('INFO','Forced schedule recompute'); }} className="w-full px-3 py-2 bg-blue-600 rounded">Force Recompute Schedule</button>
            <button onClick={() => { addLog('INFO','Opened zone debug (noop)'); }} className="w-full px-3 py-2 bg-slate-700 rounded">Run Zone Diagnostics</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
