import { describe, expect, it } from 'vitest';
import {
  groupDevices,
  sortDeviceGroups,
  getNextSort,
  type DeviceGroup,
  type SubscriptionDeviceItem,
} from '../src/components/SubscriptionDevicesPanel';

const makeDevice = (
  id: number,
  subject: string,
  deviceOs = 'iOS',
  model = 'iPhone',
  overrides: Partial<SubscriptionDeviceItem> = {},
): SubscriptionDeviceItem => ({
  id,
  subject,
  device_os: deviceOs,
  os_version: '17.0',
  model,
  first_seen: 1000,
  last_seen: 2000,
  app: 'Happ',
  ...overrides,
});

describe('groupDevices', () => {
  it('groups devices by email subject and removes the email: prefix', () => {
    const devices: SubscriptionDeviceItem[] = [
      makeDevice(1, 'email:alice@example.com', 'iOS', 'iPhone 15'),
      makeDevice(2, 'email:alice@example.com', 'Android', 'Pixel 8'),
    ];

    const groups = groupDevices(devices);

    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('email:alice@example.com');
    expect(groups[0].label).toBe('alice@example.com');
    expect(groups[0].isGroup).toBe(false);
    expect(groups[0].devices).toHaveLength(2);
    expect(groups[0].devices.map((d) => d.id)).toEqual([1, 2]);
  });

  it('groups devices by group subject, removes group: prefix and flags isGroup as true', () => {
    const devices: SubscriptionDeviceItem[] = [
      makeDevice(1, 'group:beta-testers', 'macOS', 'MacBook Pro'),
      makeDevice(2, 'group:beta-testers', 'Windows', 'PC'),
    ];

    const groups = groupDevices(devices);

    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe('group:beta-testers');
    expect(groups[0].label).toBe('beta-testers');
    expect(groups[0].isGroup).toBe(true);
    expect(groups[0].devices).toHaveLength(2);
  });

  it('handles raw subjects without prefix without crashing', () => {
    const devices: SubscriptionDeviceItem[] = [
      makeDevice(1, 'plain-user', 'Linux', 'Server'),
    ];

    const groups = groupDevices(devices);

    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('plain-user');
    expect(groups[0].isGroup).toBe(false);
  });

  it('sorts groups alphabetically by signature (label)', () => {
    const devices: SubscriptionDeviceItem[] = [
      makeDevice(1, 'email:zebra@example.com'),
      makeDevice(2, 'group:alpha-fleet'),
      makeDevice(3, 'email:beta@example.com'),
    ];

    const groups = groupDevices(devices);

    expect(groups).toHaveLength(3);
    expect(groups[0].label).toBe('alpha-fleet');
    expect(groups[0].isGroup).toBe(true);
    expect(groups[1].label).toBe('beta@example.com');
    expect(groups[1].isGroup).toBe(false);
    expect(groups[2].label).toBe('zebra@example.com');
    expect(groups[2].isGroup).toBe(false);
  });

  it('recalculates group counts upon device deletion and removes group when last device is deleted', () => {
    let devices: SubscriptionDeviceItem[] = [
      makeDevice(1, 'email:alice@example.com'),
      makeDevice(2, 'email:alice@example.com'),
      makeDevice(3, 'email:bob@example.com'),
    ];

    let groups = groupDevices(devices);
    expect(groups).toHaveLength(2);
    expect(groups[0].label).toBe('alice@example.com');
    expect(groups[0].devices).toHaveLength(2);
    expect(groups[1].label).toBe('bob@example.com');
    expect(groups[1].devices).toHaveLength(1);

    // Delete one device from alice
    devices = devices.filter((d) => d.id !== 1);
    groups = groupDevices(devices);
    expect(groups).toHaveLength(2);
    expect(groups[0].devices).toHaveLength(1);

    // Delete the only device from bob
    devices = devices.filter((d) => d.id !== 3);
    groups = groupDevices(devices);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('alice@example.com');
    expect(groups[0].devices).toHaveLength(1);

    // Delete last remaining device
    devices = devices.filter((d) => d.id !== 2);
    groups = groupDevices(devices);
    expect(groups).toHaveLength(0);
  });

  it('handles empty or non-array inputs safely', () => {
    expect(groupDevices([])).toEqual([]);
    expect(groupDevices(null as unknown as SubscriptionDeviceItem[])).toEqual([]);
    expect(groupDevices(undefined as unknown as SubscriptionDeviceItem[])).toEqual([]);
  });
});

describe('sortDeviceGroups', () => {
  const sampleGroups: DeviceGroup[] = [
    {
      key: 'email:charlie@example.com',
      label: 'charlie@example.com',
      isGroup: false,
      devices: [
        makeDevice(10, 'email:charlie@example.com', 'Windows', 'PC', {
          app: 'sing-box',
          os_version: '10.0',
          first_seen: 500,
          last_seen: 3000,
        }),
      ],
    },
    {
      key: 'email:alice@example.com',
      label: 'alice@example.com',
      isGroup: false,
      devices: [
        makeDevice(2, 'email:alice@example.com', 'iOS', 'iPad', {
          app: 'Mihomo/Clash',
          os_version: '17.4',
          first_seen: 200,
          last_seen: 1500,
        }),
        makeDevice(1, 'email:alice@example.com', 'Android', 'Pixel', {
          app: 'Happ',
          os_version: '14.0',
          first_seen: 100,
          last_seen: 2000,
        }),
      ],
    },
    {
      key: 'group:beta-fleet',
      label: 'beta-fleet',
      isGroup: true,
      devices: [
        makeDevice(3, 'group:beta-fleet', 'macOS', 'MacBook', {
          app: 'ClashMeta',
          os_version: '15.1',
          first_seen: 300,
          last_seen: 2500,
        }),
        makeDevice(4, 'group:beta-fleet', 'Linux', 'Ubuntu', {
          app: 'curl',
          os_version: '24.04',
          first_seen: 400,
          last_seen: 1200,
        }),
        makeDevice(5, 'group:beta-fleet', 'Android', 'Samsung', {
          app: 'Incy',
          os_version: '13.0',
          first_seen: 50,
          last_seen: 800,
        }),
      ],
    },
  ];

  it('is a pure function that does not mutate input groups or devices arrays', () => {
    const originalJson = JSON.stringify(sampleGroups);
    const result = sortDeviceGroups(sampleGroups, 'app', 'asc');
    expect(JSON.stringify(sampleGroups)).toBe(originalJson);
    expect(result).not.toBe(sampleGroups);
    expect(result[0].devices).not.toBe(sampleGroups[0].devices);
  });

  it('defaults to email ascending when key and direction are omitted', () => {
    const sorted = sortDeviceGroups(sampleGroups);
    expect(sorted.map((g) => g.label)).toEqual([
      'alice@example.com',
      'beta-fleet',
      'charlie@example.com',
    ]);
  });

  it('sorts groups by email in ascending and descending order', () => {
    const asc = sortDeviceGroups(sampleGroups, 'email', 'asc');
    expect(asc.map((g) => g.label)).toEqual([
      'alice@example.com',
      'beta-fleet',
      'charlie@example.com',
    ]);

    const desc = sortDeviceGroups(sampleGroups, 'email', 'desc');
    expect(desc.map((g) => g.label)).toEqual([
      'charlie@example.com',
      'beta-fleet',
      'alice@example.com',
    ]);
  });

  it('sorts groups by count (device count) and preserves stability by signature on ties', () => {
    // Counts: charlie: 1, alice: 2, beta: 3
    const asc = sortDeviceGroups(sampleGroups, 'count', 'asc');
    expect(asc.map((g) => g.label)).toEqual([
      'charlie@example.com',
      'alice@example.com',
      'beta-fleet',
    ]);

    const desc = sortDeviceGroups(sampleGroups, 'count', 'desc');
    expect(desc.map((g) => g.label)).toEqual([
      'beta-fleet',
      'alice@example.com',
      'charlie@example.com',
    ]);
  });

  it('sorts devices inside each group by selected key, and groups by first device value', () => {
    // Sort by app ascending:
    // Inside alice: 'Happ' vs 'Mihomo/Clash' -> Happ first (dev 1, then dev 2)
    // Inside beta: 'ClashMeta', 'curl', 'Incy' -> 'ClashMeta' first
    // Inside charlie: 'sing-box'
    // First device values: beta: 'ClashMeta', alice: 'Happ', charlie: 'sing-box'
    // Group order: beta, alice, charlie
    const sorted = sortDeviceGroups(sampleGroups, 'app', 'asc');
    expect(sorted.map((g) => g.label)).toEqual([
      'beta-fleet',
      'alice@example.com',
      'charlie@example.com',
    ]);

    const aliceGroup = sorted.find((g) => g.label === 'alice@example.com')!;
    expect(aliceGroup.devices.map((d) => d.app)).toEqual(['Happ', 'Mihomo/Clash']);

    const betaGroup = sorted.find((g) => g.label === 'beta-fleet')!;
    expect(betaGroup.devices.map((d) => d.app)).toEqual(['ClashMeta', 'curl', 'Incy']);
  });

  it('places empty values always at the end regardless of sort direction', () => {
    const groupsWithEmpties: DeviceGroup[] = [
      {
        key: 'g1',
        label: 'G1',
        isGroup: false,
        devices: [
          makeDevice(1, 'g1', 'iOS', 'Phone', { app: '' }),
        ],
      },
      {
        key: 'g2',
        label: 'G2',
        isGroup: false,
        devices: [
          makeDevice(2, 'g2', 'iOS', 'Phone', { app: 'BetaApp' }),
        ],
      },
      {
        key: 'g3',
        label: 'G3',
        isGroup: false,
        devices: [
          makeDevice(3, 'g3', 'iOS', 'Phone', { app: 'AlphaApp' }),
        ],
      },
      {
        key: 'g4',
        label: 'G4',
        isGroup: false,
        devices: [
          makeDevice(4, 'g4', 'iOS', 'Phone', { app: '   ' }),
        ],
      },
    ];

    // Ascending: AlphaApp, BetaApp, then empties (G1, G4 ordered by label)
    const asc = sortDeviceGroups(groupsWithEmpties, 'app', 'asc');
    expect(asc.map((g) => g.label)).toEqual(['G3', 'G2', 'G1', 'G4']);

    // Descending: BetaApp, AlphaApp, then empties (G1, G4 still at the end!)
    const desc = sortDeviceGroups(groupsWithEmpties, 'app', 'desc');
    expect(desc.map((g) => g.label)).toEqual(['G2', 'G3', 'G1', 'G4']);
  });

  it('places empty timestamps at the end regardless of direction', () => {
    const timeGroups: DeviceGroup[] = [
      {
        key: 'g1',
        label: 'G1',
        isGroup: false,
        devices: [makeDevice(1, 'g1', 'iOS', 'Phone', { last_seen: 0 })],
      },
      {
        key: 'g2',
        label: 'G2',
        isGroup: false,
        devices: [makeDevice(2, 'g2', 'iOS', 'Phone', { last_seen: 500 })],
      },
      {
        key: 'g3',
        label: 'G3',
        isGroup: false,
        devices: [makeDevice(3, 'g3', 'iOS', 'Phone', { last_seen: 1500 })],
      },
    ];

    const asc = sortDeviceGroups(timeGroups, 'last_seen', 'asc');
    expect(asc.map((g) => g.label)).toEqual(['G2', 'G3', 'G1']);

    const desc = sortDeviceGroups(timeGroups, 'last_seen', 'desc');
    expect(desc.map((g) => g.label)).toEqual(['G3', 'G2', 'G1']);
  });

  it('compares version strings using localeCompare with numeric: true', () => {
    const versionGroups: DeviceGroup[] = [
      {
        key: 'g1',
        label: 'G1',
        isGroup: false,
        devices: [makeDevice(1, 'g1', 'iOS', 'Phone', { os_version: '10.0' })],
      },
      {
        key: 'g2',
        label: 'G2',
        isGroup: false,
        devices: [makeDevice(2, 'g2', 'iOS', 'Phone', { os_version: '2.5' })],
      },
      {
        key: 'g3',
        label: 'G3',
        isGroup: false,
        devices: [makeDevice(3, 'g3', 'iOS', 'Phone', { os_version: '1.9.0' })],
      },
      {
        key: 'g4',
        label: 'G4',
        isGroup: false,
        devices: [makeDevice(4, 'g4', 'iOS', 'Phone', { os_version: '1.10.0' })],
      },
    ];

    const asc = sortDeviceGroups(versionGroups, 'version', 'asc');
    // Numeric order: 1.9.0, 1.10.0, 2.5, 10.0
    expect(asc.map((g) => g.label)).toEqual(['G3', 'G4', 'G2', 'G1']);

    const desc = sortDeviceGroups(versionGroups, 'version', 'desc');
    expect(desc.map((g) => g.label)).toEqual(['G1', 'G2', 'G4', 'G3']);
  });

  it('ensures stable sorting on tie-breaks: signature for groups, id for devices', () => {
    const tieGroups: DeviceGroup[] = [
      {
        key: 'email:bob@example.com',
        label: 'bob@example.com',
        isGroup: false,
        devices: [
          makeDevice(20, 'email:bob@example.com', 'iOS', 'Phone', { app: 'SameApp' }),
          makeDevice(10, 'email:bob@example.com', 'iOS', 'Phone', { app: 'SameApp' }),
        ],
      },
      {
        key: 'email:alice@example.com',
        label: 'alice@example.com',
        isGroup: false,
        devices: [
          makeDevice(5, 'email:alice@example.com', 'iOS', 'Phone', { app: 'SameApp' }),
        ],
      },
    ];

    const sorted = sortDeviceGroups(tieGroups, 'app', 'asc');
    // Groups have same app ('SameApp') -> tie break by label: alice, then bob
    expect(sorted.map((g) => g.label)).toEqual(['alice@example.com', 'bob@example.com']);

    // Inside bob's group: both have 'SameApp' -> tie break by id: 10, then 20
    const bob = sorted.find((g) => g.label === 'bob@example.com')!;
    expect(bob.devices.map((d) => d.id)).toEqual([10, 20]);
  });
});

describe('getNextSort', () => {
  it('toggles direction when clicking the currently active column', () => {
    expect(getNextSort('email', 'asc', 'email')).toEqual({ key: 'email', direction: 'desc' });
    expect(getNextSort('email', 'desc', 'email')).toEqual({ key: 'email', direction: 'asc' });
    expect(getNextSort('last_seen', 'desc', 'last_seen')).toEqual({
      key: 'last_seen',
      direction: 'asc',
    });
  });

  it('starts newly selected columns ascending by default', () => {
    expect(getNextSort('email', 'asc', 'app')).toEqual({ key: 'app', direction: 'asc' });
    expect(getNextSort('email', 'asc', 'os')).toEqual({ key: 'os', direction: 'asc' });
    expect(getNextSort('email', 'asc', 'version')).toEqual({ key: 'version', direction: 'asc' });
    expect(getNextSort('email', 'asc', 'model')).toEqual({ key: 'model', direction: 'asc' });
  });

  it('starts first_seen, last_seen, and count descending when newly selected', () => {
    expect(getNextSort('email', 'asc', 'first_seen')).toEqual({
      key: 'first_seen',
      direction: 'desc',
    });
    expect(getNextSort('email', 'asc', 'last_seen')).toEqual({
      key: 'last_seen',
      direction: 'desc',
    });
    expect(getNextSort('email', 'asc', 'count')).toEqual({
      key: 'count',
      direction: 'desc',
    });
  });
});
