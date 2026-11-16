import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  updateUserRole: vi.fn(),
  deleteUserRole: vi.fn(),
}));

vi.mock('../src/api/users', () => mocks);
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { UsersAdmin } from '../src/components/UsersAdmin';

describe('UsersAdmin', () => {
  beforeEach(() => {
    mocks.listUsers.mockResolvedValue({
      users: [
        { username: 'env-user', role: 'admin', source: 'env', owner: true, locked: true },
        { username: 'db-user', role: 'viewer', source: 'db', owner: false, locked: false },
      ],
      candidates: ['candidate'],
    });
    mocks.updateUserRole.mockResolvedValue({ username: 'db-user', role: 'operator', source: 'db' });
    mocks.deleteUserRole.mockResolvedValue({ username: 'db-user', removed: true });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('renders users and disables locked assignments', async () => {
    render(<UsersAdmin currentUser="current" />);
    expect(await screen.findByText('env-user')).toBeTruthy();
    expect(screen.getByText('db-user')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'usersAdmin.role env-user' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('updates a database role and reloads the list', async () => {
    render(<UsersAdmin />);
    const roleButton = await screen.findByRole('button', { name: 'usersAdmin.role db-user' });
    fireEvent.click(roleButton);
    fireEvent.click(screen.getByRole('button', { name: 'usersAdmin.roles.operator' }));
    await waitFor(() => expect(mocks.updateUserRole).toHaveBeenCalledWith('db-user', 'operator'));
    await waitFor(() => expect(mocks.listUsers).toHaveBeenCalledTimes(2));
  });

  it('shows the server error for a conflict', async () => {
    mocks.updateUserRole.mockRejectedValue({ response: { status: 409, data: { detail: 'locked by configuration' } } });
    render(<UsersAdmin />);
    fireEvent.click(await screen.findByRole('button', { name: 'usersAdmin.role db-user' }));
    fireEvent.click(screen.getByRole('button', { name: 'usersAdmin.roles.operator' }));
    expect((await screen.findByRole('alert')).textContent).toContain('locked by configuration');
  });
});
