import importlib.util
import json
import socket
import sys
import threading
import types
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sub_manager_pam", REPO / "scripts/pam/sub_manager_pam.py")
PAM = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PAM)


def response(payload, peer=1000, expected=1000, result=True):
    return json.loads(
        PAM.authenticate_request(
            payload,
            peer_uid=peer,
            expected_uid=expected,
            pam_authenticate=lambda _user, _password: result,
        )
    )


def test_helper_protocol_validation_and_peer_check():
    assert response(b'{"user":"alice","password":"secret"}\n') == {"ok": True}
    assert response(b'{"user":"alice","password":"secret"}\n', result=False) == {"ok": False}
    assert response(b'{"user":"alice","password":"secret"}', result=True) == {"ok": False}
    assert response(b"garbage\n") == {"ok": False}
    assert response(b'{"user":"alice\\u0000","password":"secret"}\n') == {"ok": False}
    assert response(b'{"user":"alice","password":"secret"}\n', peer=1001) == {"ok": False}
    assert response(b"x" * (PAM.MAX_REQUEST + 1)) == {"ok": False}


def test_auth_service_uses_socket_and_fails_closed(monkeypatch, tmp_path):
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("AF_UNIX is required")
    sys.path.insert(0, str(REPO / "backend"))
    from modules.auth.service import AuthService

    path = tmp_path / "pam.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            assert json.loads(conn.recv(4096).decode())["user"] == "alice"
            conn.sendall(b'{"ok":true}\n')

    thread = threading.Thread(target=serve)
    thread.start()
    monkeypatch.setenv("PAM_HELPER_SOCKET", str(path))
    assert AuthService().authenticate("alice", "secret") is True
    thread.join(timeout=2)
    server.close()

    monkeypatch.setenv("PAM_HELPER_SOCKET", str(tmp_path / "missing"))
    assert AuthService().authenticate("alice", "secret") is False


def test_auth_service_keeps_local_pam_path_when_helper_is_unset(monkeypatch):
    from modules.auth.service import AuthService

    class FakePam:
        def authenticate(self, _user, _password):
            return True

    monkeypatch.delenv("PAM_HELPER_SOCKET", raising=False)
    monkeypatch.setitem(sys.modules, "pam", types.SimpleNamespace(pam=FakePam))
    assert AuthService().authenticate("local-only-user", "secret") is True


def test_units_and_installation_paths_are_hardened():
    service = (REPO / "systemd/sub-manager.service").read_text(encoding="utf-8")
    helper_service = (REPO / "systemd/sub-manager-pam@.service").read_text(encoding="utf-8")
    helper_socket = (REPO / "systemd/sub-manager-pam.socket").read_text(encoding="utf-8")
    assert "SupplementaryGroups=shadow" not in service
    assert "NoNewPrivileges=yes" in helper_service
    assert "RestrictAddressFamilies=AF_UNIX" in helper_service
    assert "SocketMode=0660" in helper_socket
    assert "/usr/local/lib/sub-manager-pam" in helper_service
    for script in ("scripts/installer/install.sh", "scripts/installer/update.sh", "scripts/deploy/server-deploy.sh"):
        text = (REPO / script).read_text(encoding="utf-8")
        assert "pam_helper_install" in text
        assert "/opt/sub-manager" not in text[text.find("pam_helper_install") : text.find("pam_helper_install") + 300]


def test_diag_request_reports_pam_status_only_for_the_service_uid():
    payload = b'{"user":"svc","password":"x","diag":true}\n'

    def run(peer, status):
        return json.loads(
            PAM.authenticate_request(
                payload,
                peer_uid=peer,
                expected_uid=1000,
                pam_authenticate=lambda _u, _p: False,
                pam_status=lambda _u, _p: status,
            )
        )

    assert run(1000, 7) == {"ok": False, "pam": 7}
    assert run(1001, 7) == {"ok": False}
    # A diag flag without a status callback never reaches the plain authenticator.
    assert json.loads(PAM.authenticate_request(payload, peer_uid=1000, expected_uid=1000, pam_authenticate=lambda _u, _p: True)) == {"ok": False}
    assert PAM.SELF_CHECK_OK_STATUSES == {7, 10}
