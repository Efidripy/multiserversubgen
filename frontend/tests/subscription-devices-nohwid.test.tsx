import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiDelete = vi.hoisted(() => vi.fn());
vi.mock('../src/api', () => ({ default: { get: apiGet, delete: apiDelete } }));
vi.mock('../src/components/Toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { SubscriptionDevicesPanel } from '../src/components/SubscriptionDevicesPanel';

afterEach(cleanup);

it('shows and deletes a device without HWID and displays empty metadata', async () => {
  apiGet.mockResolvedValue({ data: { max_devices: 1, devices: [{
    id: 12, subject: 'email:alice', device_os: '', os_version: '', model: '',
    first_seen: 1, last_seen: 2, user_agent: '', has_hwid: false,
  }] } });
  apiDelete.mockResolvedValue({});
  render(<SubscriptionDevicesPanel />);
  const expand = await screen.findAllByLabelText('subscriptionClients.devices.expandGroup');
  fireEvent.click(expand[0]);
  const badge = screen.getAllByText('subscriptionClients.devices.noHwid')[0];
  const card = badge.closest('article');
  expect(card).not.toBeNull();
  expect(within(card as HTMLElement).getAllByText('—')).toHaveLength(4);
  fireEvent.click(within(card as HTMLElement).getByLabelText('subscriptionClients.devices.delete'));
  expect(apiDelete).toHaveBeenCalledWith('/v1/subscription-client-settings/devices/12');
});

