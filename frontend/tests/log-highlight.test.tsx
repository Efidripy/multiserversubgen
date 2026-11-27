// @vitest-environment jsdom
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { highlightLog } from '../src/components/logHighlight';

describe('highlightLog', () => {
  it('colours panel and Xray tokens without changing the text', () => {
    const text = '2026/11/27 12:47:12 WARNING - XRAY: blocked INFORMATION\nNov 27 12:00:00 host x-ui[1]: ERROR - boom\ntime=2026-11-27T12:00:00Z | event=BLOCKED';
    const { container } = render(<pre>{highlightLog(text)}</pre>);
    expect(container.textContent).toBe(text);
    expect(Array.from(container.querySelectorAll('span'), (s) => `${s.className}:${s.textContent}`)).toEqual([
      'log-stamp:2026/11/27 12:47:12', 'log-warning:WARNING', 'log-service:XRAY:',
      'log-stamp:Nov 27 12:00:00', 'log-error:ERROR',
      'log-key:time=', 'log-key:event=', 'log-blocked:BLOCKED',
    ]);
  });
});
