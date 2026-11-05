import { describe, expect, it } from 'vitest';
import {
  groupDevices,
  type SubscriptionDeviceItem,
} from '../src/components/SubscriptionDevicesPanel';

const makeDevice = (
  id: number,
  subject: string,
  deviceOs = 'iOS',
  model = 'iPhone',
): SubscriptionDeviceItem => ({
  id,
  subject,
  device_os: deviceOs,
  os_version: '17.0',
  model,
  first_seen: 1000,
  last_seen: 2000,
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
