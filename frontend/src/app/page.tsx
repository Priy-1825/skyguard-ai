'use client';

import React, { useState } from 'react';
import { 
  Activity, 
  AlertTriangle, 
  Radio, 
  ShieldCheck, 
  Thermometer, 
  Droplets, 
  Wind 
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid
} from 'recharts';

// Seed rolling telemetry data
const initialData = [
  { time: '18:00', temp: 28.2, humidity: 62.1, pressure: 1013.0 },
  { time: '18:05', temp: 28.4, humidity: 62.4, pressure: 1013.1 },
  { time: '18:10', temp: 29.1, humidity: 64.0, pressure: 1013.0 },
  { time: '18:15', temp: 34.8, humidity: 82.3, pressure: 1012.8 }, // Simulated Anomaly Spike
  { time: '18:20', temp: 33.2, humidity: 79.1, pressure: 1012.9 },
  { time: '18:25', temp: 28.6, humidity: 63.5, pressure: 1013.2 },
  { time: '18:30', temp: 28.5, humidity: 63.1, pressure: 1013.2 },
];

export default function Dashboard() {
  const [data] = useState(initialData);

  return (
    <div className="min-h-screen p-6 flex flex-col gap-6">
      {/* Top Navigation Bar: Government Agency Identity */}
      <header className="glass-panel rounded-2xl px-6 py-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Radio className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              SkyGuard-AI
              <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                v2.1 Edge
              </span>
            </h1>
            <p className="text-xs text-slate-400">STATE DISASTER MANAGEMENT AUTHORITY / IMD OPERATIONAL HUB</p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs font-medium">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
            REGIONAL GRID: 9 NODES ACTIVE
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-800/60 border border-slate-700 text-slate-300">
            <ShieldCheck className="w-4 h-4 text-cyan-400" />
            SOURCE: LIVE DELHI ARCHIVE STREAM
          </div>
        </div>
      </header>

      {/* Main Grid: Telemetry Trends & Root-Cause Diagnostics */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1">
        {/* Left 2 Cols: Rolling Chart & Metrics */}
        <div className="lg:col-span-2 flex flex-col gap-6">
          {/* Glassmorphic Chart Tile */}
          <div className="glass-panel rounded-2xl p-6 flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-base font-semibold text-white">Regional Telemetry Trends</h2>
                <p className="text-xs text-slate-400">Rolling 30-Tick Window across Spatial Cluster</p>
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="flex items-center gap-1.5 text-cyan-400">
                  <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" /> Temperature (°C)
                </span>
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" /> Humidity (%)
                </span>
              </div>
            </div>

            {/* Dynamic Hover Graph */}
            <div className="w-full h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                  <XAxis dataKey="time" stroke="#94a3b8" fontSize={12} tickLine={false} />
                  <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: 'rgba(15, 23, 42, 0.9)', 
                      borderColor: 'rgba(255, 255, 255, 0.1)',
                      borderRadius: '0.75rem',
                      backdropFilter: 'blur(8px)',
                      color: '#f8fafc'
                    }} 
                  />
                  <Line type="monotone" dataKey="temp" stroke="#22d3ee" strokeWidth={2.5} dot={false} />
                  <Line type="monotone" dataKey="humidity" stroke="#34d399" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Quick Metrics Bar */}
          <div className="grid grid-cols-3 gap-4">
            <div className="glass-panel rounded-xl p-4 flex items-center gap-4">
              <div className="p-3 rounded-lg bg-cyan-500/10 text-cyan-400">
                <Thermometer className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Avg Temperature</p>
                <h3 className="text-xl font-bold text-white">29.8°C</h3>
              </div>
            </div>

            <div className="glass-panel rounded-xl p-4 flex items-center gap-4">
              <div className="p-3 rounded-lg bg-emerald-500/10 text-emerald-400">
                <Droplets className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Avg Humidity</p>
                <h3 className="text-xl font-bold text-white">67.3%</h3>
              </div>
            </div>

            <div className="glass-panel rounded-xl p-4 flex items-center gap-4">
              <div className="p-3 rounded-lg bg-indigo-500/10 text-indigo-400">
                <Wind className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Avg Pressure</p>
                <h3 className="text-xl font-bold text-white">1013.1 hPa</h3>
              </div>
            </div>
          </div>
        </div>

        {/* Right Col: XAI / Root-Cause Diagnostic Tile */}
        <div className="glass-panel-alert rounded-2xl p-6 flex flex-col justify-between">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between pb-3 border-b border-red-500/20">
              <span className="text-xs font-semibold text-red-400 tracking-wider flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" /> XAI ROOT-CAUSE ATTRIBUTION
              </span>
              <span className="px-2 py-0.5 text-[10px] font-bold bg-red-500/20 text-red-300 border border-red-500/30 rounded-md">
                ACTIVE FAULT
              </span>
            </div>

            <div>
              <p className="text-xs text-slate-400">FAULTING NODE</p>
              <h4 className="text-lg font-bold text-white">Node 05 (Jahangirpuri)</h4>
            </div>

            <div>
              <p className="text-xs text-slate-400">CLASSIFIED ROOT CAUSE</p>
              <h4 className="text-sm font-semibold text-red-400">Sensor Drift (Inconsistent with 8 Spatial Neighbors)</h4>
            </div>

            {/* Feature Blame Bar Chart */}
            <div className="flex flex-col gap-2 pt-2">
              <p className="text-xs font-medium text-slate-300">Feature Blame Breakdown</p>
              
              <div className="space-y-2">
                <div>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>Humidity Sensor</span>
                    <span className="text-red-400 font-semibold">82%</span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full bg-red-500 rounded-full" style={{ width: '82%' }} />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>Temperature Sensor</span>
                    <span className="text-cyan-400">14%</span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full bg-cyan-400 rounded-full" style={{ width: '14%' }} />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>Pressure Sensor</span>
                    <span className="text-indigo-400">4%</span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full bg-indigo-400 rounded-full" style={{ width: '4%' }} />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-200 mt-6">
            <span className="font-semibold block mb-1">Recommended Action:</span>
            Dispatch local maintenance to calibrate Node 05 humidity transducer. Auto-imputation applied to operational streams.
          </div>
        </div>
      </div>
    </div>
  );
}