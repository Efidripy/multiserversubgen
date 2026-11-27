import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LazyJsonEditor } from './LazyJsonEditor';

type Rule = Record<string, any>;
const obj = (v: unknown): v is Rule => !!v && typeof v === 'object' && !Array.isArray(v);
const api = (r: Rule) => r.outboundTag === 'api' && Array.isArray(r.inboundTag) && r.inboundTag.includes('api');
const conditions = ['domain', 'ip', 'port', 'sourcePort', 'network', 'source', 'user', 'inboundTag', 'protocol', 'attrs', 'domainMatcher', 'process', 'processPath'];
const present = (v: unknown) => Array.isArray(v) ? v.length > 0 : v !== undefined && v !== null && v !== '';
export const validRule = (r: unknown): r is Rule => obj(r) && (present(r.outboundTag) || present(r.balancerTag)) && conditions.some((key) => key !== 'domainMatcher' && present(r[key]));
export function protectedRouting(value: unknown, original: unknown) {
  if (!obj(value) || !obj(original) || (value.rules !== undefined && !Array.isArray(value.rules)) || (original.rules !== undefined && !Array.isArray(original.rules))) return false;
  const oldRules = original.rules ?? [];
  const newRules = value.rules ?? [];
  const oldIndex = oldRules.findIndex((r: unknown) => obj(r) && api(r));
  if (oldIndex < 0) return true;
  return JSON.stringify(newRules.slice(0, oldIndex + 1)) === JSON.stringify(oldRules.slice(0, oldIndex + 1));
}
const button = 'rounded border border-cyan-500/30 bg-[#0a0e1a] px-2 py-1 text-xs text-slate-200 disabled:opacity-40';
export function RoutingTable({ value, onChange }: { value: Rule; onChange: (value: Rule) => void }) {
  const { t } = useTranslation();
  const rules: Rule[] = Array.isArray(value.rules) ? value.rules : [];
  const [editing, setEditing] = useState<number | null>(null);
  const [ruleText, setRuleText] = useState('');
  const [drag, setDrag] = useState<number | null>(null);
  const protectedIndex = rules.findIndex((r) => obj(r) && api(r));
  const update = (next: Rule[]) => onChange({ ...value, rules: next });
  const move = (from: number, to: number) => {
    if (from <= protectedIndex || to <= protectedIndex || to < 0 || to >= rules.length || from === to) return;
    const next = [...rules]; const [item] = next.splice(from, 1); next.splice(to, 0, item); update(next);
  };
  const start = (index: number) => { setEditing(index); setRuleText(JSON.stringify(index < 0 ? { type: 'field', outboundTag: '', domain: [] } : rules[index], null, 2)); };
  let parsed: unknown; try { parsed = JSON.parse(ruleText); } catch { /* displayed below */ }
  const summary = (...values: unknown[]) => {
    const items = values.flatMap((v) => Array.isArray(v) ? v : present(v) ? [v] : []).map(String);
    return <span title={items.join(', ')}>{items[0] || '—'}{items.length > 1 ? ` +${items.length - 1}` : ''}</span>;
  };
  if (editing !== null) return <div className="flex min-h-0 flex-1 flex-col gap-2"><div className="flex gap-2"><button type="button" className={button} disabled={!validRule(parsed)} onClick={() => { if (!validRule(parsed)) return; const next = [...rules]; if (editing < 0) next.push(parsed); else next[editing] = parsed; update(next); setEditing(null); }}>{t('common.save')}</button><button type="button" className={button} onClick={() => setEditing(null)}>{t('common.cancel')}</button></div>{!validRule(parsed) && <div role="alert" className="text-sm text-rose-300">{t('nodeOps.invalidRule')}</div>}<LazyJsonEditor value={ruleText} onChange={setRuleText} label={t('nodeOps.ruleEditor')} /></div>;
  return <><div><button type="button" className={button} onClick={() => start(-1)}>{t('nodeOps.addRule')}</button></div><div className="min-h-0 flex-1 overflow-auto"><table className="w-full min-w-[700px] text-left text-xs text-slate-200"><thead><tr>{['#', t('common.enabled'), t('nodeOps.comment'), t('nodeOps.networkProtocol'), t('nodeOps.destination'), 'Inbound', 'Outbound', t('common.actions')].map((s) => <th className="px-1.5 py-2" key={s}>{s}</th>)}</tr></thead><tbody>{rules.map((rule, i) => { const locked = i <= protectedIndex; const r = obj(rule) ? rule : {}; return <tr key={i} className="border-t border-slate-700" onDragOver={(e) => { if (drag !== null && i > protectedIndex) e.preventDefault(); }} onDrop={(e) => { e.preventDefault(); if (drag !== null) move(drag, i); setDrag(null); }}><td className="px-1.5 py-2"><span role="img" className={`${button} inline-block select-none ${locked ? 'opacity-40' : 'cursor-grab'}`} draggable={!locked} aria-label={t('nodeOps.dragRule', { number: i + 1 })} onDragStart={(e) => { e.dataTransfer?.setData('text/plain', String(i)); setDrag(i); }} onDragEnd={() => setDrag(null)}>&#8942;&#8942;</span> {i + 1}</td><td className="px-1.5 py-2"><input type="checkbox" aria-label={t('nodeOps.enableRule', { number: i + 1 })} checked={r.enabled !== false} disabled={locked} onChange={(e) => update(rules.map((item, n) => n === i ? { ...r, enabled: e.target.checked } : item))} /></td><td className="px-1.5 py-2">{String(r.comment || '')}</td><td className="px-1.5 py-2">{summary(r.network, r.protocol)}</td><td className="px-1.5 py-2">{summary(r.domain, r.ip, r.port)}</td><td className="px-1.5 py-2">{summary(r.inboundTag, r.user)}</td><td className="px-1.5 py-2">{summary(r.outboundTag, r.balancerTag)}</td><td className="px-1.5 py-2"><div className="flex gap-1"><button type="button" className={button} disabled={locked || i === protectedIndex + 1} aria-label={t('nodeOps.moveUp', { number: i + 1 })} onClick={() => move(i, i - 1)}>&#8593;</button><button type="button" className={button} disabled={locked || i === rules.length - 1} aria-label={t('nodeOps.moveDown', { number: i + 1 })} onClick={() => move(i, i + 1)}>&#8595;</button><button type="button" className={button} disabled={locked} aria-label={t('common.edit')} title={t('common.edit')} onClick={() => start(i)}>&#9998;</button><button type="button" className={button} disabled={locked} onClick={() => update(rules.filter((_, n) => n !== i))} aria-label={t('common.delete')} title={t('common.delete')}>&#10005;</button></div></td></tr>; })}</tbody></table></div></>;
}
