import React, { useEffect, useState } from 'react';

const SettingsTab: React.FC<{ addLog: (level:string, msg:string)=>void; refreshSchedule: ()=>void }> = ({ addLog, refreshSchedule }) => {
  const [settings, setSettings] = useState<any>({});
  const [enabledAudioSystems, setEnabledAudioSystems] = useState<string[]>([]);
  const [audioFiles, setAudioFiles] = useState<any[]>([]);
  const [fileInput, setFileInput] = useState<File | null>(null);
  const [qariName, setQariName] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/settings');
        if (!res.ok) return;
        const data = await res.json();
        setSettings(data);
        if (data && data.enabled_audio_systems) {
          setEnabledAudioSystems(data.enabled_audio_systems);
        }
      } catch (e) {
        // ignore
      }
      fetchAudioList();
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
      const payload = Object.assign({}, settings, { enabled_audio_systems: enabledAudioSystems });
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

      <div className="mt-4">
        <div className="text-sm font-medium text-slate-300 mb-2">Enabled Audio Systems</div>
        {(['onboard','sonos','toa'] as const).map(sys => (
          <label key={sys} className="flex items-center space-x-2">
            <input
              type="checkbox"
              checked={enabledAudioSystems.includes(sys)}
              onChange={() => {
                setEnabledAudioSystems(prev => {
                  if (prev.includes(sys)) return prev.filter(x => x !== sys);
                  return [...prev, sys];
                });
              }}
            />
            <span className="capitalize text-sm">{sys}</span>
          </label>
        ))}
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
