import { useState } from 'react';
import { ArrowDown, ArrowUp, Copy, Pencil, Star, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { OutboundEditor } from './OutboundEditor';
import type { Outbound } from './types';

const button = 'btn btn-sm btn-ghost-secondary';
export function outboundReferences(template: Outbound, outbounds: Outbound[], tag: string): string[] {
  if (!tag) return [];
  const result: string[] = [];
  (Array.isArray(template.routing?.rules) ? template.routing.rules : []).forEach((rule: Outbound, i: number) => {
    if (rule?.outboundTag === tag) result.push(`routing.rules[${i}].outboundTag`);
  });
  (Array.isArray(template.routing?.balancers) ? template.routing.balancers : []).forEach((balancer: Outbound, i: number) => {
    if (Array.isArray(balancer?.selector) && balancer.selector.includes(tag)) result.push(`routing.balancers[${i}].selector`);
  });
  outbounds.forEach((outbound, i) => {
    if (outbound?.streamSettings?.sockopt?.dialerProxy === tag) result.push(`outbounds[${i}].streamSettings.sockopt.dialerProxy`);
  });
  return result;
}
export function OutboundTable({ value, template, onChange, onEditing }: {
  value: Outbound[]; template: Outbound; onChange: (value: Outbound[]) => void; onEditing: (editing: boolean) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<number | null>(null);
  const start = (index: number) => { setEditing(index); onEditing(true); };
  const close = () => { setEditing(null); onEditing(false); };
  const confirmRefs = (tag: string) => {
    const refs = outboundReferences(template, value, tag);
    return !refs.length || window.confirm(`${t('nodeOps.outboundReferences')}\n${refs.join('\n')}`);
  };
  const move = (i: number, j: number) => {
    const next = [...value];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  if (editing !== null) return <OutboundEditor initial={editing < 0 ? { tag: '', protocol: 'vless', settings: {} } : value[editing]}
    tags={value.filter((_, i) => i !== editing).map(outbound => outbound.tag).filter(Boolean)} onCancel={close} onApply={draft => {
      if (editing >= 0 && value[editing].tag !== draft.tag && !confirmRefs(value[editing].tag)) return;
      const next = [...value];
      if (editing < 0) next.push(draft); else next[editing] = draft;
      onChange(next);
      close();
    }} />;
  return <>
    <div><button type="button" className={button} onClick={() => start(-1)}>{t('nodeOps.addOutbound')}</button></div>
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="table table-sm min-w-[700px]">
        <thead><tr>{['#', 'tag', 'protocol', t('nodeOps.addressPort'), 'transport', 'security', t('common.actions')]
          .map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{value.map((outbound, i) => {
          const server = outbound.settings?.vnext?.[0] || outbound.settings?.servers?.[0] || outbound.settings || {};
          return <tr key={i}>
            <td>{i + 1}{i === 0 && <span title={t('nodeOps.defaultOutboundHint')} aria-label={t('nodeOps.defaultOutboundHint')}>
              <Star size={14} /></span>}</td>
            <td>{outbound.tag}</td>
            <td>{outbound.protocol}</td>
            <td>{server.address ? `${server.address}:${server.port ?? ''}` : ''}</td>
            <td>{outbound.streamSettings?.network || ''}</td>
            <td>{outbound.streamSettings?.security || ''}</td>
            <td><div className="flex gap-1">
              <button className={button} disabled={i === 0} onClick={() => move(i, i - 1)}
                title={t('nodeOps.moveUp', { number: i + 1 })} aria-label={t('nodeOps.moveUp', { number: i + 1 })}>
                <ArrowUp size={14} /></button>
              <button className={button} disabled={i === value.length - 1} onClick={() => move(i, i + 1)}
                title={t('nodeOps.moveDown', { number: i + 1 })} aria-label={t('nodeOps.moveDown', { number: i + 1 })}>
                <ArrowDown size={14} /></button>
              <button className={button} onClick={() => start(i)} aria-label={t('common.edit')} title={t('common.edit')}>
                <Pencil size={14} /></button>
              <button className={button} onClick={() => {
                let tag = `${outbound.tag || 'outbound'}-copy`;
                let n = 2;
                while (value.some(item => item.tag === tag)) tag = `${outbound.tag || 'outbound'}-copy-${n++}`;
                onChange([...value, { ...structuredClone(outbound), tag }]);
              }} aria-label={t('common.copy')} title={t('common.copy')}><Copy size={14} /></button>
              <button className={button} onClick={() => {
                if (confirmRefs(outbound.tag)) onChange(value.filter((_, n) => n !== i));
              }} aria-label={t('common.delete')} title={t('common.delete')}><Trash2 size={14} /></button>
            </div></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  </>;
}
