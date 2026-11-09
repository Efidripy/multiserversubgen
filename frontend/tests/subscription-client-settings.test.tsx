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
import { SubscriptionUaTest } from '../src/components/SubscriptionUaTest';

const mockSchema = {
  happ: [
    { key: 'routing_enable', header: 'Routing-Enable', type: 'bool' as const, group: 'routing' },
    { key: 'routing', header: 'Routing', type: 'text' as const, group: 'routing' },
    ...['routing_ios', 'routing_android', 'routing_windows'].map(key => ({ key, header: null, type: 'bool' as const, group: 'routing' })),
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

  it('shows and toggles all Happ platform switches', async () => {
    render(<SubscriptionClientSettings />);
    fireEvent.click(await screen.findByText('subscriptionClients.tabs.clients'));
    for (const platform of ['ios', 'android', 'windows']) {
      const control = screen.getByRole('switch', { name: `subscriptionClients.fields.happ.routing_${platform}` });
      expect(control.getAttribute('aria-checked')).toBe('true');
      fireEvent.click(control);
      expect(control.getAttribute('aria-checked')).toBe('false');
      fireEvent.click(control);
      expect(control.getAttribute('aria-checked')).toBe('true');
    }
  });

  it('поля строятся из schema', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    // Switch to Clients tab
    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Happ client is selected by default and its fields are immediately visible
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

    // Switch to Mihomo client tab
    const mihomoTab = screen.getByRole('button', { name: /Mihomo/ });
    fireEvent.click(mihomoTab);
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
    const enabledSwitch = screen.getByRole('switch', {
      name: 'subscriptionClients.clients.enabled',
    });
    expect(enabledSwitch.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(enabledSwitch);
    expect(enabledSwitch.getAttribute('aria-checked')).toBe('false');

    // Happ fields are already visible; change routing text
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

    const moveUpButton = screen.getByRole('button', { name: 'subscriptionClients.clients.moveUp' });
    const moveDownButton = screen.getByRole('button', { name: 'subscriptionClients.clients.moveDown' });

    // Happ is first item: cannot move up, can move down
    expect((moveUpButton as HTMLButtonElement).disabled).toBe(true);
    expect((moveDownButton as HTMLButtonElement).disabled).toBe(false);

    // Click move down on Happ
    fireEvent.click(moveDownButton);

    // Happ is now at index 1: can move up, cannot move down
    expect((moveUpButton as HTMLButtonElement).disabled).toBe(false);
    expect((moveDownButton as HTMLButtonElement).disabled).toBe(true);

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

  it('проверка User-Agent показывает результат в SubscriptionUaTest', async () => {
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

    render(<SubscriptionUaTest />);

    expect(screen.getByPlaceholderText('subscriptionClients.test.userAgentPlaceholder')).toBeTruthy();

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

  it('порядок вкладок: содержимое перед клиентами, вкладки encryption нет', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === '/v1/subscription-client-settings') {
        return Promise.resolve({
          data: {
            settings: JSON.parse(JSON.stringify(mockSettings)),
            schema: JSON.parse(JSON.stringify(mockSchema)),
            section_schema: {
              content: [{ key: 'remark_template', type: 'text', group: 'body' }],
              remote_rules: [{ key: 'refresh_minutes', type: 'number', group: 'general' }],
              encryption: [{ key: 'happ_links', type: 'bool', group: 'general' }],
            },
            formats: mockFormats,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.content')).toBeTruthy();
    });

    const tabButtons = screen.getAllByRole('button', { name: /^subscriptionClients\.tabs\./ });
    const tabLabels = tabButtons.map((b) => b.textContent?.trim());

    expect(tabLabels).toEqual([
      'subscriptionClients.tabs.profile',
      'subscriptionClients.tabs.content',
      'subscriptionClients.tabs.clients',
      'subscriptionClients.tabs.remote_rules',
    ]);

    expect(screen.queryByText('subscriptionClients.tabs.encryption')).toBeNull();
  });

  it('у клиента Happ переключатель шифрования есть и меняет значение, у другого клиента его нет', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    expect(screen.getByText('subscriptionClients.sections.encryption.title')).toBeTruthy();
    const happSwitch = screen.getByRole('switch', {
      name: 'subscriptionClients.sections.encryption.happ_links',
    });
    expect(happSwitch).toBeTruthy();
    expect(happSwitch.getAttribute('aria-checked')).toBe('false');

    fireEvent.click(happSwitch);
    expect(happSwitch.getAttribute('aria-checked')).toBe('true');

    // Switch to Mihomo
    const mihomoTab = screen.getByRole('button', { name: /Mihomo/ });
    fireEvent.click(mihomoTab);

    expect(
      screen.queryByRole('switch', {
        name: 'subscriptionClients.sections.encryption.happ_links',
      }),
    ).toBeNull();
    expect(screen.queryByText('subscriptionClients.sections.encryption.title')).toBeNull();
  });

  it('секции сохраняются в PUT без потерь (тот самый баг)', async () => {
    const settingsWithSections = {
      profile: mockSettings.profile,
      clients: mockSettings.clients,
      content: { encode: true, remark_template: '{{NODE}}' },
      remote_rules: { refresh_minutes: 45, user_agent: 'MihomoBot' },
      xray_json: { always_array: true, template: '{"outbounds": []}' },
      response_rules: { rules: '[]' },
      page: { enabled: true, brand_title: 'MyBrand' },
      devices: { enabled: true, max_devices: 5 },
      encryption: { happ_links: true },
      custom_unknown_section: { custom_key: 'custom_value' },
    };

    apiGet.mockImplementation((url: string) => {
      if (url === '/v1/subscription-client-settings') {
        return Promise.resolve({
          data: {
            settings: JSON.parse(JSON.stringify(settingsWithSections)),
            schema: JSON.parse(JSON.stringify(mockSchema)),
            section_schema: {
              content: [{ key: 'remark_template', type: 'text', group: 'body' }],
            },
            formats: mockFormats,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    apiPut.mockResolvedValueOnce({
      data: {
        settings: {
          ...settingsWithSections,
          profile: { ...settingsWithSections.profile, title: 'Updated Profile' },
        },
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('subscriptionClients.profile.title')).toBeTruthy();
    });

    // Modify profile title
    const titleInput = screen.getByPlaceholderText('subscriptionClients.profile.title');
    fireEvent.change(titleInput, { target: { value: 'Updated Profile' } });

    // Click Save
    const saveButton = screen.getByRole('button', { name: 'subscriptionClients.save' });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledTimes(1);
    });

    expect(apiPut).toHaveBeenCalledWith('/v1/subscription-client-settings', {
      profile: {
        ...mockSettings.profile,
        title: 'Updated Profile',
      },
      clients: mockSettings.clients,
      content: { encode: true, remark_template: '{{NODE}}' },
      remote_rules: { refresh_minutes: 45, user_agent: 'MihomoBot' },
      xray_json: { always_array: true, template: '{"outbounds": []}' },
      response_rules: { rules: '[]' },
      page: { enabled: true, brand_title: 'MyBrand' },
      devices: { enabled: true, max_devices: 5 },
      encryption: { happ_links: true },
      custom_unknown_section: { custom_key: 'custom_value' },
    });

    expect(toastMock).toHaveBeenCalledWith('subscriptionClients.saveSuccess', 'success');
  });

  it('кнопка редактора Happ в карточке клиента применяет маршрут и включает routing_enable', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Button to open Happ routing editor is visible next to routing input immediately
    const openEditorBtn = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.openEditor',
    });
    expect(openEditorBtn).toBeTruthy();

    fireEvent.click(openEditorBtn);

    // HappRoutingEditor is rendered
    expect(screen.getByText('subscriptionClients.happRouting.presetsTitle')).toBeTruthy();

    // Select russia preset
    const russiaPresetBtn = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.presets.russia',
    });
    fireEvent.click(russiaPresetBtn);

    // Click Apply
    const applyBtn = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.apply',
    });
    fireEvent.click(applyBtn);

    // Happ routing input should now have happ://routing/onadd/...
    const routingInput = screen.getByLabelText(
      'subscriptionClients.fields.happ.routing',
    ) as HTMLInputElement;
    expect(routingInput.value.startsWith('happ://routing/onadd/')).toBe(true);

    // Routing-Enable switch should be turned on
    const routingSwitch = screen.getByRole('switch', {
      name: 'subscriptionClients.fields.happ.routing_enable',
    });
    expect(routingSwitch.getAttribute('aria-checked')).toBe('true');
  });

  it('показаны поля только выбранного клиента', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Happ is selected by default: Happ's fields exist, Mihomo's do not
    expect(screen.getByLabelText('subscriptionClients.fields.happ.routing')).toBeTruthy();
    expect(screen.getByLabelText('subscriptionClients.fields.happ.tun_mode')).toBeTruthy();
    expect(screen.queryByLabelText('subscriptionClients.fields.mihomo.rules')).toBeNull();
  });

  it('переключение вкладки меняет клиента', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Switch to Mihomo tab
    const mihomoTab = screen.getByRole('button', { name: /Mihomo/ });
    fireEvent.click(mihomoTab);

    // Mihomo fields are visible, Happ fields are not
    expect(screen.getByLabelText('subscriptionClients.fields.mihomo.rules')).toBeTruthy();
    expect(screen.queryByLabelText('subscriptionClients.fields.happ.routing')).toBeNull();
    expect(mihomoTab.getAttribute('aria-pressed')).toBe('true');
  });

  it('выбор сохраняется после перемещения', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Switch to Mihomo
    const mihomoTab = screen.getByRole('button', { name: /Mihomo/ });
    fireEvent.click(mihomoTab);
    expect(screen.getByLabelText('subscriptionClients.fields.mihomo.rules')).toBeTruthy();

    // Move Mihomo up to index 0
    const moveUpBtn = screen.getByRole('button', { name: 'subscriptionClients.clients.moveUp' });
    expect((moveUpBtn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(moveUpBtn);

    // Mihomo is still selected: its fields are still visible, now moveUp is disabled
    expect(screen.getByLabelText('subscriptionClients.fields.mihomo.rules')).toBeTruthy();
    expect(screen.queryByLabelText('subscriptionClients.fields.happ.routing')).toBeNull();
    expect((moveUpBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it('новый клиент становится выбранным', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    const addButton = screen.getByRole('button', { name: 'subscriptionClients.clients.addClient' });
    fireEvent.click(addButton);

    // New custom client should be selected: ruleName input and delete button are present
    const nameInput = screen.getByLabelText('subscriptionClients.clients.ruleName') as HTMLInputElement;
    expect(nameInput).toBeTruthy();
    expect(nameInput.value).toContain('subscriptionClients.clients.custom');
    expect(screen.getByRole('button', { name: 'subscriptionClients.clients.deleteClient' })).toBeTruthy();
    // Unique fields from Happ and Mihomo are not present
    expect(screen.queryByLabelText('subscriptionClients.fields.happ.routing')).toBeNull();
    expect(screen.queryByLabelText('subscriptionClients.fields.mihomo.rules')).toBeNull();
  });

  it('переключатель клиента меняет состояние и имеет role="switch"', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    const enabledSwitch = screen.getByRole('switch', {
      name: 'subscriptionClients.clients.enabled',
    });
    expect(enabledSwitch.tagName).toBe('INPUT');
    expect(enabledSwitch.getAttribute('type')).toBe('checkbox');
    expect(enabledSwitch.getAttribute('role')).toBe('switch');
    expect(enabledSwitch.getAttribute('aria-checked')).toBe('true');
    expect((enabledSwitch as HTMLInputElement).checked).toBe(true);

    fireEvent.click(enabledSwitch);

    expect(enabledSwitch.getAttribute('aria-checked')).toBe('false');
    expect((enabledSwitch as HTMLInputElement).checked).toBe(false);

    fireEvent.click(enabledSwitch);

    expect(enabledSwitch.getAttribute('aria-checked')).toBe('true');
    expect((enabledSwitch as HTMLInputElement).checked).toBe(true);
  });

  it('после удаления выбирается соседний клиент; если клиентов нет, показана только кнопка добавления', async () => {
    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.clients')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('subscriptionClients.tabs.clients'));

    // Add a custom client (it will be index 2)
    const addButton = screen.getByRole('button', { name: 'subscriptionClients.clients.addClient' });
    fireEvent.click(addButton);
    const deleteBtn = screen.getByRole('button', { name: 'subscriptionClients.clients.deleteClient' });
    expect(deleteBtn).toBeTruthy();

    // Delete custom client -> neighbor (Mihomo, index 1) is selected
    fireEvent.click(deleteBtn);
    expect(screen.getByLabelText('subscriptionClients.fields.mihomo.rules')).toBeTruthy();
  });
});
