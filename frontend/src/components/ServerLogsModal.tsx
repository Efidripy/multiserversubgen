import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw, X } from 'lucide-react';
import { getNodeLogs, type NodeLogKind } from '../api/serverOps';

type ServerLogLevel = 'debug' | 'info' | 'notice' | 'warning' | 'err';

const LOG_LEVELS: ServerLogLevel[] = ['debug', 'info', 'notice', 'warning', 'err'];
const REFRESH_INTERVALS = [5, 10, 30] as const;

interface ServerLogsModalProps {
  open: boolean;
  nodeId: number;
  nodeName: string;
  kind: NodeLogKind;
  onClose: () => void;
}

export function ServerLogsModal({ open, nodeId, nodeName, kind, onClose }: ServerLogsModalProps) {
  const { t } = useTranslation();
  const failedText = t('common.failed');
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const requestRef = useRef(0);
  const inFlightRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const [level, setLevel] = useState<ServerLogLevel>('info');
  // Undefined on first load keeps the legacy app-log -> journal fallback;
  // once the operator touches the checkbox, the selected source is explicit.
  const [syslog, setSyslog] = useState<boolean | undefined>(undefined);
  const [autoUpdate, setAutoUpdate] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<number>(5);
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  onCloseRef.current = onClose;

  const loadLogs = useCallback(async (silent = false) => {
    if (silent && inFlightRef.current > 0) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    inFlightRef.current += 1;
    abortRef.current = controller;
    const requestId = ++requestRef.current;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const options: { count: number; level?: string; syslog?: boolean } = {
        count: 120,
      };
      if (kind === 'panel') {
        options.level = level;
        if (syslog !== undefined) options.syslog = syslog;
      }
      const nextLogs = await getNodeLogs(nodeId, kind, { ...options, signal: controller.signal });
      if (requestId !== requestRef.current || controller.signal.aborted) return;
      setLogs(nextLogs.slice(-120));
      setLastUpdated(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    } catch (cause: any) {
      if (requestId !== requestRef.current || controller.signal.aborted) return;
      setError(String(cause?.response?.data?.detail || cause?.message || failedText));
      setLogs([]);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
      if (abortRef.current === controller) abortRef.current = null;
      inFlightRef.current = Math.max(0, inFlightRef.current - 1);
    }
  }, [failedText, kind, level, nodeId, syslog]);

  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    void loadLogs();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      requestRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [loadLogs, open]);

  useEffect(() => {
    if (!open || !autoUpdate) return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void loadLogs(true);
    }, refreshInterval * 1000);
    return () => window.clearInterval(timer);
  }, [autoUpdate, loadLogs, open, refreshInterval]);

  if (!open) return null;

  const title = t(kind === 'xray' ? 'serverStatus.xrayLogsTitle' : 'serverStatus.serverLogsTitle', { node: nodeName });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="server-logs-title"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="flex h-[min(86vh,760px)] max-h-[min(86vh,760px)] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-cyan-400/25 bg-[#0b111d] shadow-2xl">
        <div className="flex flex-wrap items-center gap-2 border-b border-cyan-500/20 bg-cyan-500/5 px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 id="server-logs-title" className="truncate font-mono text-sm font-medium text-cyan-200">{title}</h2>
            {kind === 'xray' && <p className="mt-1 font-mono text-[10px] text-gray-500">{t('serverStatus.logsViewerXrayMode')}</p>}
          </div>
          {kind === 'panel' && (
            <>
              <label className="flex items-center gap-1.5 font-mono text-[10px] text-gray-400">
                <span>{t('serverStatus.logsViewerLevel')}</span>
                <select
                  aria-label={t('serverStatus.logsViewerLevel')}
                  className="h-7 rounded border border-cyan-500/25 bg-[#080d16] px-2 text-cyan-100"
                  value={level}
                  onChange={(event) => setLevel(event.target.value as ServerLogLevel)}
                >
                  {LOG_LEVELS.map((item) => <option key={item} value={item}>{item === 'err' ? t('serverStatus.logsViewerError') : item}</option>)}
                </select>
              </label>
              <label className="flex h-7 items-center gap-1.5 rounded border border-cyan-500/20 px-2 font-mono text-[10px] text-gray-400">
                <input
                  aria-label={t('serverStatus.logsViewerSyslog')}
                  type="checkbox"
                  checked={syslog === true}
                  onChange={(event) => setSyslog(event.target.checked)}
                />
                {t('serverStatus.logsViewerSyslog')}
              </label>
            </>
          )}
          <label className="flex h-7 items-center gap-1.5 rounded border border-cyan-500/20 px-2 font-mono text-[10px] text-gray-400">
            <input
              aria-label={t('serverStatus.logsViewerAutoUpdate')}
              type="checkbox"
              checked={autoUpdate}
              onChange={(event) => setAutoUpdate(event.target.checked)}
            />
            {t('serverStatus.logsViewerAutoUpdate')}
          </label>
          {autoUpdate && (
            <select
              aria-label={t('serverStatus.logsViewerInterval')}
              className="h-7 rounded border border-cyan-500/25 bg-[#080d16] px-2 font-mono text-[10px] text-cyan-100"
              value={refreshInterval}
              onChange={(event) => setRefreshInterval(Number(event.target.value))}
            >
              {REFRESH_INTERVALS.map((seconds) => <option key={seconds} value={seconds}>{seconds}s</option>)}
            </select>
          )}
          <button
            type="button"
            aria-label={t('serverStatus.logsViewerRefresh')}
            title={t('serverStatus.logsViewerRefresh')}
            className="flex h-7 w-7 items-center justify-center rounded border border-cyan-500/25 text-gray-400 hover:text-cyan-200 disabled:opacity-50"
            onClick={() => void loadLogs()}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            ref={closeRef}
            type="button"
            aria-label={t('serverStatus.logsViewerClose')}
            title={t('serverStatus.logsViewerClose')}
            className="flex h-7 w-7 items-center justify-center rounded border border-cyan-500/25 text-gray-400 hover:text-red-300"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col p-3">
          <div className="mb-2 flex min-h-5 items-center justify-between gap-3 font-mono text-[10px] text-gray-500">
            <span>{loading ? t('serverStatus.logsViewerLoading') : error || `${logs.length} ${t('serverStatus.logsViewerEntries')}`}</span>
            {lastUpdated && <span>{t('serverStatus.logsViewerLastUpdated', { time: lastUpdated })}</span>}
          </div>
          <pre role="log" aria-live="polite" className="min-h-[280px] flex-1 overflow-auto rounded-lg border border-cyan-500/15 bg-[#060a11] p-3 font-mono text-[11px] leading-5 text-gray-300 whitespace-pre-wrap break-words">
            {error ? error : logs.length > 0 ? logs.join('\n') : loading ? '' : t('serverStatus.logsViewerNoEntries')}
          </pre>
        </div>
      </div>
    </div>
  );
}
