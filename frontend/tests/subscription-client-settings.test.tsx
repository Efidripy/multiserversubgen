import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => vi.fn());
const listNodesMock = vi.hoisted(() => vi.fn());

vi.mock('../src/api', () => ({
  default: {
    get: apiGet,
    post: apiPost,
    put: apiPut,
  },
}));

vi.mock('../src/api/nodes', () => ({
  listNodes: listNodesMock,
}));

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn(() => Promise.resolve('data:image/png;base64,test')) },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('../src/components/Toast', () => ({
  useToast: () => ({ toast: toastMock }),
}));

import { SubscriptionClientSettings } from '../src/components/SubscriptionClientSettings';

const mockSchema = {
  happ: [
    { key: 'routing_enable', header: 'Routing-Enable', type: 'bool' as const, group: 'routing' },
    { key: 'routing', header: 'Routing', type: 'text' as const, group: 'routing' },
    { key: 'tun_mode', header: 'Tun-Mode', type: 'enum' as const, group: 'network', options: ['system', 'gvisor'] },
  ],
  mihomo: [
    { key: 'enable_routing', header: null, type: 'bool' as const, group: 'routing' },
    { key: 'rules', header: null, type: 'lines' as const, group: 'routing' },
  ],
};

const mockSettings = {
  profile: {
    title: 'Test Profile',
    support_url: 'https://support.example.com',
    web_page_url: 'https://example.com',
    announce: 'Test announce message',
    update_interval_hours: 24,
  },
  clients: [
    {
      id: 'happ',
      name: 'Happ',
      kind: 'happ' as const,
      builtin: true,
      enabled: true,
      user_agent_regex: '\\bhapp\\b',
      format: 'base64',
      settings: {
        routing_enable: true,
        routing: 'happ://rule',
        tun_mode: 'system',
      },
      headers: [{ key: 'X-Custom-Happ', value: '1' }],
    },
    {
      id: 'mihomo',
      name: 'Mihomo',
      kind: 'mihomo' as const,
      builtin: true,
      enabled: false,
      user_agent_regex: '^clash',
      format: 'mihomo',
      settings: {
        enable_routing: false,
        rules: 'MATCH,DIRECT',
      },
      headers: [],
    },
  ],
};

const mockFormats = ['base64', 'mihomo', 'clash', 'singbox'];

describe('SubscriptionClientSettings', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    apiPut.mockReset();
    toastMock.mockReset();
    listNodesMock.mockReset();

    apiGet.mockImplementation((url: string) => {
      if (url === '/v1/subscription-client-settings') {
        return Promise.resolve({
          data: {
            settings: JSON.parse(JSON.stringify(mockSettings)),
            schema: JSON.parse(JSON.stringify(mockSchema)),
            formats: mockFormats,
          },
        });
      }
      if (url === '/v1/emails') {
        return Promise.resolve({ data: { emails: [], stats: {} } });
      }
      if (url === '/v1/subscription-groups') {
        return Promise.resolve({ data: { groups: [] } });
      }
      return Promise.resolve({ data: {} });
    });
    listNodesMock.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('поля строятся из schema', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    // Switch to Clients tab
    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Expand Happ client
    const expandButtons = screen.getAllByText('subscriptionClients.clients.expandSettings');
    fireEvent.click(expandButtons[0]);

    // Check bool field constructed from schema
    const switchControl = screen.getByRole('switch', {
      name: 'subscriptionClients.fields.happ.routing_enable',
    });
    expect(switchControl).toBeTruthy();
    expect(switchControl.getAttribute('aria-checked')).toBe('true');

    // Check text input field constructed from schema
    const textInput = screen.getByLabelText('subscriptionClients.fields.happ.routing');
    expect(textInput).toBeTruthy();
    expect((textInput as HTMLInputElement).value).toBe('happ://rule');

    // Check header text shown under fields
    expect(screen.getByText('Routing-Enable')).toBeTruthy();
    expect(screen.getByText('Routing')).toBeTruthy();
    expect(screen.getByText('Tun-Mode')).toBeTruthy();

    // Expand Mihomo client
    fireEvent.click(expandButtons[1]);
    const linesInput = screen.getByLabelText('subscriptionClients.fields.mihomo.rules');
    expect(linesInput).toBeTruthy();
    expect((linesInput as HTMLTextAreaElement).value).toBe('MATCH,DIRECT');
  });

  it('переключение и изменение отправляют полную модель в PUT', async () => {
    apiPut.mockResolvedValueOnce({
      data: {
        settings: mockSettings,
        schema: mockSchema,
        formats: mockFormats,
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    // Switch to clients tab
    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Toggle Happ client enabled switch
    const enabledSwitches = screen.getAllByRole('switch', {
      name: 'subscriptionClients.clients.enabled',
    });
    expect(enabledSwitches[0].getAttribute('aria-checked')).toBe('true');
    fireEvent.click(enabledSwitches[0]);
    expect(enabledSwitches[0].getAttribute('aria-checked')).toBe('false');

    // Expand Happ settings and change routing text
    const expandButtons = screen.getAllByText('subscriptionClients.clients.expandSettings');
    fireEvent.click(expandButtons[0]);
    const textInput = screen.getByLabelText('subscriptionClients.fields.happ.routing');
    fireEvent.change(textInput, { target: { value: 'happ://new-rule' } });

    // Click Save
    const saveButton = screen.getByRole('button', { name: 'subscriptionClients.save' });
    expect((saveButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledTimes(1);
    });

    expect(apiPut).toHaveBeenCalledWith('/v1/subscription-client-settings', {
      profile: mockSettings.profile,
      clients: [
        {
          ...mockSettings.clients[0],
          enabled: false,
          settings: {
            ...mockSettings.clients[0].settings,
            routing: 'happ://new-rule',
          },
        },
        mockSettings.clients[1],
      ],
    });

    expect(toastMock).toHaveBeenCalledWith('subscriptionClients.saveSuccess', 'success');
  });

  it('порядок меняется кнопками', async () => {
    apiPut.mockResolvedValueOnce({
      data: {
        settings: mockSettings,
        schema: mockSchema,
        formats: mockFormats,
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    const moveUpButtons = screen.getAllByRole('button', { name: 'subscriptionClients.clients.moveUp' });
    const moveDownButtons = screen.getAllByRole('button', { name: 'subscriptionClients.clients.moveDown' });

    // First item cannot move up, second cannot move down
    expect((moveUpButtons[0] as HTMLButtonElement).disabled).toBe(true);
    expect((moveDownButtons[0] as HTMLButtonElement).disabled).toBe(false);
    expect((moveUpButtons[1] as HTMLButtonElement).disabled).toBe(false);
    expect((moveDownButtons[1] as HTMLButtonElement).disabled).toBe(true);

    // Click move down on Happ
    fireEvent.click(moveDownButtons[0]);

    // Save changes
    const saveButton = screen.getByRole('button', { name: 'subscriptionClients.save' });
    expect((saveButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledTimes(1);
    });

    const putPayload = apiPut.mock.calls[0][1];
    expect(putPayload.clients[0].id).toBe('mihomo');
    expect(putPayload.clients[1].id).toBe('happ');

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith('subscriptionClients.saveSuccess', 'success');
    });
  });

  it('встроенное правило нельзя удалить, своё можно', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Both initial clients are builtin, so delete buttons must not be present
    expect(screen.queryByRole('button', { name: 'subscriptionClients.clients.deleteClient' })).toBeNull();

    // Add a custom client
    const addButton = screen.getByRole('button', { name: 'subscriptionClients.clients.addClient' });
    fireEvent.click(addButton);

    // Now a delete button should be present for the custom client
    const deleteButton = screen.getByRole('button', { name: 'subscriptionClients.clients.deleteClient' });
    expect(deleteButton).toBeTruthy();

    // Delete custom client
    fireEvent.click(deleteButton);

    // Delete button should no longer exist
    expect(screen.queryByRole('button', { name: 'subscriptionClients.clients.deleteClient' })).toBeNull();
  });

  it('422 показывает detail', async () => {
    apiPut.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: 'user_agent_regex is invalid: bad escape',
        },
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('subscriptionClients.profile.title')).toBeTruthy();
    });

    // Modify profile title
    const titleInput = screen.getByPlaceholderText('subscriptionClients.profile.title');
    fireEvent.change(titleInput, { target: { value: 'Changed Profile Title' } });

    // Save
    const saveButton = screen.getByRole('button', { name: 'subscriptionClients.save' });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith('user_agent_regex is invalid: bad escape', 'error');
    });

    expect(screen.getByText('user_agent_regex is invalid: bad escape')).toBeTruthy();
  });

  it('проверка User-Agent показывает результат', async () => {
    apiPost.mockResolvedValueOnce({
      data: {
        matched: true,
        client_id: 'happ',
        name: 'Happ',
        format: 'base64',
        headers: {
          'Routing-Enable': 'true',
          'Profile-Title': 'Test Profile',
        },
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('subscriptionClients.test.userAgentPlaceholder')).toBeTruthy();
    });

    const uaInput = screen.getByPlaceholderText('subscriptionClients.test.userAgentPlaceholder');
    fireEvent.change(uaInput, { target: { value: 'Happ/1.2.3 (Android)' } });

    const testButton = screen.getByRole('button', { name: 'subscriptionClients.test.testButton' });
    fireEvent.click(testButton);

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/v1/subscription-client-settings/test', {
        user_agent: 'Happ/1.2.3 (Android)',
      });
    });

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.test.resultTitle')).toBeTruthy();
    });

    expect(screen.getByText('Happ')).toBeTruthy();
    expect(screen.getByText('base64')).toBeTruthy();
    expect(screen.getByText('Routing-Enable:')).toBeTruthy();
    expect(screen.getByText('Profile-Title:')).toBeTruthy();
  });
});
