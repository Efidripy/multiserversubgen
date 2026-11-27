import type { ReactNode } from 'react';
import './logHighlight.css';

// Colouring follows the 3x-ui log viewer: timestamp, level, XRAY tag; plus Xray access-log fields.
const TOKENS = /(^(?:\d{4}[/-]\d{2}[/-]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?|[A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2})|\b(?:DEBUG|INFO|NOTICE|WARNING|ERROR|DIRECT|BLOCKED|PROXY)\b|\[(?:Debug|Info|Warning|Error)\]|\bXRAY:|\b(?:time|from|to|inbound|outbound|email|event)=)/gm;

function tokenClass(token: string): string {
  if (/^(\d{4}|[A-Z][a-z]{2} )/.test(token)) return 'log-stamp';
  if (token.endsWith('=')) return 'log-key';
  if (token === 'XRAY:') return 'log-service';
  return `log-${token.replace(/[[\]]/g, '').toLowerCase()}`;
}

/** Wraps known tokens in spans; the text content stays byte-for-byte the same. */
export function highlightLog(text: string): ReactNode[] {
  // split() with one capture group puts the matched tokens at odd indexes.
  const parts = text.split(TOKENS);
  return parts.map((part, index) => {
    if (index % 2 === 0) return part;
    return <span key={index} className={tokenClass(part)}>{part}</span>;
  });
}
