import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { InboundEditModal } from '../src/components/InboundEditModal';
import i18n from '../src/i18n/config';

vi.mock('../src/api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {
  remark: 'main', protocol: 'vless', settings: {}, streamSettings: {}, sniffing: {},
} }) } }));

describe('InboundEditModal localization', () => {
  afterEach(async () => { cleanup(); await i18n.changeLanguage('en'); });
  it('renders localized controls and schema labels', async () => {
    await i18n.changeLanguage('ru');
    render(<InboundEditModal inbound={{ id: 7, node_name: 'node', protocol: 'vless' }} nodeId={1}
      onClose={() => {}} onSaved={() => {}} />);
    expect(await screen.findByLabelText('Remark')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'JSON' }).getAttribute('aria-pressed')).toBe('false');
  });
});
