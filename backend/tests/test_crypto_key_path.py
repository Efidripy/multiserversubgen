import importlib
import os


def _key_file(monkeypatch, project_dir, existing):
    monkeypatch.setenv("PROJECT_DIR", project_dir)
    monkeypatch.setattr(os.path, "exists", lambda path: path in existing)
    import crypto

    try:
        return importlib.reload(crypto).KEY_FILE
    finally:
        monkeypatch.undo()
        importlib.reload(crypto)


def test_key_file_follows_project_dir(monkeypatch):
    assert _key_file(monkeypatch, "/opt/foo", set()) == os.path.join("/opt/foo", ".encryption_key")


def test_existing_legacy_key_is_kept_until_project_key_exists(monkeypatch):
    legacy = "/opt/sub-manager/.encryption_key"
    project = os.path.join("/opt/foo", ".encryption_key")
    assert _key_file(monkeypatch, "/opt/foo", {legacy}) == legacy
    assert _key_file(monkeypatch, "/opt/foo", {legacy, project}) == project
