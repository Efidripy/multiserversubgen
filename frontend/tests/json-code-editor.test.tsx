import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EditorView } from 'codemirror';
import JsonCodeEditor from '../src/components/JsonCodeEditor';
afterEach(cleanup);
it('mounts a real CodeMirror editor and reports edits', () => {
  const change = vi.fn();
  render(<JsonCodeEditor value="{}" onChange={change} label="JSON editor" />);
  const content = screen.getByLabelText('JSON editor');
  const editor = EditorView.findFromDOM(content)!;
  editor.dispatch({ changes: { from: 1, insert: '"x":1' } });
  expect(change).toHaveBeenCalledWith('{"x":1}');
});
