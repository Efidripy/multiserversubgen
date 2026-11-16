import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  updateUserRole: vi.fn(),
  deleteUserRole: vi.fn(),
  removeUser: vi.fn(),
  updateUserNote: vi.fn(),
}));

vi.mock('../src/api/users', () => mocks);
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { UsersAdmin } from '../src/components/UsersAdmin';

describe('UsersAdmin', () => {
  beforeEach(() => {
    mocks.listUsers.mockResolvedValue({
      users: [
        { username: 'owner-user', role: 'admin', source: 'env', env_role: 'admin', owner: true, locked: true, note: '' },
        { username: 'env-user', role: 'admin', source: 'env', env_role: 'admin', owner: false, locked: false, note: '' },
        { username: 'db-user', role: 'viewer', source: 'db', env_role: null, owner: false, locked: false, note: '' },
      ],
      candidates: ['candidate'],
      me: { username: 'current', owner: false },
    });
    mocks.updateUserRole.mockResolvedValue({ username: 'db-user', role: 'operator', source: 'db' });
    mocks.deleteUserRole.mockResolvedValue({ username: 'db-user', removed: true });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('renders users and disables owner assignments', async () => {
    render(<UsersAdmin currentUser="current" />);
    expect(await screen.findByText('owner-user')).toBeTruthy();
    expect(screen.getByText('db-user')).toBeTruthy();
    const lockedGroup = screen.getByRole('group', { name: 'usersAdmin.role owner-user' });
    for (const chip of within(lockedGroup).getAllByRole('button')) expect((chip as HTMLButtonElement).disabled).toBe(true);
  });

  it('allows editing an environment user and shows its source role', async () => {
    render(<UsersAdmin />);
    const group = await screen.findByRole('group', { name: 'usersAdmin.role env-user' });
    expect(within(group).getByRole('button', { name: 'usersAdmin.roles.admin' })).toBeTruthy();
    expect((within(group).getByRole('button', { name: 'usersAdmin.roles.operator' }) as HTMLButtonElement).disabled).toBe(false);
    // Scope to this row: the owner row shows the same note.
    expect(within(group.closest('tr') as HTMLElement).getByText('usersAdmin.fromConfiguration: usersAdmin.roles.admin')).toBeTruthy();
  });

  it('disables the current user even when the role comes from the database', async () => {
    mocks.listUsers.mockResolvedValueOnce({
      users: [{ username: 'current', role: 'admin', source: 'db', env_role: null, owner: false, locked: true }],
      candidates: [],
      me: { username: 'current', owner: false },
    });
    render(<UsersAdmin />);
    const group = await screen.findByRole('group', { name: 'usersAdmin.role current' });
    for (const chip of within(group).getAllByRole('button')) expect((chip as HTMLButtonElement).disabled).toBe(true);
  });

  it('deletes an environment user through the confirm step', async () => {
    mocks.removeUser.mockResolvedValue({ username: 'env-user', removed: false, blocked: true });
    render(<UsersAdmin />);
    const row = (await screen.findByText('env-user')).closest('tr') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'usersAdmin.remove' }));
    expect(await screen.findByText('usersAdmin.removeConfirm')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'usersAdmin.confirm' }));
    await waitFor(() => expect(mocks.removeUser).toHaveBeenCalledWith('env-user'));
  });

  it('offers no delete for the owner and saves a note on blur', async () => {
    mocks.updateUserNote.mockResolvedValue({ username: 'owner-user', note: 'boss' });
    render(<UsersAdmin />);
    const row = (await screen.findByText('owner-user')).closest('tr') as HTMLElement;
    expect(within(row).queryByRole('button', { name: 'usersAdmin.remove' })).toBeNull();
    const input = within(row).getByLabelText('usersAdmin.notes owner-user');
    fireEvent.change(input, { target: { value: 'boss' } });
    fireEvent.blur(input);
    await waitFor(() => expect(mocks.updateUserNote).toHaveBeenCalledWith('owner-user', 'boss'));
  });

  it('updates a database role and reloads the list', async () => {
    render(<UsersAdmin />);
    const group = await screen.findByRole('group', { name: 'usersAdmin.role db-user' });
    fireEvent.click(within(group).getByRole('button', { name: 'usersAdmin.roles.operator' }));
    await waitFor(() => expect(mocks.updateUserRole).toHaveBeenCalledWith('db-user', 'operator'));
    await waitFor(() => expect(mocks.listUsers).toHaveBeenCalledTimes(2));
  });

  it('shows the server error for a conflict', async () => {
    mocks.updateUserRole.mockRejectedValue({ response: { status: 409, data: { detail: 'locked by configuration' } } });
    render(<UsersAdmin />);
    const group = await screen.findByRole('group', { name: 'usersAdmin.role db-user' });
    fireEvent.click(within(group).getByRole('button', { name: 'usersAdmin.roles.operator' }));
    expect((await screen.findByRole('alert')).textContent).toContain('locked by configuration');
  });
});
