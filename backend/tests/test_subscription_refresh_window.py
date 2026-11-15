from services.subscription_links import SubscriptionRefreshWindow


def test_window_invalidates_on_open_and_on_snapshots_until_it_closes():
    calls = []
    now = [100.0]
    window = SubscriptionRefreshWindow(lambda: calls.append(now[0]), window_sec=60, clock=lambda: now[0])

    window.on_snapshots()
    assert calls == []  # closed: ordinary polls must not defeat the response cache

    window.open()
    now[0] = 130.0
    window.on_snapshots()
    now[0] = 161.0
    window.on_snapshots()
    assert calls == [100.0, 130.0]
