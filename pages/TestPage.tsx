import React from 'react';
import { useNavigate } from 'react-router-dom';
import TestTab from '../components/TestTab';

const TestPage: React.FC<{ addLog: (level:string, msg:string)=>void }> = ({ addLog }) => {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen max-w-7xl mx-auto mb-6">
      <div className="bg-slate-900 rounded-2xl p-6 border border-slate-800 min-h-[70vh]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="px-3 py-1 bg-slate-800 rounded">Back</button>
            <h3 className="text-lg font-semibold">Test</h3>
          </div>
        </div>
        <TestTab addLog={addLog} />
      </div>
    </div>
  );
};

export default TestPage;
