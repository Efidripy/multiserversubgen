type Listener = (pending: number) => void;

class RequestActivityStore {
  private pending = 0;
  private listeners = new Set<Listener>();

  getPending(): number {
    return this.pending;
  }

  increment(): void {
    this.pending += 1;
    this.emit();
  }

  decrement(): void {
    this.pending = Math.max(0, this.pending - 1);
    this.emit();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.pending);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private emit(): void {
    for (const listener of this.listeners) {
      listener(this.pending);
    }
  }
}

export const requestActivityStore = new RequestActivityStore();
