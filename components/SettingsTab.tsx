import React, { useEffect, useState } from 'react';

const SettingsTab: React.FC<{ addLog: (level:string, msg:string)=>void; refreshSchedule: ()=>void }> = ({ addLog, refreshSchedule }) => {
  const [settings, setSettings] = useState<any>({});
  const [audioFiles, setAudioFiles] = useState<any[]>([]);
  const [fileInput, setFileInput] = useState<File | null>(null);
  const [qariName, setQariName] = useState('');
  // Audio system UI state
  const [sonosEnabled, setSonosEnabled] = useState<boolean>(true);
  const [toaEnabled, setToaEnabled] = useState<boolean>(false);
  const [audioPriority, setAudioPriority] = useState<'online_first'|'offline_first'>('online_first');
  const [discoveredZones, setDiscoveredZones] = useState<any[]>([]);
  const [enabledZones, setEnabledZones] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/settings');
        if (!res.ok) return;
        const data = await res.json();
        setSettings(data);
        // load new audio-related settings
        if (typeof data.sonos_enabled !== 'undefined') setSonosEnabled(String(data.sonos_enabled) === 'true' || data.sonos_enabled === true);
        if (typeof data.toa_enabled !== 'undefined') setToaEnabled(String(data.toa_enabled) === 'true' || data.toa_enabled === true);
        if (data.audio_priority) setAudioPriority(data.audio_priority === 'offline_first' ? 'offline_first' : 'online_first');
        try {
          if (data.enabled_zones) {
            const ez = typeof data.enabled_zones === 'string' ? JSON.parse(data.enabled_zones) : data.enabled_zones;
            if (Array.isArray(ez)) setEnabledZones(ez.map((x:any)=>String(x)));
          }
        } catch (e) {}
      } catch (e) {
        // ignore
      }
      fetchAudioList();
      // fetch zones for enable/disable UI
      try {
        const rz = await fetch('/api/zones');
        if (rz.ok) {
          const zd = await rz.json();
          setDiscoveredZones(zd || []);
        }
      } catch (e) {}
    })();
  }, []);

  const fetchAudioList = async () => {
    try {
      const res = await fetch('/api/audio/list');
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.files) setAudioFiles(data.files);
    } catch (e) {
      // ignore
    }
  };

  const saveSettings = async () => {
    try {
      const headers:any = { 'Content-Type': 'application/json' };
      // include passcode if stored in localStorage
      const pass = localStorage.getItem('bilal:passcode');
      if (pass) headers['X-BILAL-PASSCODE'] = pass;
      // include our audio-specific keys in the payload
      const payload = Object.assign({}, settings, {
        sonos_enabled: sonosEnabled,
        toa_enabled: toaEnabled,
        audio_priority: audioPriority,
        enabled_zones: JSON.stringify(enabledZones || [])
      });
      const res = await fetch('/api/settings', { method: 'POST', headers, body: JSON.stringify(payload) });
      if (res.ok) {
        addLog('SUCCESS', 'Production settings saved');
        try { refreshSchedule(); } catch(e){}
      } else {
        const d = await res.json().catch(()=>({}));
        addLog('ERROR', `Save failed: ${d.message || res.statusText}`);
      }
    } catch (e:any) {
      addLog('ERROR', `Save failed: ${e.message || e}`);
    }
  };

  const handleUpload = async (e:React.FormEvent) => {
    e.preventDefault();
    if (!fileInput) return addLog('ERROR','No file selected');
    try {
      const form = new FormData();
      form.append('file', fileInput);
      form.append('qari_name', qariName || '');
      const headers:any = {};
      const pass = localStorage.getItem('bilal:passcode');
      if (pass) headers['X-BILAL-PASSCODE'] = pass;
      const res = await fetch('/api/audio/upload', { method: 'POST', body: form, headers });
      const d = await res.json();
      if (res.ok) {
        addLog('SUCCESS', `Uploaded audio ${d.filename}`);
        setFileInput(null);
        setQariName('');
        fetchAudioList();
      } else {
        addLog('ERROR', `Upload failed: ${d.message || JSON.stringify(d)}`);
      }
    } catch (e:any) {
      addLog('ERROR', `Upload error: ${e.message || e}`);
    }
  };

  // small helper to show upload guidance
  const uploadGuidance = () => {
    return 'Accepts .mp3/.wav/.ogg files. Max size: 10MB by default.';
  };

  const handleDelete = async (filename:string) => {
    if (!confirm(`Delete audio ${filename}? This cannot be undone.`)) return;
    try {
      const pass = localStorage.getItem('bilal:passcode');
      const headers:any = {};
      if (pass) headers['X-BILAL-PASSCODE'] = pass;
      const res = await fetch(`/api/audio/${encodeURIComponent(filename)}`, { method: 'DELETE', headers });
      const d = await res.json();
      if (res.ok) {
        addLog('SUCCESS', `Deleted ${filename}`);
        fetchAudioList();
      } else {
        addLog('ERROR', `Delete failed: ${d.message || JSON.stringify(d)}`);
      }
    } catch (e:any) {
      addLog('ERROR', `Delete error: ${e.message || e}`);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Production Settings & Audio</h2>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-sm">Prayer Latitude</label>
        <input className="p-2 bg-slate-800 rounded" value={settings.prayer_lat || ''} onChange={e => setSettings({...settings, prayer_lat: e.target.value})} />
        <label className="text-sm">Prayer Longitude</label>
        <input className="p-2 bg-slate-800 rounded" value={settings.prayer_lon || ''} onChange={e => setSettings({...settings, prayer_lon: e.target.value})} />
        <label className="text-sm">Calculation Method</label>
        <input className="p-2 bg-slate-800 rounded" value={settings.calc_method || ''} onChange={e => setSettings({...settings, calc_method: e.target.value})} />
        <label className="text-sm">Asr Madhab</label>
        <input className="p-2 bg-slate-800 rounded" value={settings.asr_madhab || ''} onChange={e => setSettings({...settings, asr_madhab: e.target.value})} />
      </div>
      <div className="flex gap-2">
        <button onClick={saveSettings} className="px-4 py-2 bg-emerald-600 rounded">Save Production Settings</button>
      </div>

      <div className="mt-4 border-t border-slate-800 pt-4">
        <h3 className="font-semibold">Audio Systems</h3>
        <div className="space-y-3 mt-3">
          <div className="flex items-center justify-between bg-slate-800 p-2 rounded">
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

          <div className="flex items-center justify-between bg-slate-800 p-2 rounded">
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
            <div className="mt-2 max-h-48 overflow-y-auto space-y-2">
              {discoveredZones.map(z => (
                <div key={z.id} className="flex items-center justify-between bg-slate-800 p-2 rounded">
                  <div>
                    <div className="font-medium">{z.name}</div>
                    <div className="text-xs text-slate-400">{z.isAvailable ? 'Available' : 'Offline'}</div>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" className="sr-only peer" checked={enabledZones.includes(String(z.id))} onChange={e => {
                      const id = String(z.id);
                      if (e.target.checked) setEnabledZones(prev => Array.from(new Set([...(prev||[]), id])));
                      else setEnabledZones(prev => (prev||[]).filter(x=>x!==id));
                    }} />
                    <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:bg-emerald-500 transition-colors" />
                  </label>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 border-t border-slate-800 pt-4">
        <h3 className="font-semibold">Audio Files</h3>
        <div className="space-y-2 mt-2">
          {audioFiles.map(f => (
            <div key={f.filename} className="flex items-center justify-between bg-slate-800 p-2 rounded">
              <div>
                <div className="font-medium">{f.qari_name || f.filename}</div>
                <div className="text-xs text-slate-400">{f.filename}</div>
              </div>
              <div className="flex items-center gap-2">
                <a className="text-sm text-emerald-400" href={f.url} target="_blank" rel="noreferrer">Play</a>
                <button onClick={() => handleDelete(f.filename)} className="text-sm px-2 py-1 bg-red-600 rounded">Delete</button>
              </div>
            </div>
          ))}
        </div>

        <form onSubmit={handleUpload} className="mt-4 grid grid-cols-2 gap-2 items-end">
          <div>
            <label className="text-xs text-slate-400">Audio File</label>
            <input type="file" accept="audio/*" onChange={e => setFileInput(e.target.files ? e.target.files[0] : null)} />
          </div>
          <div>
            <label className="text-xs text-slate-400">Qari Name (display)</label>
            <input className="p-2 bg-slate-800 rounded" value={qariName} onChange={e => setQariName(e.target.value)} />
            <div className="mt-2">
              <button className="px-3 py-2 bg-blue-600 rounded">Upload</button>
            </div>
          </div>
        </form>
        <div className="text-xs text-slate-400 mt-2">{uploadGuidance()}</div>
      </div>
    </div>
  );
};

export default SettingsTab;
