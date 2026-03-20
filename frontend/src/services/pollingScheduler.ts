type PollingTask = {
  id: string;
  intervalMs: number;
  hiddenIntervalMs?: number;
  run: () => void | Promise<void>;
};

type PollingTaskState = {
  task: PollingTask;
  nextRunAt: number;
  running: boolean;
};

class PollingScheduler {
  private tasks = new Map<string, PollingTaskState>();
  private timer: number | null = null;

  private start(): void {
    if (this.timer !== null) return;
    this.timer = window.setInterval(() => this.tick(), 1000);
  }

  private stop(): void {
    if (this.timer === null) return;
    window.clearInterval(this.timer);
    this.timer = null;
  }

  private getEffectiveInterval(task: PollingTask): number {
    if (typeof document !== 'undefined' && document.hidden) {
      return task.hiddenIntervalMs ?? Math.max(task.intervalMs * 3, 30_000);
    }
    return task.intervalMs;
  }

  private tick(): void {
    const now = Date.now();
    this.tasks.forEach((state) => {
      if (state.running || now < state.nextRunAt) return;

      state.running = true;
      Promise.resolve(state.task.run())
        .catch(() => undefined)
        .finally(() => {
          const current = this.tasks.get(state.task.id);
          if (!current) return;
          current.running = false;
          current.nextRunAt = Date.now() + this.getEffectiveInterval(current.task);
        });
    });
  }

  register(task: PollingTask): () => void {
    this.tasks.set(task.id, {
      task,
      nextRunAt: Date.now() + this.getEffectiveInterval(task),
      running: false,
    });
    this.start();

    return () => {
      this.tasks.delete(task.id);
      if (this.tasks.size === 0) {
        this.stop();
      }
    };
  }
}

const scheduler = new PollingScheduler();

export function registerPollingTask(task: PollingTask): () => void {
  return scheduler.register(task);
}
