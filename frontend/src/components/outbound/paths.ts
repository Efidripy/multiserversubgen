import type { Outbound, Path } from './types';

export function getPath(value: unknown, path: Path): any {
  return path.reduce<any>((current, key) => current?.[key], value);
}

export function deletePath(value: Outbound, path: Path): Outbound {
  if (!path.length || getPath(value, path) === undefined) return value;
  const next = structuredClone(value);
  const parents: any[] = [next];
  for (const key of path.slice(0, -1)) parents.push(parents[parents.length - 1][key]);
  const last = parents[parents.length - 1];
  delete last[path[path.length - 1]];
  for (let i = path.length - 1; i > 0; i--) {
    const child = parents[i];
    if (Array.isArray(child) || Object.keys(child).length) break;
    delete parents[i - 1][path[i - 1]];
  }
  return next;
}

export function setPath(value: Outbound, path: Path, field: unknown): Outbound {
  if (!path.length) return value;
  if (field === undefined || field === '') return deletePath(value, path);
  const next = structuredClone(value);
  let current: any = next;
  path.forEach((key, index) => {
    if (index === path.length - 1) current[key] = field;
    else {
      if (!current[key] || typeof current[key] !== 'object') current[key] = typeof path[index + 1] === 'number' ? [] : {};
      current = current[key];
    }
  });
  return next;
}
