import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  const [size, setSize] = useState({ w: 520, h: 360 });
  const bottomRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startY: number; startW: number; startH: number } | null>(null);

  useEffect(() => activityLog.subscribe(setEntries), []);

  const visible = entries
    .filter(e => LEVEL_RANK[e.level] >= LEVEL_RANK[minLevel])
    .filter(e => !filter || `${e.section} ${e.message} ${JSON.stringify(e.context ?? '')}`.toLowerCase().includes(filter.toLowerCase()));

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [visible.length, autoScroll]);

  const copy = () => navigator.clipboard.writeText(activityLog.exportText(minLevel));

  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startY: e.clientY, startW: size.w, startH: size.h };

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const dw = dragRef.current.startX - ev.clientX;
      const dh = dragRef.current.startY - ev.clientY;
      setSize({
        w: Math.max(320, dragRef.current.startW + dw),
        h: Math.max(200, dragRef.current.startH + dh),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [size]);

  if (!open) return null;

  return (
    <div style={{
      position: 'fixed', bottom: 0, right: 0,
      width: size.w, height: size.h,
      background: '#0d1117', border: '1px solid #30363d', borderRadius: '10px 0 0 0',
      boxShadow: '0 -4px 24px rgba(0,0,0,0.5)', zIndex: 9999,
      display: 'flex', flexDirection: 'column', fontFamily: 'monospace', fontSize: '0.72rem',
    }}>
      {/* Resize handle top-left corner */}
      <div
        onMouseDown={onResizeMouseDown}
        style={{
          position: 'absolute', top: 0, left: 0, width: 20, height: 20,
          cursor: 'nw-resize', zIndex: 10000, borderRadius: '10px 0 0 0',
          background: 'linear-gradient(135deg, #58a6ff 4px, transparent 4px)',
        }}
        title="Drag to resize"
      />

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
        borderBottom: '1px solid #30363d', background: '#161b22', borderRadius: '10px 0 0 0',
        flexShrink: 0, userSelect: 'none',
      }}>
        <span style={{ color: '#e6edf3', fontWeight: 700, fontSize: '0.75rem', paddingLeft: 16 }}>Activity Log</span>
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
            flex: 1, minWidth: 0, padding: '2px 7px', borderRadius: 4, border: '1px solid #30363d',
            background: '#0d1117', color: '#e6edf3', fontSize: '0.68rem', outline: 'none',
          }}
        />
        <button onClick={() => setAutoScroll(v => !v)} style={{
          padding: '1px 6px', borderRadius: 4, border: '1px solid #30363d',
          background: autoScroll ? '#1f6feb' : '#21262d', color: '#e6edf3', cursor: 'pointer', fontSize: '0.68rem',
          flexShrink: 0,
        }} title="Auto-scroll">auto</button>
        <button onClick={copy} style={{
          padding: '1px 6px', borderRadius: 4, border: '1px solid #30363d',
          background: '#21262d', color: '#e6edf3', cursor: 'pointer', fontSize: '0.68rem', flexShrink: 0,
        }} title="Copy to clipboard">copy</button>
        <button onClick={() => activityLog.clear()} style={{
          padding: '1px 6px', borderRadius: 4, border: '1px solid #30363d',
          background: '#21262d', color: '#f87171', cursor: 'pointer', fontSize: '0.68rem', flexShrink: 0,
        }} title="Clear">clr</button>
        <button onClick={onClose} style={{
          padding: '2px 9px', borderRadius: 4, border: '1px solid #f87171',
          background: '#f871711a', color: '#f87171', cursor: 'pointer', fontSize: '0.78rem',
          fontWeight: 700, flexShrink: 0,
        }} title="Close">X</button>
      </div>

      {/* Count */}
      <div style={{ padding: '2px 10px', color: '#6c757d', fontSize: '0.65rem', borderBottom: '1px solid #30363d', flexShrink: 0 }}>
        {visible.length} entries{filter ? ' (filtered)' : ''}
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
