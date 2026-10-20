from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
XUI_CORE = REPO / "scripts" / "installer" / "lib" / "xui_core.sh"


def test_xui_replacement_refuses_to_move_files_until_service_is_inactive():
    source = XUI_CORE.read_text(encoding="utf-8")

    assert "xui_stop_and_confirm_inactive()" in source
    assert 'if ! sudo systemctl stop x-ui; then' in source
    assert 'sudo systemctl is-active --quiet x-ui' in source
    assert "x-ui remains active after stop; replacement was not started." in source
    install_body = source.split("xui_install_binary() {", 1)[1]
    assert install_body.index("xui_stop_and_confirm_inactive") < install_body.index(
        'sudo mv /usr/local/x-ui "${rollback_dir}/x-ui"'
    )


def test_xui_replacement_keeps_a_full_rollback_anchor_and_does_not_ignore_migration_errors():
    source = XUI_CORE.read_text(encoding="utf-8")

    assert 'sudo cp -a /etc/x-ui "${rollback_dir}/etc-x-ui"' in source
    assert '! sudo x-ui migrate ||' in source
    assert 'xui_restore_binary_rollback "$rollback_dir" "$prior_xui_was_active"' in source
    assert 'sudo cp -a "${rollback_dir}/x-ui" /usr/local/x-ui' in source
    assert 'sudo cp -a "${rollback_dir}/etc-x-ui" /etc/x-ui' in source
    assert 'Recover manually from ${rollback_dir}' in source
