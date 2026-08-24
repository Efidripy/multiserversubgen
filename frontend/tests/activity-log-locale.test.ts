import { afterEach, describe, expect, it, vi } from 'vitest';
import { activityLog } from '../src/services/activityLog';

describe('Activity Log locale formatting', () => {
  afterEach(() => {
    activityLog.clear();
    vi.restoreAllMocks();
  });

  it('formats exported timestamps in the caller-selected locale', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000);
    const formatTime = vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('10:00');
    activityLog.info('test', 'entry');

    expect(activityLog.exportText('debug', 'en-US')).toContain('[10:00]');
    expect(formatTime).toHaveBeenCalledWith('en-US', { hour12: false });
  });
});
