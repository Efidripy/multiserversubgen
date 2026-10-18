import { createElement } from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  beginProjectionOperation,
  clearProjectionOperation,
  clientProjectionTargetKey,
  setProjectionOperationStatus,
  setProjectionOperationTargetStatus,
  useProjectionOperations,
} from '../src/services/projectionOperationStore';

const createdOperationIds: number[] = [];

afterEach(() => {
  createdOperationIds.forEach(clearProjectionOperation);
  createdOperationIds.length = 0;
});

const TargetOverlayProbe = () => {
  const operations = useProjectionOperations('clients');
  return createElement('output', { 'data-testid': 'operations' }, JSON.stringify(operations));
};

describe('client node operation overlays', () => {
  it('keeps operation status at the exact node plus inbound target and separates partial aggregate state', () => {
    render(createElement(TargetOverlayProbe));
    const primaryKey = clientProjectionTargetKey(10, 101, 'example@invalid');
    const secondaryKey = clientProjectionTargetKey(11, 101, 'example@invalid');

    let operationId = 0;
    act(() => {
      operationId = beginProjectionOperation('clients', 'projection add', {
        kind: 'add',
        targets: [
          { key: primaryKey, nodeId: 10, inboundId: 101, email: 'example@invalid' },
          { key: secondaryKey, nodeId: 11, inboundId: 101, email: 'example@invalid' },
        ],
      });
      createdOperationIds.push(operationId);
      setProjectionOperationStatus(operationId, 'partial');
      setProjectionOperationTargetStatus(operationId, primaryKey, 'remote_succeeded_awaiting_projection');
      setProjectionOperationTargetStatus(operationId, secondaryKey, 'failed');
    });

    const operation = JSON.parse(screen.getByTestId('operations').textContent || '[]')[0];
    expect(operation.status).toBe('partial');
    expect(operation.targets).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: primaryKey, nodeId: 10, inboundId: 101, status: 'remote_succeeded_awaiting_projection' }),
      expect.objectContaining({ key: secondaryKey, nodeId: 11, inboundId: 101, status: 'failed' }),
    ]));
  });

  it('does not change the target identity when a status reaches projection confirmation', () => {
    render(createElement(TargetOverlayProbe));
    const targetKey = clientProjectionTargetKey(10, 202, 'example@invalid');

    let operationId = 0;
    act(() => {
      operationId = beginProjectionOperation('clients', 'projection delete', {
        kind: 'delete',
        targets: [{ key: targetKey, nodeId: 10, inboundId: 202, email: 'example@invalid' }],
      });
      createdOperationIds.push(operationId);
      setProjectionOperationStatus(operationId, 'visible_in_projection');
      setProjectionOperationTargetStatus(operationId, targetKey, 'visible_in_projection');
    });

    const operation = JSON.parse(screen.getAllByTestId('operations').at(-1)?.textContent || '[]')[0];
    expect(operation.targets[0]).toMatchObject({ key: targetKey, nodeId: 10, inboundId: 202, status: 'visible_in_projection' });
  });
});
