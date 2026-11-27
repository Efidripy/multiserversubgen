import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { deletePath, getPath, setPath } from './paths';
import type { FieldDef, ItemContext, Outbound, Path } from './types';

type Props = { value: Outbound; fields: FieldDef[]; onChange: (value: Outbound) => void; context?: ItemContext };

function JsonField({ value, onChange, label }: { value: unknown; onChange: (v: unknown) => void; label: string }) {
  const [text, setText] = useState(() => value === undefined ? '' : JSON.stringify(value, null, 2));
  return <textarea className="form-control" aria-label={label} value={text} onChange={event => {
    const next = event.target.value;
    setText(next);
    if (!next) onChange(undefined);
    else try { onChange(JSON.parse(next)); } catch { /* retain invalid draft */ }
  }} />;
}

function Generator({ kind, onChange }: { kind: NonNullable<FieldDef['generate']>; onChange: (v: string) => void }) {
  const [available, setAvailable] = useState(kind !== 'x25519' && typeof globalThis.crypto?.getRandomValues === 'function');
  const [publicKey, setPublicKey] = useState('');
  useEffect(() => {
    if (kind !== 'x25519' || !globalThis.crypto?.subtle) return;
    let active = true;
    crypto.subtle.generateKey({ name: 'X25519' }, true, ['deriveBits']).then(() => {
      if (active) setAvailable(true);
    }).catch(() => {});
    return () => { active = false; };
  }, [kind]);
  if (!available) return null;
  const generate = async () => {
    if (kind === 'x25519') {
      try {
        const pair = await crypto.subtle.generateKey({ name: 'X25519' }, true, ['deriveBits']) as CryptoKeyPair;
        const privateJwk = await crypto.subtle.exportKey('jwk', pair.privateKey);
        const publicBytes = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
        if (!privateJwk.d) return;
        const base64 = (s: string) => s.replace(/-/g, '+').replace(/_/g, '/').padEnd(44, '=');
        onChange(base64(privateJwk.d));
        setPublicKey(btoa(String.fromCharCode(...publicBytes)));
      } catch { setAvailable(false); }
      return;
    }
    const chars = kind === 'shortId' ? '0123456789abcdef' : 'abcdefghijklmnopqrstuvwxyz0123456789';
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    onChange(Array.from(bytes, b => chars[b % chars.length]).join(''));
  };
  return <span><button type="button" className="btn btn-sm btn-ghost-secondary" onClick={() => void generate()}>Regenerate</button>
    {publicKey && <output>Public Key: {publicKey}</output>}</span>;
}

export function SchemaForm({ value, fields, onChange, context }: Props) {
  const { t } = useTranslation();
  const render = (field: FieldDef, index: number) => {
    if (field.showIf && !field.showIf(value, context)) return null;
    const relative = typeof field.path === 'function' ? field.path(value, context) : field.path;
    const path: Path = context && typeof field.path !== 'function' ? [...context.path, ...relative] : relative;
    const stored = getPath(value, path);
    const current = field.read ? field.read(stored, value, path) : stored;
    const options = typeof field.options === 'function' ? field.options(value) : field.options || [];
    const change = (next: unknown) => {
      if (field.write) next = field.write(next, value, path);
      const clear = typeof field.clearValue === 'function' ? field.clearValue(next) : field.clearValue !== undefined && next === field.clearValue;
      const updated = field.uiOnly ? structuredClone(value) : clear ? deletePath(value, path) : setPath(value, path, next);
      onChange(field.onChange ? field.onChange(updated, next, path, value) : updated);
    };
    const key = `${path.join('.')}-${index}`;
    if (field.kind === 'section') return <details key={key} className="sm:col-span-2"><summary>{t(field.label)}</summary>
      <SchemaForm value={value} fields={field.fields || []} onChange={onChange} context={context} />
    </details>;
    if (field.kind === 'toggle') return <div key={key} className="sm:col-span-2"><label>
      <input type="checkbox" checked={current !== undefined} onChange={event => {
        if (event.target.checked) change(structuredClone(typeof field.defaults === 'function' ? field.defaults(value) : field.defaults ?? {}));
        else if (!current || !Object.keys(current).length || window.confirm(t('nodeOps.removeBlockConfirm'))) change(undefined);
      }} /> {t(field.label)}</label>
      {current !== undefined && <SchemaForm value={value} fields={field.fields || []} onChange={onChange} context={context} />}
    </div>;
    if (field.kind === 'array') {
      const items = Array.isArray(current) ? current : [];
      return <div key={key} className="sm:col-span-2"><span>{t(field.label)}</span>{items.map((item: Outbound, i: number) => {
        const move = (j: number) => { const next = [...items]; [next[i], next[j]] = [next[j], next[i]]; change(next); };
        return <div key={i}><SchemaForm value={value} fields={field.fields || []} onChange={onChange}
          context={{ path: [...path, i], value: item, index: i }} />
          <button type="button" className="btn btn-sm btn-ghost-secondary" disabled={i === 0} onClick={() => move(i - 1)}>{t('nodeOps.arrayUp')}</button>
          <button type="button" className="btn btn-sm btn-ghost-secondary" disabled={i === items.length - 1} onClick={() => move(i + 1)}>{t('nodeOps.arrayDown')}</button>
          <button type="button" className="btn btn-sm btn-ghost-secondary" onClick={() => change(items.filter((_: unknown, n: number) => n !== i))}>{t('common.delete')}</button>
        </div>;
      })}<button type="button" className="btn btn-sm btn-ghost-secondary" onClick={() => change([...items, structuredClone(typeof field.defaults === 'function' ? field.defaults(value) : field.defaults ?? {})])}>{t('nodeOps.arrayAdd')}</button></div>;
    }
    if (field.kind === 'keyValue') return <div key={key} className="sm:col-span-2"><span>{t(field.label)}</span>
      {Object.entries(current || {}).map(([name, entry], row) => <div key={row}>
        <input aria-label={t('nodeOps.key')} value={name} onChange={event => {
          const next = { ...current }; delete next[name]; next[event.target.value] = entry; change(next);
        }} />
        <input aria-label={t('nodeOps.value')} value={String(entry)} onChange={event => change({ ...current, [name]: event.target.value })} />
        <button type="button" className="btn btn-sm btn-ghost-secondary" onClick={() => { const next = { ...current }; delete next[name]; change(next); }}>{t('common.delete')}</button>
      </div>)}<button type="button" className="btn btn-sm btn-ghost-secondary" onClick={() => { let name = ''; while (name in (current || {})) name += '_';
        change({ ...current, [name]: '' }); }}>{t('nodeOps.arrayAdd')}</button></div>;
    if (field.kind === 'json') return <label key={key} className="flex flex-col gap-1"><span>{t(field.label)}</span>
      <JsonField value={current} onChange={change} label={t(field.label)} /></label>;
    if (field.kind === 'lineList') return <label key={key} className="flex flex-col gap-1"><span>{t(field.label)}</span>
      <textarea className="form-control" value={Array.isArray(current) ? current.join('\n') : ''}
        onChange={event => change(event.target.value.split(/\r?\n/))} /></label>;
    if (field.kind === 'boolean') return <label key={key}><input type="checkbox" checked={current === true}
      onChange={event => change(event.target.checked)} /> {t(field.label)}</label>;
    if (field.kind === 'select') return <label key={key} className="flex flex-col gap-1"><span>{t(field.label)}</span>
      <select className="form-select" value={current ?? ''} onChange={event => change(event.target.value)}>
        {!options.includes('') && <option value="" />}
        {current != null && current !== '' && !options.includes(current) && <option value={current}>{current}</option>}
        {options.map(option => <option key={option} value={option}>{option}</option>)}
      </select></label>;
    const id = `options-${key}`;
    return <label key={key} className="flex flex-col gap-1"><span>{t(field.label)}</span>
      <input className="form-control" list={field.kind === 'combobox' ? id : undefined} placeholder={field.placeholder}
        type={field.kind === 'number' ? 'number' : field.kind === 'datetime' ? 'datetime-local' : 'text'} value={Array.isArray(current) ? current.join(', ') : current ?? ''}
        onChange={event => {
          const input = event.target.value;
          if (field.kind === 'list' || field.kind === 'numberList') {
            change(input ? input.split(',').map(s => s.trim()).filter(Boolean).map(s => field.kind === 'numberList' ? Number(s) : s) : undefined);
          } else change(field.kind === 'number' && input !== '' ? Number(input) : input);
        }} />
      {field.generate && <Generator kind={field.generate} onChange={change} />}
      {field.kind === 'combobox' && <datalist id={id}>{options.map(option => <option key={option} value={option} />)}</datalist>}
    </label>;
  };
  return <div className="grid gap-2 sm:grid-cols-2">{fields.map(render)}</div>;
}
