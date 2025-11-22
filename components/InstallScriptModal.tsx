import React from 'react';
import { X, Copy, Download } from 'lucide-react';
import { INSTALL_SCRIPT } from '../constants';

interface InstallScriptModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const InstallScriptModal: React.FC<InstallScriptModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-3xl flex flex-col max-h-[80vh]">
        <div className="flex justify-between items-center p-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">Installation Script (install.sh)</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X size={20} />
          </button>
        </div>
        
        <div className="p-4 bg-black/50 overflow-auto flex-1">
          <pre className="text-xs sm:text-sm font-mono text-green-400 whitespace-pre-wrap">
            {INSTALL_SCRIPT}
          </pre>
        </div>

        <div className="p-4 border-t border-slate-700 bg-slate-800 flex justify-end gap-3">
          <button 
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm font-medium transition-colors"
            onClick={() => {
                navigator.clipboard.writeText(INSTALL_SCRIPT);
                alert('Copied to clipboard!');
            }}
          >
            <Copy size={16} /> Copy
          </button>
          <button 
             className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium text-white transition-colors"
             onClick={() => {
                 const blob = new Blob([INSTALL_SCRIPT], { type: 'text/plain' });
                 const url = URL.createObjectURL(blob);
                 const a = document.createElement('a');
                 a.href = url;
                 a.download = 'install.sh';
                 a.click();
             }}
          >
            <Download size={16} /> Download
          </button>
        </div>
      </div>
    </div>
  );
};

export default InstallScriptModal;