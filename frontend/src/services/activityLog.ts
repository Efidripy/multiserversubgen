/**
 * Activity Log — singleton ring buffer for frontend action logging. v2
 * 4 levels: debug (everything), info, warning, error.
 *
 * Usage:
 *   import { activityLog } from '../services/activityLog';
 *   activityLog.info('ClientManager', 'Add client clicked', { node: 'DE-82FR', email: 'user@x' });
 *   activityLog.error('ServerStatus', 'Restart Xray failed', { error: '403' });
 */

export type LogLevel = 'debug' | 'info' | 'warning' | 'error';

export interface LogEntry {
  id: string;
  ts: number;
  level: LogLevel;
  section: string;
  message: string;
  context?: Record<string, unknown>;
}

type Subscriber = (entries: LogEntry[]) => void;

const RING_SIZE = 500;
export const LEVEL_RANK: Record<LogLevel, number> = { debug: 0, info: 1, warning: 2, error: 3 };

class ActivityLogStore {
  private entries: LogEntry[] = [];
  private subscribers = new Set<Subscriber>();

  private push(level: LogLevel, section: string, message: string, context?: Record<string, unknown>) {
    const entry: LogEntry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      ts: Date.now(),
      level,
      section,
      message,
      context,
    };
    this.entries.push(entry);
    if (this.entries.length > RING_SIZE) {
      this.entries.splice(0, this.entries.length - RING_SIZE);
    }
    this.notify();
    const prefix = `[${section}]`;
    if (level === 'error') console.error(prefix, message, context ?? '');
    else if (level === 'warning') console.warn(prefix, message, context ?? '');
    else if (level === 'debug') console.debug(prefix, message, context ?? '');
    else console.info(prefix, message, context ?? '');
  }

  debug(section: string, message: string, context?: Record<string, unknown>) { this.push('debug', section, message, context); }
  info(section: string, message: string, context?: Record<string, unknown>) { this.push('info', section, message, context); }
  warning(section: string, message: string, context?: Record<string, unknown>) { this.push('warning', section, message, context); }
  error(section: string, message: string, context?: Record<string, unknown>) { this.push('error', section, message, context); }

  getEntries(minLevel: LogLevel = 'debug'): LogEntry[] {
    const minRank = LEVEL_RANK[minLevel];
    return this.entries.filter(e => LEVEL_RANK[e.level] >= minRank);
  }

  clear() { this.entries = []; this.notify(); }

  subscribe(fn: Subscriber): () => void {
    this.subscribers.add(fn);
    fn([...this.entries]);
    return () => this.subscribers.delete(fn);
  }

  private notify() {
    const snapshot = [...this.entries];
    this.subscribers.forEach(fn => fn(snapshot));
  }

  exportText(minLevel: LogLevel = 'debug'): string {
    return this.getEntries(minLevel)
      .map(e => {
        const time = new Date(e.ts).toLocaleTimeString('ru', { hour12: false });
        const ctx = e.context ? ' ' + JSON.stringify(e.context) : '';
        return `[${time}] ${e.level.toUpperCase().padEnd(7)} [${e.section}] ${e.message}${ctx}`;
      })
      .join('\n');
  }
}

export const activityLog = new ActivityLogStore();
