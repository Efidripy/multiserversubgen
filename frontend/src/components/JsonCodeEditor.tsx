import { useEffect, useRef } from 'react';
import { basicSetup, EditorView } from 'codemirror';
import { EditorState } from '@codemirror/state';
import { json, jsonParseLinter } from '@codemirror/lang-json';
import { linter, lintGutter } from '@codemirror/lint';

export default function JsonCodeEditor({ value, onChange, readOnly = false, label }: { value: string; onChange?: (value: string) => void; readOnly?: boolean; label: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const change = useRef(onChange);
  change.current = onChange;
  useEffect(() => {
    const editor = new EditorView({ parent: host.current!, state: EditorState.create({ doc: value, extensions: [basicSetup, json(), linter((editor) => jsonParseLinter()(editor).map((diagnostic) => { const line = editor.state.doc.lineAt(diagnostic.from); return { ...diagnostic, from: line.from, to: line.to }; })), lintGutter(), EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly), EditorView.contentAttributes.of({ 'aria-label': label }), EditorView.updateListener.of((update) => { if (update.docChanged) change.current?.(update.state.doc.toString()); }), EditorView.theme({ '&': { height: '100%', color: 'var(--text-primary)', backgroundColor: 'var(--bg-primary)' }, '.cm-gutters': { color: 'var(--text-secondary)', backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }, '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--bg-tertiary)' }, '.cm-cursor': { borderLeftColor: 'var(--text-primary)' }, '.cm-content span': { color: 'var(--text-primary)' }, '.cm-scroller': { overflow: 'auto' }, '.cm-line:has(.cm-lintRange-error)': { backgroundColor: 'color-mix(in srgb, var(--danger) 20%, transparent)' } })] }) });
    view.current = editor;
    return () => { editor.destroy(); view.current = null; };
  // The document is synchronized separately, so typing never recreates the view.
  }, [readOnly, label]);
  useEffect(() => { const editor = view.current; if (editor && editor.state.doc.toString() !== value) editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } }); }, [value]);
  return <div ref={host} className="min-h-0 w-full flex-1 overflow-hidden node-ops-editor" />;
}
