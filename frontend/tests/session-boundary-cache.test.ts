import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { clearManagerSnapshotCaches } from '../src/services/staleCache';

const SESSION_SNAPSHOT_KEYS = [
  'sub_manager_header_summary_cache_v1',
  'sub_manager_clients_page_cache_v1',
  'sub_manager_inbounds_page_cache_v1',
  'sub_manager_traffic_stats_cache_v3',
  'sub-manager:dashboard-overview:v1:operator-a',
  'sub-manager:dashboard-overview:v1:operator-b',
] as const;

const LOCAL_SNAPSHOT_KEYS = [
  'sub_manager_node_list_cache_v1',
  'sub_manager_node_status_cache_v1',
] as const;

describe('manager snapshot cache session boundary', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it('removes persisted data snapshots from both storages', () => {
    for (const key of SESSION_SNAPSHOT_KEYS) {
      sessionStorage.setItem(key, 'snapshot');
    }
    for (const key of LOCAL_SNAPSHOT_KEYS) {
      localStorage.setItem(key, 'snapshot');
    }

    clearManagerSnapshotCaches();

    for (const key of SESSION_SNAPSHOT_KEYS) {
      expect(sessionStorage.getItem(key)).toBeNull();
    }
    for (const key of LOCAL_SNAPSHOT_KEYS) {
      expect(localStorage.getItem(key)).toBeNull();
    }
  });

  it('preserves preferences and non-snapshot browser state', () => {
    const retainedSessionKey = 'sm_nav_client_search';
    const retainedLocalKeys = [
      'sub_manager_active_tab_v1',
      'sub_manager_cm_prefs_v1',
      'sub_manager_client_filters_v1',
      'sub_manager_inbound_filters_v1',
      'sub_manager_fleet_rail_collapsed_v1',
      'i18nextLng',
    ];

    sessionStorage.setItem(retainedSessionKey, 'operator@example.test');
    for (const key of retainedLocalKeys) {
      localStorage.setItem(key, 'preference');
    }

    clearManagerSnapshotCaches();

    expect(sessionStorage.getItem(retainedSessionKey)).toBe('operator@example.test');
    for (const key of retainedLocalKeys) {
      expect(localStorage.getItem(key)).toBe('preference');
    }
  });
});
