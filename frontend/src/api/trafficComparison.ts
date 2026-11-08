import api from './client';

export interface TrafficComparisonData {
  history_days: number;
  previous_available: boolean;
  series_current: { ts: number; value: number }[];
  series_previous: { ts: number; value: number }[];
  totals: { current: number; previous: number | null };
  top_clients: { email: string; current: number; previous: number | null; delta_pct: number | null }[];
  top_growth: TrafficComparisonData['top_clients'];
}
export async function getTrafficComparison(range: string, nodeId: string, signal: AbortSignal): Promise<TrafficComparisonData> {
  const result = await api.get('/v1/traffic/comparison', { params: { range, ...(nodeId ? { node_id: nodeId } : {}) }, signal, sessionOnlyAuth: true });
  return result.data;
}
