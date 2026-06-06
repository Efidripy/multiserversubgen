#!/usr/bin/env python3
"""Deploy a pre-built backend+frontend to vm2.kleva.ru cleanly."""
import paramiko, tarfile, os, io, sys

REPO = r'E:\GitHub\repos\multiserversubgen'
BACKEND = os.path.join(REPO, 'backend')
LABEL = sys.argv[1] if len(sys.argv) > 1 else 'unknown'

print(f"[deploy] Building tarball for slice: {LABEL}")

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    for root, dirs, files in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in ('venv', '__pycache__', '.git', 'node_modules')]
        for f in files:
            fp = os.path.join(root, f)
            arcname = os.path.relpath(fp, BACKEND)
            tar.add(fp, arcname=arcname)
buf.seek(0)
size_mb = buf.getbuffer().nbytes / 1024 / 1024
print(f"[deploy] Tarball size: {size_mb:.1f} MB")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('vm2.kleva.ru', port=22, username='vm2', password='6661313', timeout=30)

print("[deploy] Uploading tarball...")
sftp = client.open_sftp()
sftp.putfo(buf, '/var/tmp/deploy.tar.gz')
sftp.close()
print("[deploy] Upload done")

CLEAN_SCRIPT = r"""#!/bin/bash
set -e
echo "[server] Stopping service..."
systemctl stop sub-manager

echo "[server] Backing up DB and key..."
cp /opt/sub-manager/admin.db /var/tmp/admin.db.bak
cp /opt/sub-manager/admin.db-wal /var/tmp/ 2>/dev/null || true
cp /opt/sub-manager/admin.db-shm /var/tmp/ 2>/dev/null || true
cp /opt/sub-manager/.encryption_key /var/tmp/.enc_key.bak 2>/dev/null || true
cp -r /opt/sub-manager/config /var/tmp/sm-config-bak

echo "[server] Wiping project dir..."
find /opt/sub-manager -mindepth 1 -maxdepth 1 \
  -not -name venv \
  -not -name logs \
  -exec rm -rf {} +

echo "[server] Restoring DB and config..."
cp /var/tmp/admin.db.bak /opt/sub-manager/admin.db
cp /var/tmp/admin.db-wal /opt/sub-manager/ 2>/dev/null || true
cp /var/tmp/admin.db-shm /opt/sub-manager/ 2>/dev/null || true
cp /var/tmp/.enc_key.bak /opt/sub-manager/.encryption_key 2>/dev/null || true
cp -r /var/tmp/sm-config-bak /opt/sub-manager/config

echo "[server] Extracting new build..."
tar -xzf /var/tmp/deploy.tar.gz -C /opt/sub-manager/

echo "[server] Installing Python deps..."
/opt/sub-manager/venv/bin/pip install -q -r /opt/sub-manager/requirements.txt 2>&1 | tail -5

echo "[server] Starting service..."
systemctl start sub-manager
sleep 3
STATUS=$(systemctl is-active sub-manager)
echo "[server] Service status: $STATUS"
echo "DEPLOY_OK:$STATUS"
"""

sftp = client.open_sftp()
sftp.putfo(io.BytesIO(CLEAN_SCRIPT.encode()), '/var/tmp/clean_deploy.sh')
sftp.close()

print("[deploy] Running clean install on server...")
_, out, err = client.exec_command('echo "6661313" | sudo -S bash /var/tmp/clean_deploy.sh', timeout=180)
for line in out:
    print(line.rstrip())
stderr = err.read().decode().strip()
if stderr:
    print("[STDERR]", stderr[:500])

client.close()
print(f"[deploy] Done: slice {LABEL}")
