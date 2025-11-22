import React, { useEffect, useRef } from 'react';
import { LogEntry } from '../types';
import { Terminal, Info, AlertTriangle, XCircle, CheckCircle } from 'lucide-react';

interface LogsViewerProps {
  logs: LogEntry[];
}

const LogsViewer: React.FC<LogsViewerProps> = ({ logs }) => {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const getIcon = (level: string) => {
    switch (level) {
      case 'INFO': return <Info size={14} className="text-blue-400" />;
      case 'WARN': return <AlertTriangle size={14} className="text-yellow-400" />;
      case 'ERROR': return <XCircle size={14} className="text-red-400" />;
      case 'SUCCESS': return <CheckCircle size={14} className="text-green-400" />;
      default: return <Terminal size={14} className="text-gray-400" />;
    }
  };

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden flex flex-col h-full shadow-xl">
      <div className="bg-slate-800 px-4 py-2 border-b border-slate-700 flex items-center gap-2">
        <Terminal size={16} className="text-emerald-400" />
        <h3 className="text-sm font-mono font-semibold text-slate-200">System Logs (/logs/sys.log)</h3>
      </div>
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1.5 max-h-[300px] scrollbar-hide">
        {logs.length === 0 && (
          <div className="text-slate-500 italic">No logs recorded yet...</div>
        )}
        {logs.map((log) => (
          <div key={log.id} className="flex items-start gap-2 hover:bg-slate-800/50 p-1 rounded transition-colors">
            <span className="text-slate-500 whitespace-nowrap">
              [{log.timestamp.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}]
            </span>
            <span className="mt-0.5">{getIcon(log.level)}</span>
            <span className={`${
              log.level === 'ERROR' ? 'text-red-300' : 
              log.level === 'WARN' ? 'text-yellow-200' : 
              log.level === 'SUCCESS' ? 'text-green-300' : 'text-slate-300'
            }`}>
              {log.message}
            </span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
};

export default LogsViewer;