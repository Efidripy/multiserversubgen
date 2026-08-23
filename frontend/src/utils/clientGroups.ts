export interface ClientEmailRecord {
  email: string;
}

export interface ClientEmailGroup<T extends ClientEmailRecord> {
  /** Stable logical-user identifier, intentionally independent of node records. */
  key: string;
  /** First non-empty spelling received from the API, kept for operator display. */
  email: string;
  /** Original node/inbound records. Their identity and API semantics stay intact. */
  clients: T[];
}

export const normalizeClientEmail = (email: string): string => email.trim().toLowerCase();

/**
 * Builds a presentation-only logical-user projection. Callers retain ownership
 * of filtering, sorting, API payloads and all record-level operations.
 */
export const groupClientsByEmail = <T extends ClientEmailRecord>(clients: T[]): ClientEmailGroup<T>[] => {
  const groups = new Map<string, ClientEmailGroup<T>>();

  clients.forEach((client) => {
    const key = normalizeClientEmail(client.email);
    const existing = groups.get(key);

    if (existing) {
      existing.clients.push(client);
      return;
    }

    groups.set(key, {
      key,
      email: client.email.trim() || client.email,
      clients: [client],
    });
  });

  return Array.from(groups.values());
};
