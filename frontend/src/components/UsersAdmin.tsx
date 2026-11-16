import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { deleteUserRole, listUsers, updateUserRole, type ManagedUser, type UserRole } from '../api/users';
import { SelectMenu } from './SelectMenu';

const shellClass = 'min-h-screen min-w-0 bg-[#0a0e1a] p-3 text-slate-100 sm:p-4 lg:p-6';
const panelClass = 'min-w-0 overflow-hidden rounded-lg border border-cyan-500/20 bg-[#0f1420] p-3 sm:p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04),0_18px_50px_rgba(0,0,0,0.18)]';
const buttonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-500/20 bg-[#0a0e1a] px-3 text-xs font-medium text-slate-300 transition hover:border-cyan-300/40 hover:text-cyan-100 disabled:cursor-not-allowed disabled:opacity-45';
const primaryButtonClass = 'inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-300 px-3 text-xs font-medium text-[#06111f] transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-45';
const roleOptions = (t: (key: string) => string) => (['viewer', 'operator', 'admin'] as UserRole[]).map((role) => ({
  value: role,
  label: t(`usersAdmin.roles.${role}`),
}));

function errorText(error: any, fallback: string): string {
  return error?.response?.data?.detail || error?.response?.data?.message || error?.message || fallback;
}

export interface UsersAdminProps {
  currentUser?: string;
}

export const UsersAdmin: React.FC<UsersAdminProps> = ({ currentUser = '' }) => {
  const { t } = useTranslation();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState('');
  const [success, setSuccess] = useState('');
  const [confirming, setConfirming] = useState<string | null>(null);
  const [candidate, setCandidate] = useState('');
  const [newRole, setNewRole] = useState<UserRole>('viewer');

  const load = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError('');
    try {
      const payload = await listUsers();
      setUsers(payload.users);
      setCandidates(payload.candidates);
      setCandidate((previous) => previous && payload.candidates.includes(previous) ? previous : (payload.candidates[0] || ''));
      return true;
    } catch (err: any) {
      setError(errorText(err, t('usersAdmin.loadError')));
      return false;
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, []);

  const roles = useMemo(() => roleOptions(t), [t]);

  const finishMutation = async (message: string) => {
    if (await load()) setSuccess(message);
  };

  const changeRole = async (username: string, role: UserRole) => {
    setSaving(username);
    setError('');
    setSuccess('');
    try {
      await updateUserRole(username, role);
      await finishMutation(t('usersAdmin.saved'));
    } catch (err: any) {
      setError(errorText(err, t('usersAdmin.saveError')));
    } finally {
      setSaving('');
    }
  };

  const removeRole = async (username: string) => {
    setSaving(username);
    setError('');
    setSuccess('');
    try {
      await deleteUserRole(username);
      setConfirming(null);
      await finishMutation(t('usersAdmin.removed'));
    } catch (err: any) {
      setError(errorText(err, t('usersAdmin.removeError')));
    } finally {
      setSaving('');
    }
  };

  const addAssignment = async () => {
    if (!candidate) return;
    await changeRole(candidate, newRole);
  };

  return (
    <div className={shellClass} data-ln="users">
      <div className="mx-auto max-w-6xl">
        <header className="mb-4">
          <h2 className="text-lg font-semibold tracking-tight text-slate-100">{t('usersAdmin.title')}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">{t('usersAdmin.hint')}</p>
        </header>

        {error && <div role="alert" className="mb-4 rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200">{error}</div>}
        {success && <div role="status" className="mb-4 rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-200">{success}</div>}

        <section className={`${panelClass} mb-4`}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('usersAdmin.listTitle')}</h3>
            {!loading && <span className="text-xs text-slate-500">{users.length}</span>}
          </div>
          {loading ? <p className="text-sm text-slate-400">{t('usersAdmin.loading')}</p> : users.length === 0 ? <p className="text-sm text-slate-400">{t('usersAdmin.empty')}</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] border-collapse text-left text-xs">
                <thead><tr className="border-b border-cyan-500/15 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="px-2 py-2 font-medium">{t('usersAdmin.username')}</th>
                  <th className="px-2 py-2 font-medium">{t('usersAdmin.role')}</th>
                  <th className="px-2 py-2 font-medium">{t('usersAdmin.source')}</th>
                  <th className="px-2 py-2 font-medium">{t('usersAdmin.notes')}</th>
                  <th className="px-2 py-2 font-medium">{t('usersAdmin.actions')}</th>
                </tr></thead>
                <tbody>
                  {users.map((item) => {
                    const locked = item.locked || item.username === currentUser;
                    return <tr key={item.username} className="border-b border-cyan-500/10 last:border-0">
                      <td className="px-2 py-3 font-mono text-slate-200">{item.username}</td>
                      <td className="w-44 px-2 py-3"><SelectMenu value={item.role} options={roles} ariaLabel={`${t('usersAdmin.role')} ${item.username}`} disabled={locked || saving === item.username} onChange={(value) => void changeRole(item.username, value as UserRole)} /></td>
                      <td className="px-2 py-3 text-slate-400">{t(`usersAdmin.sources.${item.source}`)}</td>
                      <td className="px-2 py-3 text-slate-400">{item.owner && <span className="mr-2">{t('usersAdmin.owner')}</span>}{item.locked && <span>{t('usersAdmin.locked')}</span>}{item.username === currentUser && <span>{t('usersAdmin.self')}</span>}{item.locked && <span className="ml-2 text-slate-500">{t('usersAdmin.serverConfigured')}</span>}</td>
                      <td className="px-2 py-3">{item.source === 'db' && !locked && (confirming === item.username ? <span className="flex flex-wrap items-center gap-2"><span className="text-slate-400">{t('usersAdmin.removeConfirm')}</span><button type="button" className={primaryButtonClass} disabled={saving === item.username} onClick={() => void removeRole(item.username)}>{t('usersAdmin.confirm')}</button><button type="button" className={buttonClass} onClick={() => setConfirming(null)}>{t('usersAdmin.cancel')}</button></span> : <button type="button" className={buttonClass} disabled={saving === item.username} onClick={() => setConfirming(item.username)}>{t('usersAdmin.remove')}</button>)}</td>
                    </tr>;
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className={panelClass}>
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-slate-300">{t('usersAdmin.addTitle')}</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">{t('usersAdmin.addHint')}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,180px)_auto] sm:items-end">
            <label className="text-xs text-slate-400">{t('usersAdmin.candidate')}<span className="mt-1 block"><SelectMenu value={candidate} options={candidates.map((value) => ({ value, label: value }))} ariaLabel={t('usersAdmin.candidate')} onChange={(value) => setCandidate(String(value))} /></span></label>
            <label className="text-xs text-slate-400">{t('usersAdmin.role')}<span className="mt-1 block"><SelectMenu value={newRole} options={roles} ariaLabel={t('usersAdmin.role')} onChange={(value) => setNewRole(value as UserRole)} /></span></label>
            <button type="button" className={primaryButtonClass} disabled={!candidate || Boolean(saving)} onClick={() => void addAssignment()}>{t('usersAdmin.add')}</button>
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">{t('usersAdmin.linuxHint')}</p>
        </section>
      </div>
    </div>
  );
};

export default UsersAdmin;
