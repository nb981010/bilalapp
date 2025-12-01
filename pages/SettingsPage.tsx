import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const SettingsPage: React.FC<{ addLog: (level:string, msg:string)=>void; refreshSchedule: ()=>void }> = ({ addLog, refreshSchedule }) => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen max-w-7xl mx-auto mb-6">
      <div className="bg-slate-900 rounded-2xl p-6 border border-slate-800 min-h-[70vh]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="px-3 py-1 bg-slate-800 rounded">Back</button>
            <h3 className="text-lg font-semibold">Settings</h3>
          </div>
        </div>

        <div>
          <SettingsPanel addLog={addLog} refreshSchedule={refreshSchedule} />
        </div>
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
        enabled_zones: JSON.stringify(enabledZones || [])
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
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Audio Systems</h3>
      <div className="space-y-3">
        <div className="flex items-center justify-between bg-slate-800 p-3 rounded">
          <div>
            <div className="font-medium">Sonos</div>
            <div className="text-xs text-slate-400">Enable Sonos control (cloud/local)</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" className="sr-only peer" checked={sonosEnabled} onChange={e=>setSonosEnabled(e.target.checked)} />
            <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:bg-emerald-500 transition-colors" />
            <span className={`ml-3 text-sm ${sonosEnabled ? 'text-white' : 'text-slate-400'}`}>{sonosEnabled ? 'On' : 'Off'}</span>
          </label>
        </div>

        <div className="flex items-center justify-between bg-slate-800 p-3 rounded">
          <div>
            <div className="font-medium">TOA (amplifier)</div>
            <div className="text-xs text-slate-400">Static/dummy config for TOA (no discovery yet)</div>
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
        </div>

        <div>
          <label className="text-xs text-slate-400">Enable Zones</label>
          <div className="space-y-2 mt-2 max-h-40 overflow-y-auto">
            {zones.map(z => (
              <div key={z.id} className="flex items-center justify-between bg-slate-800 p-2 rounded">
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

        <div className="flex gap-2">
          <button onClick={save} className="px-4 py-2 bg-emerald-600 rounded">Save Audio Settings</button>
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
