import React from 'react';
import { SonosZone } from '../types';
import { Speaker, Wifi, WifiOff, Music, Volume2 } from 'lucide-react';

interface ZoneGridProps {
  zones: SonosZone[];
}

const ZoneGrid: React.FC<ZoneGridProps> = ({ zones }) => {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      {zones.map((zone) => (
        <div 
          key={zone.id} 
          className={`
            relative p-4 rounded-xl border transition-all duration-300
            ${zone.isAvailable 
              ? 'bg-slate-800 border-slate-600 hover:border-emerald-500/50' 
              : 'bg-slate-900/50 border-slate-800 opacity-60 grayscale'}
            ${zone.status === 'playing_azan' ? 'ring-2 ring-emerald-500 bg-emerald-900/20' : ''}
            ${zone.status === 'grouped' ? 'ring-1 ring-blue-500/50' : ''}
          `}
        >
          <div className="flex justify-between items-start mb-3">
            <div className={`p-2 rounded-full ${
              zone.status === 'playing_azan' ? 'bg-emerald-500/20 text-emerald-400' : 
              zone.status === 'playing_music' ? 'bg-blue-500/20 text-blue-400' : 
              'bg-slate-700 text-slate-400'
            }`}>
              <Speaker size={20} />
            </div>
            {zone.isAvailable ? (
              <Wifi size={14} className="text-green-500" />
            ) : (
              <WifiOff size={14} className="text-red-500" />
            )}
          </div>

          <h4 className="font-medium text-slate-200 text-sm truncate">{zone.name}</h4>
          
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className={`px-2 py-0.5 rounded-full border ${
               zone.status === 'playing_azan' ? 'bg-emerald-900 text-emerald-300 border-emerald-700' :
               zone.status === 'playing_music' ? 'bg-blue-900 text-blue-300 border-blue-700' :
               zone.status === 'grouped' ? 'bg-indigo-900 text-indigo-300 border-indigo-700' :
               'bg-slate-700 text-slate-400 border-slate-600'
            }`}>
              {zone.status.replace('_', ' ').toUpperCase()}
            </span>
            {zone.isAvailable && (
               <div className="flex items-center gap-1 text-slate-400">
                  <Volume2 size={12} />
                  <span>{zone.volume}%</span>
               </div>
            )}
          </div>
          
          {zone.status === 'playing_music' && (
             <div className="absolute top-2 right-8 animate-pulse text-blue-400">
                <Music size={12} />
             </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default ZoneGrid;