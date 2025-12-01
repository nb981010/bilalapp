import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import SettingsTab from '../components/SettingsTab';
import TestTab from '../components/TestTab';

const SettingsPage: React.FC<{ addLog: (level:string, msg:string)=>void; refreshSchedule: ()=>void }> = ({ addLog, refreshSchedule }) => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'settings'|'testing'>('settings');

  return (
    <div className="min-h-screen max-w-7xl mx-auto mb-6">
      <div className="bg-slate-900 rounded-2xl p-6 border border-slate-800 min-h-[70vh]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="px-3 py-1 bg-slate-800 rounded">Back</button>
            <h3 className="text-lg font-semibold">Settings</h3>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setActiveTab('settings')} className={`px-3 py-1 rounded ${activeTab==='settings' ? 'bg-emerald-600' : 'bg-slate-800'}`}>General</button>
            <button onClick={() => setActiveTab('testing')} className={`px-3 py-1 rounded ${activeTab==='testing' ? 'bg-emerald-600' : 'bg-slate-800'}`}>Testing</button>
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
  );
};

export default SettingsPage;
