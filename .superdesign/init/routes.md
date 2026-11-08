# Routes

No router. Single page; `App.tsx` keeps `activeTab` state (persisted in localStorage) and `renderTabContent` switches on it. Unauthenticated users see the login screen in `App.tsx`.

| Tab id | Component | Role |
|---|---|---|
| dashboard | DashboardSummary + NodeManager + ServerStatus + RegisteredFleetPanel | any |
| inbounds | InboundManager (lazy) | any |
| clients | ClientManager (lazy) | any |
| traffic | TrafficStats | any |
| monitoring | MonitoringDashboard | any |
| backup | BackupManager | admin |
| subscriptions | SubscriptionManager | admin |
| telegram | TelegramAdmin | admin |

Layout for every tab: App shell (see layouts.md).

```tsx

  const renderTabContent = (tab: TabType) => {
    switch (tab) {
      case 'dashboard':
        return (
          <DashboardDataProvider>
          <DashboardPullRefreshRegistration onRegister={registerDashboardRefresh}>
          <div className="dashboard-command-grid min-w-0 overflow-hidden p-3 sm:p-4 lg:p-6 min-h-screen transition-all duration-300 ease-in-out xl:grid xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start xl:gap-6">
            <div className="dashboard-command-grid__main min-w-0 overflow-hidden">
              <DashboardSummary onNavigate={(tab) => {
                const t = tab as TabType;
                if (t in TAB_META) {
                  setActiveTab(t);
                }
              }}
              onOnlineClientsChange={handleOnlineClientsChange}
              fleetSummary={fleetSummary}
              />
              <section className="mb-6 rounded-lg border border-cyan-500/20 bg-[#0f1420] p-4 shadow-[inset_0_1px_0_rgba(148,163,184,0.04)]">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">{t('nodes.intakeTitle').toUpperCase()}</h3>
                    <p className="mt-1 text-[10px] font-light leading-4 text-slate-500">{t('nodes.intakeHint')}</p>
                  </div>
                  <button
                    className="flex items-center gap-1 rounded-md border border-cyan-300/25 bg-gradient-to-r from-cyan-400/90 to-fuchsia-400/90 px-3 py-1.5 text-xs font-medium tracking-wide text-white shadow-[0_10px_24px_rgba(34,211,238,0.16)]"
                    type="button"
                    onClick={() => setNodeIntakeOpenSignal((value) => value + 1)}
                  >
                    {`+ ${t('nodes.addNode')}`}
                  </button>
                </div>
              </section>
              <NodeManager
                onReload={() => setKey((prev) => prev + 1)}
                showIntake={false}
                openIntakeSignal={nodeIntakeOpenSignal}
                editNode={nodeEditTarget}
                openEditSignal={nodeEditOpenSignal}
              />
              <section className="dashboard-server-deck min-w-0">
                <ServerStatus
                  fleetSummary={fleetSummary}
                  fleetCollapsed={registeredFleetCollapsed}
                  onToggleFleet={() => setRegisteredFleetCollapsed((value) => !value)}
                />
              </section>
            </div>
            <RegisteredFleetPanel
              collapsed={registeredFleetCollapsed}
              setCollapsed={setRegisteredFleetCollapsed}
              canManageTelegram={role === 'admin'}
              onSummaryChange={handleFleetSummaryChange}
              onOpenNodes={() => {
                setNodeIntakeOpenSignal((value) => value + 1);
                setRegisteredFleetCollapsed(true);
              }}
              onEditNode={(node) => {
                setNodeEditTarget(node);
                setNodeEditOpenSignal((value) => value + 1);
                setRegisteredFleetCollapsed(true);
              }}
            />
          </div>
          </DashboardPullRefreshRegistration>
          </DashboardDataProvider>
        );
      case 'inbounds':
        return <LazyInboundManager
          onReload={() => setKey((prev) => prev + 1)}
          onNavigateToClients={(inboundId, inboundRemark) => {
            try { sessionStorage.setItem('sm_nav_inbound_filter', JSON.stringify({ id: inboundId, remark: inboundRemark })); } catch {}
            setActiveTab('clients');
          }}
          onAddClientToInbound={(inboundId, _nodeName) => {
            try { sessionStorage.setItem('sm_nav_add_to_inbound', String(inboundId)); } catch {}
            setActiveTab('clients');
          }}
        />;
      case 'clients':
        return <LazyClientManager />;
      case 'traffic':
        return <LazyTrafficStats onNavigateToClient={(email) => {
          try { sessionStorage.setItem('sm_nav_client_search', email); } catch {}
          setActiveTab('clients');
        }} />;
      case 'monitoring':
        return <LazyMonitoringDashboard onHeaderProjectionChange={(projection: MonitoringHeaderProjection) => {
          updateHeaderSummary({
            description: t('header.monitoring.description'),
            stats: [
              { label: t('header.monitoring.stackProbes'), value: `${projection.servicesUp}/${projection.servicesTotal}`, tone: projection.servicesUp === projection.servicesTotal && projection.servicesTotal > 0 ? 'success' : 'warning' },
              { label: t('header.monitoring.adguardSources'), value: `${projection.sourcesOnline}/${projection.sourcesTotal}`, tone: projection.sourcesOnline > 0 ? 'success' : 'warning' },
              { label: t('header.monitoring.blockedRate'), value: formatPercent(projection.blockedRate), tone: 'accent' },
              { label: t('header.monitoring.collector'), value: projection.collectorRunning ? t('header.monitoring.collectorRunning') : t('header.monitoring.collectorIdle'), tone: projection.collectorRunning ? 'success' : 'warning' },
            ],
          });
        }} />;
      case 'backup':
        return <LazyBackupManager onHeaderProjectionChange={(projection: BackupHeaderProjection) => {
          updateHeaderSummary({
            description: t('header.backup.description'),
            stats: [
              { label: t('header.backup.knownNodes'), value: String(projection.knownNodes) },
              { label: t('header.backup.writable'), value: String(projection.writableNodes), tone: projection.writableNodes > 0 ? 'success' : 'warning' },
              { label: t('header.backup.readOnly'), value: String(projection.readOnlyNodes) },
              { label: t('header.backup.restoreTargets'), value: String(projection.restoreTargets) },
            ],
          });
        }} />;
      case 'subscriptions':
        return <LazySubscriptionManager
          key={key}
          apiUrl={getApiUrl()}
          onHeaderProjectionChange={handleSubscriptionsHeaderProjection}
        />;
      case 'telegram':
        return <LazyTelegramAdmin />;
      default:
        return null;
    }
  };

  const levelColor = (level: NoticeLevel) => {
    if (level === 'success') return colors.success;
    if (level === 'warning') return colors.warning;
    if (level === 'danger') return colors.danger;
    return colors.info;
```
