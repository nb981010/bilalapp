import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const TestPage: React.FC<{ addLog: (level:string, msg:string)=>void }> = ({ addLog }) => {
  const navigate = useNavigate();
  const [settings, setSettings] = useState<any>({});
  const [audioFiles, setAudioFiles] = useState<any[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [dateOpt, setDateOpt] = useState<'today'|'tomorrow'>('today');
  const [jobs, setJobs] = useState<any[]>([]);
  const [runMode, setRunMode] = useState<'dry'|'production'>('dry');
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/test/settings');
        if (res.ok) setSettings(await res.json());
      } catch (e) {}
      fetchAudioList();
    })();
  }, []);

  const fetchAudioList = async () => {
    try {
      const res = await fetch('/api/audio/list');
      if (!res.ok) return;
      const d = await res.json();
      if (d && d.files) setAudioFiles(d.files);
    } catch (e) {}
  };

  const saveTestSettings = async () => {
    try {
      const res = await fetch('/api/test/settings', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(settings) });
      if (res.ok) addLog('SUCCESS','Test settings saved');
      else addLog('ERROR','Failed to save test settings');
    } catch (e:any) { addLog('ERROR', `Save failed: ${e.message || e}`); }
  };

  const computeSchedule = async () => {
    try {
      setError(null);
      setComputing(true);
      const base = dateOpt === 'today' ? new Date() : new Date(Date.now() + 24*3600*1000);
      const dateStr = base.toISOString().slice(0,10);
      const res = await fetch('/api/scheduler/compute', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ mode: 'test', date: dateStr }) });
      const d = await res.json();
      if (res.ok && d.jobs) {
        setJobs(d.jobs);
        addLog('SUCCESS', `Computed ${d.jobs.length} test jobs for ${dateStr}`);
      } else {
        const msg = d && d.message ? d.message : JSON.stringify(d);
        setError(String(msg));
        addLog('ERROR', `Compute failed: ${msg}`);
      }
    } catch (e:any) {
      setError(String(e?.message || e));
      addLog('ERROR', `Compute error: ${e.message || e}`);
    } finally {
      setComputing(false);
    }
  };

  const simulatePlay = async (whenIso?:string) => {
    try {
      const payload:any = { file: selectedFile || 'azan.mp3' };
      if (whenIso) payload.ts = whenIso;
      const res = await fetch('/api/test/play', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const d = await res.json();
      if (res.ok) addLog('SUCCESS','Simulated play appended'); else addLog('ERROR', `Simulate failed: ${d.message || JSON.stringify(d)}`);
    } catch (e:any) { addLog('ERROR', `Simulate error: ${e.message || e}`); }
  };

  const runProductionNow = async () => {
    if (!confirm('This will perform a real playback on production Sonos devices. Continue?')) return;
    try {
      const payload = { file: selectedFile || 'azan.mp3', zones: [] };
      const headers:any = { 'Content-Type': 'application/json' };
      let pass = localStorage.getItem('bilal:passcode');
      if (!pass) {
        const entered = window.prompt('Enter admin passcode for production action (will be stored in localStorage for this session):', '');
        if (!entered) { addLog('ERROR','Production action cancelled (no passcode)'); return; }
        pass = entered;
        localStorage.setItem('bilal:passcode', pass);
      }
      headers['X-BILAL-PASSCODE'] = pass;
      const res = await fetch('/api/play', { method: 'POST', headers, body: JSON.stringify(payload) });
      const d = await res.json();
      if (res.ok) addLog('SUCCESS', 'Production play triggered'); else addLog('ERROR', `Production play failed: ${d.message || JSON.stringify(d)}`);
    } catch (e:any) { addLog('ERROR', `Run error: ${e.message || e}`); }
  };

  return (
    <div className="min-h-screen max-w-7xl mx-auto mb-6">
      <div className="bg-slate-900 rounded-2xl p-6 border border-slate-800 min-h-[70vh]">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="px-3 py-1 bg-slate-800 rounded">Back</button>
            <h3 className="text-lg font-semibold">Test</h3>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-slate-800 p-4 rounded">
            <h2 className="text-xl font-semibold mb-2">Test Environment</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-sm text-slate-300">Test Location Latitude</label>
                <input className="mt-1 p-2 bg-slate-700 rounded w-full" value={settings.prayer_lat || ''} onChange={e => setSettings({...settings, prayer_lat: e.target.value})} />
              </div>
              <div>
                <label className="text-sm text-slate-300">Test Location Longitude</label>
                <input className="mt-1 p-2 bg-slate-700 rounded w-full" value={settings.prayer_lon || ''} onChange={e => setSettings({...settings, prayer_lon: e.target.value})} />
              </div>
              <div>
                <label className="text-sm text-slate-300">Calculation Method</label>
                <input className="mt-1 p-2 bg-slate-700 rounded w-full" value={settings.calc_method || ''} onChange={e => setSettings({...settings, calc_method: e.target.value})} />
              </div>
              <div>
                <label className="text-sm text-slate-300">Asr Madhab</label>
                <input className="mt-1 p-2 bg-slate-700 rounded w-full" value={settings.asr_madhab || ''} onChange={e => setSettings({...settings, asr_madhab: e.target.value})} />
              </div>
            </div>
            <div className="mt-3 flex gap-2">
              <button onClick={saveTestSettings} className="px-4 py-2 bg-emerald-600 rounded">Save Test Settings</button>
              <button onClick={() => { setSettings({}); addLog('INFO','Cleared test settings locally'); }} className="px-3 py-2 bg-slate-700 rounded">Clear</button>
            </div>
          </div>

          <div className="bg-slate-800 p-4 rounded">
            <h3 className="font-semibold mb-2">Test Controls</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-slate-400">Date</label>
                <select value={dateOpt} onChange={e => setDateOpt(e.target.value as any)} className="mt-1 p-2 bg-slate-700 rounded w-full">
                  <option value="today">Today</option>
                  <option value="tomorrow">Tomorrow</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400">Audio File</label>
                <select value={selectedFile} onChange={e => setSelectedFile(e.target.value)} className="mt-1 p-2 bg-slate-700 rounded w-full">
                  <option value="">(default) azan.mp3</option>
                  {audioFiles.map(f => <option key={f.filename} value={f.filename}>{f.qari_name || f.filename}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400">Run Type</label>
                <select value={runMode} onChange={e => setRunMode(e.target.value as any)} className="mt-1 p-2 bg-slate-700 rounded w-full">
                  <option value="dry">Dry-run (no production changes)</option>
                  <option value="production">Production (real playback)</option>
                </select>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={computeSchedule} disabled={computing} className={`px-3 py-2 ${computing ? 'bg-slate-600' : 'bg-blue-600'} rounded`}>{computing ? 'Computing...' : 'Compute Test Schedule'}</button>
              <button onClick={() => simulatePlay()} className="px-3 py-2 bg-slate-700 rounded">Simulate Play (server)</button>
              <button onClick={runProductionNow} className="px-3 py-2 bg-red-600 rounded">Run Now (Production)</button>
            </div>
            {error && <div className="mt-2 text-red-400">Error: {error}</div>}

            <div className="mt-4">
              <h4 className="font-medium">Computed Jobs</h4>
              <div className="mt-2 space-y-2">
                {jobs.length === 0 && <div className="text-sm text-slate-400">No computed jobs yet. Click "Compute Test Schedule" to generate jobs for the selected date.</div>}
                {jobs.map(j => (
                  <div key={j.id} className="bg-slate-700 p-3 rounded flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium">{(j.prayer || '').toString().toUpperCase()}</div>
                      <div className="text-xs text-slate-400">Local: {j.scheduled_local}</div>
                    </div>
                    <div className="text-xs text-slate-400">file: {j.playback_file}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TestPage;
