import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());
const apiDelete = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => vi.fn());

vi.mock('../src/api', () => ({
  default: {
    get: apiGet,
    post: apiPost,
    put: apiPut,
    delete: apiDelete,
  },
}));

vi.mock('../src/api/nodes', () => ({
  listNodes: vi.fn(() => Promise.resolve([])),
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

import {
  SubscriptionSettingsSections,
  SectionFieldSchema,
} from '../src/components/SubscriptionSettingsSections';
import {
  HappRoutingEditor,
  decodeHappRouting,
  encodeHappRouting,
  parseGlobalProxy,
} from '../src/components/HappRoutingEditor';
import { SubscriptionDevicesPanel } from '../src/components/SubscriptionDevicesPanel';
import { SubscriptionClientSettings } from '../src/components/SubscriptionClientSettings';

describe('SubscriptionSettingsSections and Client Subscriptions Stage 2', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    apiPut.mockReset();
    apiDelete.mockReset();
    toastMock.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('поля строятся из section_schema', () => {
    const mockFields: SectionFieldSchema[] = [
      { key: 'enable_feature', type: 'bool', group: 'general' },
      { key: 'count_limit', type: 'number', group: 'general' },
      { key: 'endpoint_url', type: 'url', group: 'network' },
      { key: 'custom_text', type: 'text', group: 'network' },
      { key: 'select_mode', type: 'enum', group: 'network', options: ['mode1', 'mode2'] },
      { key: 'raw_config', type: 'json', group: 'advanced' },
    ];

    const values: Record<string, any> = {
      enable_feature: true,
      count_limit: 42,
      endpoint_url: 'https://example.com/api',
      custom_text: 'hello world',
      select_mode: 'mode1',
      raw_config: '{"foo":"bar"}',
    };

    const handleChange = vi.fn();
    const handleValidityChange = vi.fn();

    render(
      <SubscriptionSettingsSections
        sectionKey="content"
        fields={mockFields}
        values={values}
        onChange={handleChange}
        onValidityChange={handleValidityChange}
      />,
    );

    // Section title
    expect(screen.getByText('subscriptionClients.sections.content.title')).toBeTruthy();

    // Bool field: role switch
    const switchEl = screen.getByRole('switch', {
      name: 'subscriptionClients.sections.content.enable_feature',
    });
    expect(switchEl).toBeTruthy();
    expect(switchEl.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(switchEl);
    expect(handleChange).toHaveBeenCalledWith('enable_feature', false);

    // Number field
    const numInput = screen.getByLabelText('subscriptionClients.sections.content.count_limit');
    expect((numInput as HTMLInputElement).value).toBe('42');
    fireEvent.change(numInput, { target: { value: '100' } });
    expect(handleChange).toHaveBeenCalledWith('count_limit', 100);

    // URL field
    const urlInput = screen.getByLabelText('subscriptionClients.sections.content.endpoint_url');
    expect((urlInput as HTMLInputElement).value).toBe('https://example.com/api');

    // Text field
    const textInput = screen.getByLabelText('subscriptionClients.sections.content.custom_text');
    expect((textInput as HTMLInputElement).value).toBe('hello world');

    // JSON field
    const jsonInput = screen.getByLabelText('subscriptionClients.sections.content.raw_config');
    expect((jsonInput as HTMLTextAreaElement).value).toBe('{"foo":"bar"}');
  });

  it('битый JSON запрещает сохранение', async () => {
    const mockSectionSchema = {
      xray_json: [
        { key: 'always_array', type: 'bool' as const, group: 'format' },
        { key: 'template', type: 'json' as const, group: 'format' },
      ],
    };

    const mockInitialSettings = {
      profile: { title: 'Test Profile', support_url: '', web_page_url: '', announce: '', update_interval_hours: null },
      clients: [],
      xray_json: {
        always_array: false,
        template: '{"outbounds": []}',
      },
    };

    apiGet.mockResolvedValueOnce({
      data: {
        settings: mockInitialSettings,
        schema: {},
        section_schema: mockSectionSchema,
        formats: ['base64'],
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.xray_json')).toBeTruthy();
    });

    // Switch to xray_json tab
    fireEvent.click(screen.getByText('subscriptionClients.tabs.xray_json'));

    const templateTextarea = screen.getByLabelText('subscriptionClients.sections.xray_json.template');
    expect((templateTextarea as HTMLTextAreaElement).value).toBe('{"outbounds": []}');

    // Save button should initially be disabled because there are no changes
    const saveButton = screen.getByRole('button', { name: 'subscriptionClients.save' });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);

    // Enter broken JSON
    fireEvent.change(templateTextarea, { target: { value: '{ broken json: true' } });

    // Error message must appear under the field
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
    });
    expect(screen.getByText('subscriptionClients.sections.fixJsonErrors')).toBeTruthy();

    // Save button must remain disabled due to invalid JSON!
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);

    // Clicking save button should not call apiPut
    fireEvent.click(saveButton);
    expect(apiPut).not.toHaveBeenCalled();

    // Fix the JSON
    fireEvent.change(templateTextarea, { target: { value: '{"outbounds": [{"tag": "direct"}]}' } });

    // Error message should disappear and save button should now be enabled
    await waitFor(() => {
      expect(screen.queryByRole('alert')).toBeNull();
    });
    expect((saveButton as HTMLButtonElement).disabled).toBe(false);

    // Now clicking save calls apiPut
    apiPut.mockResolvedValueOnce({
      data: {
        settings: {
          ...mockInitialSettings,
          xray_json: {
            always_array: false,
            template: '{"outbounds": [{"tag": "direct"}]}',
          },
        },
      },
    });

    fireEvent.click(saveButton);
    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledTimes(1);
    });
  });

  it('редактор Happ создаёт разбираемую строку happ://routing/onadd/ с кириллицей и разбирает сохранённую', () => {
    const handleApply = vi.fn();

    const { unmount } = render(
      <HappRoutingEditor routingValue="" onApply={handleApply} />,
    );

    // Fill form with Cyrillic and rules
    const nameInput = screen.getByLabelText('subscriptionClients.happRouting.name');
    fireEvent.change(nameInput, { target: { value: 'Правило маршрутизации для РФ' } });

    const directSitesInput = screen.getByLabelText('subscriptionClients.happRouting.directSites');
    fireEvent.change(directSitesInput, {
      target: { value: 'geosite:category-ru\ngeosite:private\nдомен.рф' },
    });

    const directIpInput = screen.getByLabelText('subscriptionClients.happRouting.directIp');
    fireEvent.change(directIpInput, { target: { value: 'geoip:ru\ngeoip:private' } });

    // Click Apply
    const applyButton = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.apply',
    });
    fireEvent.click(applyButton);

    expect(handleApply).toHaveBeenCalledTimes(1);
    const generatedString = handleApply.mock.calls[0][0];

    // Check string starts with happ://routing/onadd/
    expect(generatedString.startsWith('happ://routing/onadd/')).toBe(true);

    // Parse with decodeHappRouting and verify Cyrillic and contents
    const decoded = decodeHappRouting(generatedString);
    expect(decoded.error).toBeUndefined();
    expect(decoded.data).toBeDefined();
    expect(decoded.data?.Name).toBe('Правило маршрутизации для РФ');
    expect(typeof decoded.data?.GlobalProxy).toBe('string');
    expect(decoded.data?.GlobalProxy).toBe('true');
    expect(decoded.data?.DirectSites).toEqual(['geosite:category-ru', 'geosite:private', 'домен.рф']);
    expect(decoded.data?.DirectIp).toEqual(['geoip:ru', 'geoip:private']);

    unmount();

    // Now mount a new editor with that generated string and verify it populates correctly
    render(<HappRoutingEditor routingValue={generatedString} onApply={handleApply} />);

    const parsedNameInput = screen.getByLabelText(
      'subscriptionClients.happRouting.name',
    ) as HTMLInputElement;
    expect(parsedNameInput.value).toBe('Правило маршрутизации для РФ');

    const parsedDirectSites = screen.getByLabelText(
      'subscriptionClients.happRouting.directSites',
    ) as HTMLTextAreaElement;
    expect(parsedDirectSites.value).toContain('домен.рф');
    expect(parsedDirectSites.value).toContain('geosite:category-ru');
  });

  it('GlobalProxy в результате это строка; "false" разбирается как выключено', () => {
    const handleApply = vi.fn();

    // 1. Initial string with GlobalProxy: "false" (string)
    const rawConfigWithFalseString = {
      Name: 'Custom Route Off',
      GlobalProxy: 'false',
      DirectSites: ['direct.local'],
    };
    const routingStrFalse = encodeHappRouting(rawConfigWithFalseString);

    const { rerender } = render(
      <HappRoutingEditor routingValue={routingStrFalse} onApply={handleApply} />,
    );

    // Switch should be parsed as disabled/off
    const switchEl = screen.getByRole('switch', {
      name: 'subscriptionClients.happRouting.globalProxy',
    });
    expect(switchEl.getAttribute('aria-checked')).toBe('false');

    // Click Apply without toggling switch
    const applyButton = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.apply',
    });
    fireEvent.click(applyButton);

    expect(handleApply).toHaveBeenCalledTimes(1);
    const applied1 = handleApply.mock.calls[0][0];
    const decoded1 = decodeHappRouting(applied1);
    expect(typeof decoded1.data?.GlobalProxy).toBe('string');
    expect(decoded1.data?.GlobalProxy).toBe('false');

    // Toggle switch on
    fireEvent.click(switchEl);
    expect(switchEl.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(applyButton);

    expect(handleApply).toHaveBeenCalledTimes(2);
    const applied2 = handleApply.mock.calls[1][0];
    const decoded2 = decodeHappRouting(applied2);
    expect(typeof decoded2.data?.GlobalProxy).toBe('string');
    expect(decoded2.data?.GlobalProxy).toBe('true');

    // 2. Also verify boolean false is parsed as off
    const rawConfigWithFalseBool = {
      Name: 'Custom Route Bool Off',
      GlobalProxy: false,
    };
    const routingStrBoolFalse = encodeHappRouting(rawConfigWithFalseBool);
    rerender(<HappRoutingEditor routingValue={routingStrBoolFalse} onApply={handleApply} />);

    const switchElBool = screen.getByRole('switch', {
      name: 'subscriptionClients.happRouting.globalProxy',
    });
    expect(switchElBool.getAttribute('aria-checked')).toBe('false');

    // Direct parser check
    expect(parseGlobalProxy('false')).toBe(false);
    expect(parseGlobalProxy('False')).toBe(false);
    expect(parseGlobalProxy(false)).toBe(false);
    expect(parseGlobalProxy('true')).toBe(true);
    expect(parseGlobalProxy(true)).toBe(true);
  });

  it('неизвестное поле RouteOrder переживает открытие и применение; пресет его не тащит', () => {
    const handleApply = vi.fn();

    // Config with unknown fields (RouteOrder, DnsHosts, FakeDNS)
    const rawConfig = {
      Name: 'Initial Route',
      GlobalProxy: 'true',
      DirectSites: ['example.com'],
      RouteOrder: ['Direct', 'Proxy', 'Block'],
      DnsHosts: { 'test.internal': '10.0.0.1' },
      FakeDNS: true,
    };
    const initialRouting = encodeHappRouting(rawConfig);

    const { rerender } = render(
      <HappRoutingEditor routingValue={initialRouting} onApply={handleApply} />,
    );

    // Edit Name
    const nameInput = screen.getByLabelText('subscriptionClients.happRouting.name');
    expect((nameInput as HTMLInputElement).value).toBe('Initial Route');
    fireEvent.change(nameInput, { target: { value: 'Edited Route' } });

    // Click Apply
    const applyButton = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.apply',
    });
    fireEvent.click(applyButton);

    expect(handleApply).toHaveBeenCalledTimes(1);
    const applied1 = handleApply.mock.calls[0][0];
    const decoded1 = decodeHappRouting(applied1);

    // RouteOrder, DnsHosts, FakeDNS survived opening and applying!
    expect(decoded1.data?.Name).toBe('Edited Route');
    expect(decoded1.data?.RouteOrder).toEqual(['Direct', 'Proxy', 'Block']);
    expect(decoded1.data?.DnsHosts).toEqual({ 'test.internal': '10.0.0.1' });
    expect(decoded1.data?.FakeDNS).toBe(true);

    // Now re-render with the initial string and choose a preset
    rerender(<HappRoutingEditor routingValue={initialRouting} onApply={handleApply} />);

    const russiaPresetBtn = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.presets.russia',
    });
    fireEvent.click(russiaPresetBtn);

    fireEvent.click(applyButton);

    expect(handleApply).toHaveBeenCalledTimes(2);
    const applied2 = handleApply.mock.calls[1][0];
    const decoded2 = decodeHappRouting(applied2);

    // Preset starts with clean object: RouteOrder, DnsHosts, FakeDNS are NOT carried over!
    expect(decoded2.data?.Name).toBe('Bypass Russia & LAN');
    expect(decoded2.data?.RouteOrder).toBeUndefined();
    expect(decoded2.data?.DnsHosts).toBeUndefined();
    expect(decoded2.data?.FakeDNS).toBeUndefined();
    expect(decoded2.data?.DirectSites).toContain('geosite:category-ru');
  });

  it('ошибка исчезает при очистке значения или когда строка снова корректна', () => {
    const handleApply = vi.fn();
    const corruptRouting = 'happ://routing/onadd/not-a-valid-base64!';

    const { rerender } = render(
      <HappRoutingEditor routingValue={corruptRouting} onApply={handleApply} />,
    );

    // Error is shown
    expect(screen.getByText('subscriptionClients.happRouting.invalidString')).toBeTruthy();

    // Clear value to empty string -> error must disappear!
    rerender(<HappRoutingEditor routingValue="" onApply={handleApply} />);
    expect(screen.queryByText('subscriptionClients.happRouting.invalidString')).toBeNull();

    // Set invalid value again -> error appears
    rerender(<HappRoutingEditor routingValue={corruptRouting} onApply={handleApply} />);
    expect(screen.getByText('subscriptionClients.happRouting.invalidString')).toBeTruthy();

    // Set valid value -> error must disappear!
    const validRouting = encodeHappRouting({ Name: 'Valid' });
    rerender(<HappRoutingEditor routingValue={validRouting} onApply={handleApply} />);
    expect(screen.queryByText('subscriptionClients.happRouting.invalidString')).toBeNull();
  });

  it('битая строка не роняет экран', () => {
    const handleApply = vi.fn();

    // Test with completely corrupted payload
    const corruptRouting = 'happ://routing/onadd/corrupted-base64---not-valid-json';

    // Must not throw during render
    render(<HappRoutingEditor routingValue={corruptRouting} onApply={handleApply} />);

    // Shows error message
    expect(
      screen.getByText('subscriptionClients.happRouting.invalidString'),
    ).toBeTruthy();

    // Form is still interactive: choose preset russia
    const russiaPresetButton = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.presets.russia',
    });
    fireEvent.click(russiaPresetButton);

    // Apply russia preset
    const applyButton = screen.getByRole('button', {
      name: 'subscriptionClients.happRouting.apply',
    });
    fireEvent.click(applyButton);

    expect(handleApply).toHaveBeenCalledTimes(1);
    const applied = handleApply.mock.calls[0][0];
    const decoded = decodeHappRouting(applied);
    expect(decoded.data?.DirectSites).toContain('geosite:category-ru');
  });

  it('панель устройств показывает и удаляет запись', async () => {
    const mockDevices = [
      {
        id: 101,
        subject: 'client-user@example.com',
        device_os: 'iOS',
        os_version: '18.1',
        model: 'iPhone 16 Pro',
        first_seen: 1730000000,
        last_seen: 1730050000,
      },
    ];

    apiGet.mockImplementation((url: string) => {
      if (url === '/v1/subscription-client-settings/devices') {
        return Promise.resolve({ data: { devices: mockDevices } });
      }
      return Promise.resolve({ data: {} });
    });

    apiDelete.mockResolvedValueOnce({ data: { status: 'deleted' } });

    render(<SubscriptionDevicesPanel />);

    await waitFor(() => {
      expect(screen.getAllByText('client-user@example.com').length).toBeGreaterThan(0);
    });

    // Groups start collapsed; phone and desktop layouts are both in the DOM
    expect(screen.queryByText('iPhone 16 Pro')).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: 'subscriptionClients.devices.expandGroup' })[0]);

    expect(screen.getAllByText('iOS').length).toBeGreaterThan(0);
    expect(screen.getAllByText('18.1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('iPhone 16 Pro').length).toBeGreaterThan(0);

    // Verify HWID is not displayed anywhere in document
    expect(screen.queryByText(/hwid/i)).toBeNull();

    // Click Delete button
    const deleteBtn = screen.getAllByRole('button', {
      name: 'subscriptionClients.devices.delete',
    })[0];
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(apiDelete).toHaveBeenCalledWith('/v1/subscription-client-settings/devices/101');
    });

    // Record removed from screen, empty state shown
    await waitFor(() => {
      expect(screen.queryByText('client-user@example.com')).toBeNull();
    });
    expect(screen.getByText('subscriptionClients.devices.empty')).toBeTruthy();
    expect(toastMock).toHaveBeenCalledWith('subscriptionClients.devices.deleted', 'success');
  });

  it('вкладка Содержимое вставляет токены в remark_template', async () => {
    const mockInitialSettings = {
      profile: { title: 'Title', support_url: '', web_page_url: '', announce: '', update_interval_hours: null },
      clients: [],
      content: {
        remark_template: 'Server - ',
      },
    };

    apiGet.mockResolvedValueOnce({
      data: {
        settings: mockInitialSettings,
        schema: {},
        section_schema: {
          content: [
            { key: 'remark_template', type: 'text' as const, group: 'body' },
          ],
        },
        formats: ['base64'],
      },
    });

    render(<SubscriptionClientSettings />);

    await waitFor(() => {
      expect(screen.getByText('subscriptionClients.tabs.content')).toBeTruthy();
    });

    // Switch to content tab
    fireEvent.click(screen.getByText('subscriptionClients.tabs.content'));

    const remarkInput = screen.getByLabelText(
      'subscriptionClients.sections.content.remark_template',
    ) as HTMLInputElement;
    expect(remarkInput.value).toBe('Server - ');

    // Click {{NODE}} token button
    const nodeTokenBtn = screen.getByRole('button', {
      name: 'subscriptionClients.content.insertToken {{NODE}}',
    });
    fireEvent.click(nodeTokenBtn);

    expect(remarkInput.value).toBe('Server - {{NODE}}');

    // Click {{EMAIL}} token button
    const emailTokenBtn = screen.getByRole('button', {
      name: 'subscriptionClients.content.insertToken {{EMAIL}}',
    });
    fireEvent.click(emailTokenBtn);

    expect(remarkInput.value).toBe('Server - {{NODE}}{{EMAIL}}');
  });

  it('для page.theme нет пункта «не задано» и пустое значение показывает первый вариант', () => {
    const pageFields: SectionFieldSchema[] = [
      { key: 'theme', type: 'enum', group: 'appearance', options: ['remnawave', '3xui'] },
    ];

    const handleChange = vi.fn();

    const { rerender } = render(
      <SubscriptionSettingsSections
        sectionKey="page"
        fields={pageFields}
        values={{ theme: '' }}
        onChange={handleChange}
      />,
    );

    const selectButton = screen.getByRole('button', {
      name: 'subscriptionClients.sections.page.theme',
    });
    expect(selectButton.textContent).toBe('subscriptionClients.options.remnawave');

    fireEvent.click(selectButton);

    const listbox = screen.getByRole('listbox');
    expect(within(listbox).queryByText('subscriptionClients.notSet')).toBeNull();
    expect(within(listbox).getByText('subscriptionClients.options.remnawave')).toBeTruthy();
    expect(within(listbox).getByText('subscriptionClients.options.3xui')).toBeTruthy();

    fireEvent.click(within(listbox).getByText('subscriptionClients.options.3xui'));
    expect(handleChange).toHaveBeenCalledWith('theme', '3xui');

    rerender(
      <SubscriptionSettingsSections
        sectionKey="page"
        fields={pageFields}
        values={{ theme: '3xui' }}
        onChange={handleChange}
      />,
    );
    expect(selectButton.textContent).toBe('subscriptionClients.options.3xui');
  });
});
