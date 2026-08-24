import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { InboundEditModal } from '../src/components/InboundEditModal';
import { ThemeProvider } from '../src/contexts/ThemeContext';
import i18n from '../src/i18n/config';

describe('InboundEditModal localization', () => {
  afterEach(async () => {
    cleanup();
    await i18n.changeLanguage('en');
  });

  it('renders all form-facing labels in Russian without changing protocol values', async () => {
    await i18n.changeLanguage('ru');

    render(
      <ThemeProvider>
        <InboundEditModal
          inbound={{
            id: 7,
            node_name: 'test-node',
            protocol: 'vless',
            port: 443,
            remark: 'main',
            enable: true,
            security: 'none',
            is_reality: false,
          }}
          nodeId={1}
          onClose={() => undefined}
          onSaved={() => undefined}
        />
      </ThemeProvider>,
    );

    expect(screen.getByRole('tab', { name: 'Форма' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Исходный JSON' })).toBeTruthy();
    expect(screen.getByText('IP для прослушивания')).toBeTruthy();
    expect(screen.getByTitle('Оставьте пустым, чтобы слушать все IP-адреса')).toBeTruthy();
    expect(screen.getByText('Транспорт')).toBeTruthy();
    expect(screen.getByText('Параметры сокета')).toBeTruthy();
    expect(screen.getByText('Сниффинг')).toBeTruthy();
    expect(screen.getByText('TCP (RAW)')).toBeTruthy();
  });
});
