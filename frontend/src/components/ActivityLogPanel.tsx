import React, { useEffect, useRef, useState } from 'react';
import { activityLog, LogEntry, LogLevel, LEVEL_RANK } from '../services/activityLog';

const LEVELS: LogLevel[] = ['debug', 'info', 'warning', 'error'];

const LEVEL_COLOR: Record<LogLevel, string> = {
  debug:   '#6c757d',
  info:    '#6ea8fe',
  warning: '#ffc107',
  error:   '#f87171',
};

const LEVEL_BG: Record<LogLevel, string> = {
  debug:   'rgba(108,117,125,0.12)',
  info:    'rgba(110,168,254,0.10)',
  warning: 'rgba(255,193,7,0.12)',
  error:   'rgba(248,113,113,0.14)',
};

interface Props {
  open: boolean;
  onClose: () => void;
}

export const ActivityLogPanel: React.FC<Props> = ({ open, onClose }) => {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [minLevel, setMinLevel] = useState<LogLevel>('info');
  const [autoScroll, setAutoScroll] = useState(true);
  const [filter, setFilter] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => activityLog.subscribe(setEntries), []);

  const visible = entries
    .filter(e => LEVEL_RANK[e.level] >= LEVEL_RANK[minLevel])
    .filter(e => !filter || `${e.section} ${e.message} ${JSON.stringify(e.context ?? '')}`.toLowerCase().includes(filter.toLowerCase()));

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [visible.length, autoScroll]);

  const copy = () => {
    navigator.clipboard.writeText(activityLog.exportText(minLevel));
  };

  if (!open) return null;

  return (
    <div style={{
      position: 'fixed', bottom: 0, right: 0, width: 520, height: 360,
      background: '#0d1117', border: '1px solid #30363d', borderRadius: '10px 0 0 0',
      boxShadow: '0 -4px 24px rgba(0,0,0,0.5)', zIndex: 9999,
      display: 'flex', flexDirection: 'column', fontFamily: 'monospace', fontSize: '0.72rem',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
        borderBottom: '1px solid #30363d', background: '#161b22', borderRadius: '10px 0 0 0',
        flexShrink: 0,
      }}>
        <span style={{ color: '#e6edf3', fontWeight: 700, fontSize: '0.75rem' }}>Activity Log v2</span>
        <div style={{ display: 'flex', gap: 3, marginLeft: 4 }}>
          {LEVELS.map(l => (
            <button key={l} onClick={() => setMinLevel(l)} style={{
              padding: '1px 7px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: '0.68rem', fontWeight: 600,
              background: minLevel === l ? LEVEL_COLOR[l] : '#21262d',
              color: minLevel === l ? '#0d1117' : LEVEL_COLOR[l],
            }}>{l}</button>
          ))}
        </div>
        <input
          value={filter} onChange={e => setFilter(e.target.value)}
          placeholder="filter..." style={{
            flex: 1, padding: '2px 7px', borderRadius: 4, border: '1px solid #30363d',
            background: '#0d1117', color: '#e6edf3', fontSize: '0.68rem', outline: 'none',
          }}
        />
        <button onClick={() => setAutoScroll(v => !v)} style={{
          padding: '1px 6px', borderRadius: 4, border: '1px solid #30363d',
          background: autoScroll ? '#1f6feb' : '#21262d', color: '#e6edf3', cursor: 'pointer', fontSize: '0.68rem',
          flexShrink: 0,
        }} title="Auto-scroll">v</button>
        <button onClick={copy} style={{
          padding: '1px 6px', borderRadius: 4, border: '1px solid #30363d',
          background: '#21262d', color: '#e6edf3', cursor: 'pointer', fontSize: '0.68rem', flexShrink: 0,
        }} title="Copy to clipboard">CP</button>
        <button onClick={() => activityLog.clear()} style={{
          padding: '1px 6px', borderRadius: 4, border: '1px solid #30363d',
          background: '#21262d', color: '#f87171', cursor: 'pointer', fontSize: '0.68rem', flexShrink: 0,
        }} title="Clear">X</button>
        <button onClick={onClose} style={{
          padding: '1px 6px', borderRadius: 4, border: 'none',
          background: 'transparent', color: '#6c757d', cursor: 'pointer', fontSize: '0.85rem', flexShrink: 0,
        }}>X</button>
      </div>

      {/* Count */}
      <div style={{ padding: '2px 10px', color: '#6c757d', fontSize: '0.65rem', borderBottom: '1px solid #30363d', flexShrink: 0 }}>
        {visible.length} entries {filter && `(filtered)`}
      </div>

      {/* Entries */}
      <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {visible.map(e => {
          const time = new Date(e.ts).toLocaleTimeString('ru', { hour12: false });
          return (
            <div key={e.id} style={{
              display: 'flex', gap: 6, alignItems: 'baseline',
              padding: '2px 10px', borderLeft: `2px solid ${LEVEL_COLOR[e.level]}`,
              background: LEVEL_BG[e.level], marginBottom: 1,
            }}>
              <span style={{ color: '#6c757d', minWidth: 62, flexShrink: 0 }}>{time}</span>
              <span style={{ color: LEVEL_COLOR[e.level], minWidth: 52, flexShrink: 0, fontWeight: 700 }}>
                {e.level.toUpperCase()}
              </span>
              <span style={{ color: '#8b949e', minWidth: 90, flexShrink: 0 }}>[{e.section}]</span>
              <span style={{ color: '#e6edf3', wordBreak: 'break-word' }}>
                {e.message}
                {e.context && (
                  <span style={{ color: '#6c757d', marginLeft: 5 }}>
                    {JSON.stringify(e.context)}
                  </span>
                )}
              </span>
            </div>
          );
        })}
        {visible.length === 0 && (
          <div style={{ padding: '16px', color: '#6c757d', textAlign: 'center' }}>No entries</div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
