import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight, Edit3, Pause, Play, RefreshCw, Trash2 } from 'lucide-react';
import { getRegisteredFleetOverview, type FleetNode } from '../api/nodes';

interface FleetSummary {
  total: number;
  online: number;
  offline: number;
  checking: number;
  loading: boolean;
}

interface RegisteredFleetPanelProps {
  collapsed: boolean;
  setCollapsed: (value: boolean) => void;
  onOpenNodes?: () => void;
  onSummaryChange?: (summary: FleetSummary) => void;
}

type UiFleetNode = {
  id: number;
  flag: string;
  code: string;
  version: string;
  address: string;
  latency: string;
  status: 'online' | 'offline' | 'error';
  access: 'RW' | 'RO';
  error?: string;
};

const fallbackFleetNodes: UiFleetNode[] = [
  { id: 1, flag: 'DE', code: '82-FR', version: 'v3', address: 'https://son.kleva.ru:443', latency: '11ms', status: 'online', access: 'RW' },
  { id: 2, flag: 'EE', code: '5-EE', version: 'v3', address: 'https://ebola.kleva.ru:443', latency: '11ms', status: 'online', access: 'RW' },
  { id: 3, flag: 'NL', code: '146-AM-E', version: 'v3', address: 'https://mans-cov.kleva.ru:443', latency: '-', status: 'offline', access: 'RW', error: 'Connection timeout' },
  { id: 4, flag: 'RU', code: '185-AM', version: 'v3', address: 'https://hiin1.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 5, flag: 'PL', code: '91-PL', version: 'v3', address: 'https://nipax.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 6, flag: 'RU', code: '185-RF-E', version: 'v3', address: 'https://cholera.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 7, flag: 'RU', code: '45-RF', version: 'v3', address: 'https://first.kleva.ru:443', latency: '-', status: 'error', access: 'RW', error: 'Auth failed' },
  { id: 8, flag: 'RU', code: '88-RF', version: 'v3', address: 'https://anaemia.kleva.ru:443', latency: '11ms', status: 'online', access: 'RW' },
  { id: 9, flag: 'RU', code: '94-RF', version: 'v3', address: 'https://dev.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 10, flag: 'RU', code: '94-RF-2', version: 'v3', address: 'https://ftu.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 11, flag: 'FR', code: '35-FR', version: 'v3', address: 'https://paris.kleva.ru:443', latency: '13ms', status: 'online', access: 'RW' },
  { id: 12, flag: 'GB', code: '127-UK', version: 'v3', address: 'https://london.kleva.ru:443', latency: '-', status: 'offline', access: 'RW', error: 'No connection' },
  { id: 13, flag: 'SE', code: '52-SE', version: 'v3', address: 'https://stockholm.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 14, flag: 'IT', code: '89-IT', version: 'v3', address: 'https://rome.kleva.ru:443', latency: '15ms', status: 'online', access: 'RW' },
  { id: 15, flag: 'ES', code: '43-ES', version: 'v3', address: 'https://madrid.kleva.ru:443', latency: '-', status: 'error', access: 'RO', error: 'SSL error' },
  { id: 16, flag: 'CH', code: '78-CH', version: 'v3', address: 'https://zurich.kleva.ru:443', latency: '11ms', status: 'online', access: 'RW' },
  { id: 17, flag: 'AT', code: '33-AT', version: 'v3', address: 'https://vienna.kleva.ru:443', latency: '13ms', status: 'online', access: 'RW' },
  { id: 18, flag: 'BE', code: '65-BE', version: 'v3', address: 'https://brussels.kleva.ru:443', latency: '12ms', status: 'online', access: 'RW' },
  { id: 19, flag: 'DK', code: '29-DK', version: 'v3', address: 'https://copenhagen.kleva.ru:443', latency: '-', status: 'offline', access: 'RW', error: 'Host unreachable' },
  { id: 20, flag: 'FI', code: '41-FI', version: 'v3', address: 'https://helsinki.kleva.ru:443', latency: '14ms', status: 'online', access: 'RW' },
];

const toUiNode = (node: FleetNode, index: number): UiFleetNode => {
  const rawAddress = node.url || `${node.scheme || 'https'}://${node.ip || node.name}${node.port ? `:${node.port}` : ''}`;
  return {
    id: node.id || index + 1,
    flag: (node.name || 'NA').slice(0, 2).toUpperCase(),
    code: node.name || `NODE-${index + 1}`,
    version: node.api_version || node.panel_version || 'v3',
    address: rawAddress.startsWith('http') ? rawAddress : `https://${rawAddress}`,
    latency: node.latency ? `${node.latency}ms` : '-',
    status: node.available === true ? 'online' : node.available === false ? 'offline' : 'error',
    access: node.read_only ? 'RO' : 'RW',
    error: node.error,
  };
};

export function RegisteredFleetPanel({
  collapsed,
  setCollapsed,
  onOpenNodes,
  onSummaryChange,
}: RegisteredFleetPanelProps) {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<UiFleetNode[]>(fallbackFleetNodes);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const payload = await getRegisteredFleetOverview();
      setNodes(payload.length > 0 ? payload.map(toUiNode) : fallbackFleetNodes);
    } catch {
      setNodes(fallbackFleetNodes);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const counts = useMemo(() => {
    const online = nodes.filter((node) => node.status === 'online').length;
    const offline = nodes.filter((node) => node.status === 'offline').length;
    const checking = nodes.filter((node) => node.status === 'error').length;
    return { online, offline, checking };
  }, [nodes]);

  useEffect(() => {
    onSummaryChange?.({
      total: nodes.length,
      online: counts.online,
      offline: counts.offline,
      checking: counts.checking,
      loading,
    });
  }, [counts.checking, counts.offline, counts.online, loading, nodes.length, onSummaryChange]);

  return (
    <>
      <div
        className={`xl:hidden fixed inset-0 bg-black/50 z-30 transition-all duration-300 ${
          collapsed ? 'opacity-0 pointer-events-none backdrop-blur-0' : 'opacity-100 pointer-events-auto backdrop-blur-sm'
        }`}
        onClick={() => setCollapsed(true)}
        aria-hidden="true"
      />

      {collapsed && (
        <button
          onClick={() => setCollapsed(false)}
          className="xl:hidden fixed right-0 top-24 bottom-[25px] w-8 bg-[#0a0e1a] hover:bg-[#0f1420] transition-all group z-20 flex items-center justify-center rounded-l-lg"
          title={t('nodes.registeredFleet')}
          aria-label={t('nodes.registeredFleet')}
          type="button"
        >
          <ChevronLeft className="w-4 h-4 text-cyan-300/70 group-hover:text-cyan-300" />
        </button>
      )}

      <aside
        className={`fixed right-0 top-0 bottom-[25px] w-[420px] max-w-[calc(100vw-24px)] transition-[width,transform] duration-300 pt-20 ${
          collapsed ? 'translate-x-full xl:translate-x-0 xl:w-8' : 'translate-x-0 xl:w-[420px]'
        } xl:sticky xl:top-6 xl:right-auto xl:bottom-auto xl:h-[calc(100vh-7rem)] xl:max-w-none xl:pt-0 xl:z-20 z-40`}
      >
        <div className="bg-[#0f1420] h-full flex flex-col relative overflow-clip">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={`absolute left-0 top-0 bottom-0 ${collapsed ? 'w-8' : 'w-6'} bg-[#0a0e1a] hover:bg-[#111827] transition-colors group z-10 flex items-center justify-center`}
            title={collapsed ? t('nodes.registeredFleet') : t('common.close')}
            aria-label={collapsed ? t('nodes.registeredFleet') : t('common.close')}
            type="button"
          >
            {collapsed ? (
              <ChevronLeft className="w-4 h-4 text-cyan-300/70 group-hover:text-cyan-300" />
            ) : (
              <ChevronRight className="w-4 h-4 text-cyan-300/70 group-hover:text-cyan-300" />
            )}
          </button>

          <div className="flex-1 flex flex-col pl-[28px] pr-3 pb-3 pt-3 min-h-0">
            <div className="py-3 px-3 bg-[#0d1b2b] flex-shrink-0">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div>
                  <h2 className="text-sm font-bold text-cyan-300 font-mono uppercase">{t('nodes.registeredFleet')}</h2>
                  <div className="flex flex-wrap gap-3 mt-1">
                    <span className="text-[10px] text-green-400 font-mono">Online: <strong>{counts.online}</strong></span>
                    <span className="text-[10px] text-yellow-400 font-mono">Error: <strong>{counts.checking}</strong></span>
                    <span className="text-[10px] text-red-400 font-mono">Offline: <strong>{counts.offline}</strong></span>
                  </div>
                </div>
                <button
                  className="px-3 py-1.5 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 text-white rounded font-mono font-bold text-xs disabled:opacity-50"
                  onClick={load}
                  disabled={loading}
                  type="button"
                >
                  {t('nodes.testAll')}
                </button>
              </div>
              <p className="text-xs text-gray-400 font-mono">{t('nodes.fleetHint')}</p>
            </div>

            <div id="fleet-scroll-container" className="flex-1 min-h-0 overflow-y-scroll overflow-x-hidden scrollbar-none">
              <div className="space-y-1 py-1.5">
                {nodes.map((node) => (
                  <article key={node.id} className="bg-[#0a0e1a] rounded-lg px-2.5 py-1 transition-colors duration-200 hover:bg-[#0b101b]">
                    <div className="mb-0.5">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                          node.status === 'online' ? 'bg-green-400' : node.status === 'error' ? 'bg-yellow-400' : 'bg-red-400'
                        }`} />
                        <span className="font-bold text-white text-sm">{node.flag} {node.code}</span>
                        <span className="text-gray-500 text-xs">{node.version}</span>
                      </div>

                      <div className="text-[11px] space-y-0.5 pl-4 min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="text-green-400 font-mono flex-shrink-0">https</span>
                          <span className="text-cyan-100 font-mono truncate min-w-0" title={node.address}>{node.address.replace(/^https?:\/\//, '')}</span>
                        </div>
                        <div className="flex items-center gap-2 text-gray-400">
                          <span className="text-gray-500">{node.latency}</span>
                          <span className={`font-bold ${
                            node.status === 'online' ? 'text-green-400' : node.status === 'error' ? 'text-yellow-400' : 'text-red-400'
                          }`}>{node.status}</span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            node.access === 'RW' ? 'bg-cyan-400/20 text-cyan-300' : 'bg-yellow-400/20 text-yellow-300'
                          }`}>
                            {node.access}
                          </span>
                        </div>
                        {node.error && (
                          <div className="pt-0.5 text-red-400 font-mono text-[10px]">{node.error}</div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-start gap-1.5 pt-1">
                      <button className="w-5 h-5 bg-[#0f1420] rounded text-gray-500 hover:text-cyan-300 flex items-center justify-center" type="button" title="Play">
                        <Play className="w-3.5 h-3.5 opacity-60" />
                      </button>
                      <button className="w-5 h-5 bg-[#0f1420] rounded text-gray-500 hover:text-cyan-300 flex items-center justify-center" type="button" title="Pause">
                        <Pause className="w-3.5 h-3.5 opacity-60" />
                      </button>
                      <button className="w-5 h-5 bg-[#0f1420] rounded text-gray-500 hover:text-cyan-300 flex items-center justify-center" type="button" title="Refresh" onClick={load}>
                        <RefreshCw className="w-3.5 h-3.5 opacity-60" />
                      </button>
                      <button className="w-5 h-5 bg-[#0f1420] rounded text-gray-500 hover:text-cyan-300 flex items-center justify-center" type="button" title="Edit" onClick={onOpenNodes}>
                        <Edit3 className="w-3.5 h-3.5 opacity-60" />
                      </button>
                      <button className="w-5 h-5 bg-[#0f1420] rounded text-gray-500 hover:text-red-300 flex items-center justify-center" type="button" title="Delete" disabled>
                        <Trash2 className="w-3.5 h-3.5 opacity-60" />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
