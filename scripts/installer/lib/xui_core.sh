#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/locale.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/artifact_manifest.sh"

xui_arch() {
    case "$(uname -m)" in
        x86_64|x64|amd64) printf 'amd64' ;;
        i*86|x86) printf '386' ;;
        armv8*|armv8|arm64|aarch64) printf 'arm64' ;;
        armv7*|armv7|arm) printf 'armv7' ;;
        armv6*|armv6) printf 'armv6' ;;
        armv5*|armv5) printf 'armv5' ;;
        s390x) printf 's390x' ;;
        *) return 1 ;;
    esac
}

xui_random_token() {
    local length="${1:-10}"
    python3 - "$length" <<'PY'
import secrets
import string
import sys

length = int(sys.argv[1])
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(length)))
PY
}

xui_random_group_id() {
    python3 - <<'PY'
import secrets
import string

print(''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16)))
PY
}

xui_pick_release_tag() {
    printf "%s" "$ARTIFACT_XUI_VERSION"
}

xui_download_release() {
    local target_archive="$1"
    local tag="$2"
    local arch

    arch="$(xui_arch)" || return 1
    local asset="x-ui-linux-${arch}.tar.gz"
    curl -fsSL "https://github.com/MHSanaei/3x-ui/releases/download/${tag}/${asset}" -o "$target_archive"
    [[ "$tag" == "$ARTIFACT_XUI_VERSION" ]] && artifact_verify_file XUI "$arch" "$target_archive" || {
        echo "XUI archive digest verification failed." >&2
        return 1
    }
}

xui_seed_nginx_bootstrap_files() {
    sudo mkdir -p /etc/nginx/conf.d /etc/nginx/modules-enabled /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/snippets /etc/nginx/stream-enabled
    if [ ! -f /etc/nginx/nginx.conf ]; then
        sudo tee /etc/nginx/nginx.conf >/dev/null <<'EOF'
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 1024;
}

http {
    sendfile on;
    tcp_nopush on;
    types_hash_max_size 2048;
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
    gzip on;
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOF
    fi
}

xui_ensure_system_prerequisites() {
    sudo apt-get update -y >/dev/null
    xui_seed_nginx_bootstrap_files
    if ! sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
        -o Dpkg::Options::="--force-confold" \
        wget \
        curl \
        tar \
        tzdata \
        nginx \
        libnginx-mod-stream \
        openssl \
        sqlite3 \
        fail2ban \
        certbot \
        python3-certbot-nginx >/dev/null; then
        sudo DEBIAN_FRONTEND=noninteractive dpkg --force-confold --configure -a >/dev/null 2>&1 || true
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -f -y -o Dpkg::Options::="--force-confold" >/dev/null 2>&1 || true
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
            -o Dpkg::Options::="--force-confold" \
            wget \
            curl \
            tar \
            tzdata \
            nginx \
            libnginx-mod-stream \
            openssl \
            sqlite3 \
            fail2ban \
            certbot \
            python3-certbot-nginx >/dev/null
    fi
    sudo DEBIAN_FRONTEND=noninteractive dpkg --force-confold --configure -a >/dev/null 2>&1 || true
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -f -y -o Dpkg::Options::="--force-confold" >/dev/null 2>&1 || true

    if [ ! -f /etc/nginx/nginx.conf ]; then
        xui_seed_nginx_bootstrap_files
        sudo DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y -q \
            -o Dpkg::Options::="--force-confold" \
            nginx nginx-common libnginx-mod-stream >/dev/null
    fi

    xui_ensure_nginx_base_config
}

xui_ensure_nginx_base_config() {
    sudo mkdir -p /etc/nginx/conf.d /etc/nginx/modules-enabled /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/snippets /etc/nginx/stream-enabled
    if [ ! -f /etc/nginx/nginx.conf ]; then
        sudo tee /etc/nginx/nginx.conf >/dev/null <<'EOF'
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 1024;
}

http {
    sendfile on;
    tcp_nopush on;
    types_hash_max_size 2048;
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
    gzip on;
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOF
    fi
}

xui_install_binary() {
    local tag="$1"
    local workdir
    local archive
    local arch
    local staged_dir
    local rollback_root
    local rollback_dir
    local previous_cli=""
    local previous_unit=""
    local stamp

    arch="$(xui_arch)" || {
        echo "Unsupported CPU architecture for x-ui" >&2
        return 1
    }

    workdir="$(mktemp -d)"
    archive="${workdir}/x-ui-linux-${arch}.tar.gz"

    xui_ensure_system_prerequisites

    xui_download_release "$archive" "$tag" || { rm -rf "$workdir"; return 1; }

    staged_dir="${workdir}/x-ui"
    if ! sudo tar -xzf "$archive" -C "$workdir"; then
        echo "Failed to unpack verified 3x-ui archive." >&2
        rm -rf "$workdir"
        return 1
    fi
    [ -x "${staged_dir}/x-ui" ] || {
        echo "Downloaded 3x-ui archive has no executable x-ui binary." >&2
        rm -rf "$workdir"
        return 1
    }
    [ -f "${staged_dir}/x-ui.service.debian" ] || {
        echo "Downloaded 3x-ui archive has no Debian systemd unit." >&2
        rm -rf "$workdir"
        return 1
    }
    sudo chmod +x "${staged_dir}/x-ui" "${staged_dir}/x-ui.sh"

    if [[ "$arch" == armv5 || "$arch" == armv6 || "$arch" == armv7 ]]; then
        sudo mv "${staged_dir}/bin/xray-linux-${arch}" "${staged_dir}/bin/xray-linux-arm"
        sudo chmod +x "${staged_dir}/bin/xray-linux-arm"
    elif [ -f "${staged_dir}/bin/xray-linux-${arch}" ]; then
        sudo chmod +x "${staged_dir}/bin/xray-linux-${arch}"
    fi

    sudo mkdir -p /usr/local
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    rollback_root="/var/backups/multiserversubgen/x-ui"
    rollback_dir="${rollback_root}/${stamp}"
    sudo install -d -m 0700 "$rollback_dir"
    if [ -d /usr/local/x-ui ]; then
        sudo systemctl stop x-ui >/dev/null 2>&1 || true
        sudo mv /usr/local/x-ui "${rollback_dir}/x-ui"
    fi
    if [ -f /usr/bin/x-ui ]; then
        previous_cli="${rollback_dir}/x-ui-cli"
        sudo cp -p /usr/bin/x-ui "$previous_cli"
    fi
    if [ -f /etc/systemd/system/x-ui.service ]; then
        previous_unit="${rollback_dir}/x-ui.service"
        sudo cp -p /etc/systemd/system/x-ui.service "$previous_unit"
    fi
    sudo mv "$staged_dir" /usr/local/x-ui
    sudo install -m 0755 /usr/local/x-ui/x-ui.sh /usr/bin/x-ui

    if [ -f /usr/local/x-ui/x-ui.service.debian ]; then
        sudo cp -f /usr/local/x-ui/x-ui.service.debian /etc/systemd/system/x-ui.service
    fi

    sudo systemctl daemon-reload
    sudo systemctl enable x-ui >/dev/null
    if ! sudo systemctl start x-ui; then
        echo "3x-ui service failed after update; restoring rollback ${rollback_dir}." >&2
        sudo systemctl stop x-ui >/dev/null 2>&1 || true
        sudo rm -rf /usr/local/x-ui
        if [ -d "${rollback_dir}/x-ui" ]; then sudo mv "${rollback_dir}/x-ui" /usr/local/x-ui; fi
        if [ -n "$previous_cli" ] && [ -f "$previous_cli" ]; then sudo install -m 0755 "$previous_cli" /usr/bin/x-ui; fi
        if [ -n "$previous_unit" ] && [ -f "$previous_unit" ]; then sudo install -m 0644 "$previous_unit" /etc/systemd/system/x-ui.service; fi
        sudo systemctl daemon-reload
        sudo systemctl start x-ui >/dev/null 2>&1 || true
        rm -rf "$workdir"
        return 1
    fi
    sudo x-ui migrate >/dev/null 2>&1 || true

    rm -rf "$workdir"
}

xui_generate_panel_settings() {
    PROFILE_XUI_PANEL_PORT="${PROFILE_XUI_PANEL_PORT:-$(shuf -i 20000-49000 -n 1)}"
    PROFILE_XUI_PANEL_PATH="${PROFILE_XUI_PANEL_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_USERNAME="${PROFILE_XUI_USERNAME:-$(xui_random_token 10)}"
    PROFILE_XUI_PASSWORD="${PROFILE_XUI_PASSWORD:-$(xui_random_token 14)}"
    PROFILE_XUI_GENERATED_USERNAME="${PROFILE_XUI_USERNAME}"
    PROFILE_XUI_GENERATED_PASSWORD="${PROFILE_XUI_PASSWORD}"
    if declare -F report_capture_xui_runtime >/dev/null 2>&1; then
        report_capture_xui_runtime
    fi
}

xui_configure_panel() {
    local domain="$1"
    local cert_file="$2"
    local cert_key="$3"

    xui_generate_panel_settings

    sudo /usr/local/x-ui/x-ui setting \
        -username "${PROFILE_XUI_USERNAME}" \
        -password "${PROFILE_XUI_PASSWORD}" \
        -port "${PROFILE_XUI_PANEL_PORT}" \
        -webBasePath "${PROFILE_XUI_PANEL_PATH}" >/dev/null

    if [ -n "$cert_file" ] && [ -n "$cert_key" ] && [ -f "$cert_file" ] && [ -f "$cert_key" ]; then
        sudo /usr/local/x-ui/x-ui cert -webCert "$cert_file" -webCertKey "$cert_key" >/dev/null
    fi

    sudo systemctl restart x-ui
    PROFILE_XUI_PANEL_URL="https://${domain}/${PROFILE_XUI_PANEL_PATH}/"
}

xui_generate_seed_context() {
    local domain="$1"
    local reality_domain="$2"
    local xray_bin="/usr/local/x-ui/bin/xray-linux-$(xui_arch)"

    [ -x "$xray_bin" ] || xray_bin="/usr/local/x-ui/bin/xray-linux-arm"

    PROFILE_XUI_SUB_PORT="${PROFILE_XUI_SUB_PORT:-$(shuf -i 20000-49000 -n 1)}"
    PROFILE_XUI_WS_PORT="${PROFILE_XUI_WS_PORT:-$(shuf -i 20000-49000 -n 1)}"
    PROFILE_XUI_TROJAN_PORT="${PROFILE_XUI_TROJAN_PORT:-$(shuf -i 20000-49000 -n 1)}"
    PROFILE_XUI_SUB2SING_PORT="${PROFILE_XUI_SUB2SING_PORT:-8080}"
    PROFILE_XUI_SUB_PATH="${PROFILE_XUI_SUB_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_JSON_PATH="${PROFILE_XUI_JSON_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_WEB_PATH="${PROFILE_XUI_WEB_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_SUB2SING_PATH="${PROFILE_XUI_SUB2SING_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_WS_PATH="${PROFILE_XUI_WS_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_TROJAN_PATH="${PROFILE_XUI_TROJAN_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_XHTTP_PATH="${PROFILE_XUI_XHTTP_PATH:-$(xui_random_token 10)}"

    PROFILE_XUI_UUID_REALITY="$("$xray_bin" uuid)"
    PROFILE_XUI_UUID_WS="$("$xray_bin" uuid)"
    PROFILE_XUI_UUID_XHTTP="$("$xray_bin" uuid)"
    # 3x-ui v3.5+ requires a 16-character lowercase-alphanumeric group_id for
    # editable host rows. Keep each seeded inbound in its own host group.
    PROFILE_XUI_GROUP_REALITY="$(xui_random_group_id)"
    PROFILE_XUI_GROUP_WS="$(xui_random_group_id)"
    PROFILE_XUI_GROUP_XHTTP="$(xui_random_group_id)"
    PROFILE_XUI_GROUP_TROJAN="$(xui_random_group_id)"
    PROFILE_XUI_TROJAN_PASS="$(xui_random_token 10)"
    local x25519_output
    x25519_output="$("$xray_bin" x25519)"
    PROFILE_XUI_PRIVATE_KEY="$(printf "%s\n" "$x25519_output" | awk '/PrivateKey:/ {print $2}')"
    PROFILE_XUI_PUBLIC_KEY="$(printf "%s\n" "$x25519_output" | awk '/PublicKey:/ {print $2}')"
    if [ -z "$PROFILE_XUI_PUBLIC_KEY" ]; then
        PROFILE_XUI_PUBLIC_KEY="$(printf "%s\n" "$x25519_output" | awk '/Password:/ {print $2}')"
    fi

    local short_ids=()
    local idx
    for idx in 1 2 3 4 5 6 7 8; do
        short_ids+=("$(openssl rand -hex 8)")
    done
    PROFILE_XUI_SHORT_IDS="$(IFS=,; printf "%s" "${short_ids[*]}")"
    PROFILE_XUI_DOMAIN="$domain"
    PROFILE_XUI_REALITY_DOMAIN="$reality_domain"
    PROFILE_XUI_WEBSUB_URL="https://${PROFILE_XUI_DOMAIN}/${PROFILE_XUI_WEB_PATH}?name=first"
    PROFILE_XUI_SUB2SING_URL="https://${PROFILE_XUI_DOMAIN}/${PROFILE_XUI_SUB2SING_PATH}/"
}

xui_seed_base_inbounds() {
    local domain="$1"
    local reality_domain="$2"
    local template_path="${REPO_ROOT}/scripts/installer/templates/xui-pro/base-inbounds.sql.tpl"
    local sql_file

    [ -f "$template_path" ] || {
        echo "Missing x-ui seed template: $template_path" >&2
        return 1
    }

    if [ -z "${PROFILE_XUI_DOMAIN:-}" ] || [ -z "${PROFILE_XUI_REALITY_DOMAIN:-}" ] || [ -z "${PROFILE_XUI_SUB_PATH:-}" ]; then
        xui_generate_seed_context "$domain" "$reality_domain"
    fi
    if [ ! -f /etc/x-ui/x-ui.db ]; then
        echo "3x-ui database was not created before seed configuration." >&2
        return 1
    fi
    if ! sudo sqlite3 /etc/x-ui/x-ui.db "SELECT 1 FROM pragma_table_info('hosts') WHERE name='group_id' LIMIT 1;" | grep -qx '1'; then
        echo "3x-ui v3.5+ hosts/group_id schema is missing after migration." >&2
        return 1
    fi
    sql_file="$(mktemp)"

    env \
        PROFILE_XUI_DOMAIN="${PROFILE_XUI_DOMAIN}" \
        PROFILE_XUI_REALITY_DOMAIN="${PROFILE_XUI_REALITY_DOMAIN}" \
        PROFILE_XUI_SUB_PORT="${PROFILE_XUI_SUB_PORT}" \
        PROFILE_XUI_SUB_PATH="${PROFILE_XUI_SUB_PATH}" \
        PROFILE_XUI_JSON_PATH="${PROFILE_XUI_JSON_PATH}" \
        PROFILE_XUI_WEB_PATH="${PROFILE_XUI_WEB_PATH}" \
        PROFILE_XUI_WS_PORT="${PROFILE_XUI_WS_PORT}" \
        PROFILE_XUI_WS_PATH="${PROFILE_XUI_WS_PATH}" \
        PROFILE_XUI_TROJAN_PORT="${PROFILE_XUI_TROJAN_PORT}" \
        PROFILE_XUI_TROJAN_PATH="${PROFILE_XUI_TROJAN_PATH}" \
        PROFILE_XUI_XHTTP_PATH="${PROFILE_XUI_XHTTP_PATH}" \
        PROFILE_XUI_UUID_REALITY="${PROFILE_XUI_UUID_REALITY}" \
        PROFILE_XUI_UUID_WS="${PROFILE_XUI_UUID_WS}" \
        PROFILE_XUI_UUID_XHTTP="${PROFILE_XUI_UUID_XHTTP}" \
        PROFILE_XUI_GROUP_REALITY="${PROFILE_XUI_GROUP_REALITY}" \
        PROFILE_XUI_GROUP_WS="${PROFILE_XUI_GROUP_WS}" \
        PROFILE_XUI_GROUP_XHTTP="${PROFILE_XUI_GROUP_XHTTP}" \
        PROFILE_XUI_GROUP_TROJAN="${PROFILE_XUI_GROUP_TROJAN}" \
        PROFILE_XUI_TROJAN_PASS="${PROFILE_XUI_TROJAN_PASS}" \
        PROFILE_XUI_PRIVATE_KEY="${PROFILE_XUI_PRIVATE_KEY}" \
        PROFILE_XUI_PUBLIC_KEY="${PROFILE_XUI_PUBLIC_KEY}" \
        PROFILE_XUI_SHORT_IDS="${PROFILE_XUI_SHORT_IDS}" \
        python3 - "$template_path" "$sql_file" <<'PY'
from pathlib import Path
import json
import os
import sys

template = Path(sys.argv[1]).read_text()
target = Path(sys.argv[2])

short_ids = os.environ["PROFILE_XUI_SHORT_IDS"].split(",")
replacements = {
    "DOMAIN": os.environ["PROFILE_XUI_DOMAIN"],
    "REALITY_DOMAIN": os.environ["PROFILE_XUI_REALITY_DOMAIN"],
    "SUB_PORT": os.environ["PROFILE_XUI_SUB_PORT"],
    "SUB_PATH": os.environ["PROFILE_XUI_SUB_PATH"],
    "SUB_URI": f"https://{os.environ['PROFILE_XUI_DOMAIN']}/{os.environ['PROFILE_XUI_SUB_PATH']}/",
    "JSON_PATH": os.environ["PROFILE_XUI_JSON_PATH"],
    "JSON_URI": f"https://{os.environ['PROFILE_XUI_DOMAIN']}/{os.environ['PROFILE_XUI_WEB_PATH']}?name=",
    "WS_PORT": os.environ["PROFILE_XUI_WS_PORT"],
    "WS_PATH": os.environ["PROFILE_XUI_WS_PATH"],
    "TROJAN_PORT": os.environ["PROFILE_XUI_TROJAN_PORT"],
    "TROJAN_PATH": os.environ["PROFILE_XUI_TROJAN_PATH"],
    "XHTTP_PATH": os.environ["PROFILE_XUI_XHTTP_PATH"],
    "UUID_REALITY": os.environ["PROFILE_XUI_UUID_REALITY"],
    "UUID_WS": os.environ["PROFILE_XUI_UUID_WS"],
    "UUID_XHTTP": os.environ["PROFILE_XUI_UUID_XHTTP"],
    "GROUP_REALITY": os.environ["PROFILE_XUI_GROUP_REALITY"],
    "GROUP_WS": os.environ["PROFILE_XUI_GROUP_WS"],
    "GROUP_XHTTP": os.environ["PROFILE_XUI_GROUP_XHTTP"],
    "GROUP_TROJAN": os.environ["PROFILE_XUI_GROUP_TROJAN"],
    "TROJAN_PASS": os.environ["PROFILE_XUI_TROJAN_PASS"],
    "PRIVATE_KEY": os.environ["PROFILE_XUI_PRIVATE_KEY"],
    "PUBLIC_KEY": os.environ["PROFILE_XUI_PUBLIC_KEY"],
    "SHORT_IDS_JSON": json.dumps(short_ids),
}

for key, value in replacements.items():
    template = template.replace(f"__{key}__", value)

target.write_text(template)
PY

    sudo sqlite3 /etc/x-ui/x-ui.db < "$sql_file"
    rm -f "$sql_file"
    sudo systemctl restart x-ui
}

xui_collect_summary() {
    PROFILE_XUI_STATUS="$(systemctl is-active x-ui 2>/dev/null || true)"
    if [ -z "${PROFILE_XUI_PANEL_URL:-}" ] && [ -n "${PROFILE_XUI_DOMAIN:-}" ] && [ -n "${PROFILE_XUI_PANEL_PATH:-}" ]; then
        PROFILE_XUI_PANEL_URL="https://${PROFILE_XUI_DOMAIN}/${PROFILE_XUI_PANEL_PATH}/"
    fi
    if [ -z "${PROFILE_XUI_WEBSUB_URL:-}" ] && [ -n "${PROFILE_XUI_DOMAIN:-}" ] && [ -n "${PROFILE_XUI_WEB_PATH:-}" ]; then
        PROFILE_XUI_WEBSUB_URL="https://${PROFILE_XUI_DOMAIN}/${PROFILE_XUI_WEB_PATH}?name=first"
    fi
    if [ -z "${PROFILE_XUI_SUB2SING_URL:-}" ] && [ -n "${PROFILE_XUI_DOMAIN:-}" ] && [ -n "${PROFILE_XUI_SUB2SING_PATH:-}" ]; then
        PROFILE_XUI_SUB2SING_URL="https://${PROFILE_XUI_DOMAIN}/${PROFILE_XUI_SUB2SING_PATH}/"
    fi
    PROFILE_XUI_SUB2SING_STATUS="$(systemctl is-active sub2sing-box 2>/dev/null || true)"
    if declare -F report_capture_xui_runtime >/dev/null 2>&1; then
        report_capture_xui_runtime
    fi
}

xui_install_sub2sing_box() {
    local version="${SUB2SING_BOX_VERSION:-$ARTIFACT_SUB2SING_VERSION}"
    [[ "$version" == "$ARTIFACT_SUB2SING_VERSION" ]] || { echo "Unsupported sub2sing-box version." >&2; return 1; }
    local arch
    local asset_name
    local asset_url
    local workdir
    local archive

    arch="$(xui_arch)" || {
        echo "Unsupported CPU architecture for sub2sing-box" >&2
        return 1
    }

    case "$arch" in
        amd64|386|arm64|armv7|armv6|armv5) ;;
        *)
            echo "Unsupported sub2sing-box architecture mapping: $arch" >&2
            return 1
            ;;
    esac

    workdir="$(mktemp -d)"
    asset_name="sub2sing-box_${version}_linux_${arch}.tar.gz"
    archive="${workdir}/${asset_name}"
    asset_url="https://github.com/legiz-ru/sub2sing-box/releases/download/v${version}/${asset_name}"

    sudo apt-get install -y -q tar >/dev/null
    curl -fsSL "$asset_url" -o "$archive"
    artifact_verify_file SUB2SING "$arch" "$archive" || {
        echo "sub2sing-box archive digest verification failed." >&2
        rm -rf "$workdir"
        return 1
    }
    tar -xzf "$archive" -C "$workdir"
    local binary_path
    binary_path="$(find "$workdir" -type f -name sub2sing-box | head -n 1)"
    if [ -z "$binary_path" ]; then
        echo "Could not find sub2sing-box binary inside extracted archive" >&2
        rm -rf "$workdir"
        return 1
    fi

    sudo install -m 0755 "$binary_path" /usr/local/bin/sub2sing-box
    sudo rm -f /usr/bin/sub2sing-box
    sudo pkill -f 'sub2sing-box server --bind 127.0.0.1 --port' >/dev/null 2>&1 || true
    sudo tee /etc/systemd/system/sub2sing-box.service >/dev/null <<EOF
[Unit]
Description=sub2sing-box local converter
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c '/usr/local/bin/sub2sing-box server --bind 127.0.0.1 --port ${PROFILE_XUI_SUB2SING_PORT} >/dev/null 2>&1 &'
ExecStop=/usr/bin/pkill -f "sub2sing-box server --bind 127.0.0.1 --port ${PROFILE_XUI_SUB2SING_PORT}" || true

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now sub2sing-box >/dev/null
    rm -rf "$workdir"
}

xui_render_sub_templates() {
    local template_root="${REPO_ROOT}/scripts/installer/templates/xui-pro"
    local sub_template="${template_root}/sub-3x-ui.html"
    local clash_template="${template_root}/clash.yaml"
    local target_dir="/var/www/subpage"
    local target_page="${target_dir}/index.html"
    local target_clash="${target_dir}/clash.yaml"
    local tmp_page
    local tmp_clash

    [ -f "$sub_template" ] || {
        echo "Missing sub page template: $sub_template" >&2
        return 1
    }
    [ -f "$clash_template" ] || {
        echo "Missing clash template: $clash_template" >&2
        return 1
    }

    sudo mkdir -p "$target_dir"
    tmp_page="$(mktemp)"
    tmp_clash="$(mktemp)"
    env \
        PROFILE_XUI_DOMAIN="${PROFILE_XUI_DOMAIN}" \
        PROFILE_XUI_SUB_PATH="${PROFILE_XUI_SUB_PATH}" \
        PROFILE_XUI_JSON_PATH="${PROFILE_XUI_JSON_PATH}" \
        python3 - "$sub_template" "$clash_template" "$tmp_page" "$tmp_clash" <<'PY'
from pathlib import Path
import os
import sys

sub_tpl = Path(sys.argv[1]).read_text()
clash_tpl = Path(sys.argv[2]).read_text()
page_target = Path(sys.argv[3])
clash_target = Path(sys.argv[4])

replacements = {
    "${DOMAIN}": os.environ["PROFILE_XUI_DOMAIN"],
    "${SUB_PATH}": f"/{os.environ['PROFILE_XUI_SUB_PATH']}/",
    "${SUB_JSON_PATH}": f"/{os.environ['PROFILE_XUI_JSON_PATH']}/",
}

for old, new in replacements.items():
    sub_tpl = sub_tpl.replace(old, new)
    clash_tpl = clash_tpl.replace(old, new)

page_target.write_text(sub_tpl)
clash_target.write_text(clash_tpl)
PY
    sudo install -m 0644 "$tmp_page" "$target_page"
    sudo install -m 0644 "$tmp_clash" "$target_clash"
    rm -f "$tmp_page" "$tmp_clash"
}

xui_install_root_landing_template() {
    local template_base="${REPO_ROOT}/scripts/installer/templates"
    local local_pool="${template_base}/.local-randomfakehtml"
    local sample_pool="${template_base}/.local-randomfakehtml-sample"
    local fallback_dir="${template_base}/xui-pro/fake-site"
    local target_dir="/var/www/multiserversubgen-xui-root"
    local ownership_marker="${target_dir}/.multiserversubgen-xui-root"
    local selected_zip=""
    local extract_dir=""
    local web_root=""
    local zip_candidates=()
    local selected_pool=""

    # Prefer the curated sample pool (10 approved archives). Use the broad local pool
    # only when sample pool is unavailable/empty.
    if [ -d "$sample_pool" ]; then
        while IFS= read -r f; do zip_candidates+=("$f"); done < <(find "$sample_pool" -maxdepth 1 -type f -name '*.zip' | sort)
    fi
    if [ "${#zip_candidates[@]}" -gt 0 ]; then
        selected_pool="sample"
    elif [ -d "$local_pool" ]; then
        while IFS= read -r f; do zip_candidates+=("$f"); done < <(find "$local_pool" -maxdepth 1 -type f -name '*.zip' | sort)
        [ "${#zip_candidates[@]}" -gt 0 ] && selected_pool="local"
    fi

    if [ "${#zip_candidates[@]}" -gt 0 ]; then
        selected_zip="$(printf '%s\n' "${zip_candidates[@]}" | shuf -n 1)"
        extract_dir="$(mktemp -d)"

        if ! python3 - "$selected_zip" "$extract_dir" <<'PY'
from pathlib import Path
import shutil
import sys
import zipfile

zip_path = Path(sys.argv[1])
dst = Path(sys.argv[2])
if not zip_path.exists():
    raise SystemExit(2)
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(dst)

# pick best web root:
# 1) extracted root if has index.html
# 2) first directory containing index.html
root = dst
if not (root / "index.html").exists():
    candidates = sorted(p.parent for p in dst.rglob("index.html") if p.is_file())
    if candidates:
        root = candidates[0]
    else:
        raise SystemExit(3)

marker = dst / ".selected-web-root"
marker.write_text(str(root))
PY
        then
            web_root="$(cat "$extract_dir/.selected-web-root" 2>/dev/null || true)"
            if [ -n "$web_root" ] && [ -d "$web_root" ]; then
                if xui_replace_owned_web_root "$target_dir" "$ownership_marker" "$web_root"; then
                    PROFILE_XUI_MAIN_TEMPLATE_SOURCE="zip"
                    PROFILE_XUI_MAIN_TEMPLATE_NAME="$(basename "$selected_zip")"
                    [ -n "$selected_pool" ] && PROFILE_XUI_MAIN_TEMPLATE_POOL="$selected_pool"
                    rm -rf "$extract_dir"
                    return 0
                fi
            fi
        fi

        rm -rf "$extract_dir"
    fi

    # fallback: bundled local placeholder page
    if [ -f "$fallback_dir/index.html" ]; then
        if xui_replace_owned_web_root "$target_dir" "$ownership_marker" "$fallback_dir"; then
            PROFILE_XUI_MAIN_TEMPLATE_SOURCE="fallback"
            PROFILE_XUI_MAIN_TEMPLATE_NAME="fake-site/index.html"
            return 0
        fi
    fi

    return 1
}

xui_require_owned_web_root() {
    local target_dir="$1"
    local ownership_marker="$2"

    if sudo test -L "$target_dir" || sudo test -L "$ownership_marker"; then
        echo "Refusing symlinked XUI web root or ownership marker: ${target_dir}" >&2
        return 1
    fi

    sudo mkdir -p "$target_dir"
    if sudo test -f "$ownership_marker"; then
        return 0
    fi

    if sudo find "$target_dir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
        echo "Refusing to replace unowned XUI web root: ${target_dir}" >&2
        return 1
    fi

    printf '%s\n' 'managed-by: multiserversubgen-xui' | sudo tee "$ownership_marker" >/dev/null
    sudo chmod 0644 "$ownership_marker"
}

xui_backup_owned_web_root() {
    local target_dir="$1"
    local backup_root="/var/backups/multiserversubgen/xui-web-root"
    local stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    local backup_dir="${backup_root}/${stamp}"
    local archive="${backup_dir}/web-root.tar.gz"
    local parent_dir
    local target_name

    parent_dir="$(dirname "$target_dir")"
    target_name="$(basename "$target_dir")"
    sudo install -d -m 0700 "$backup_dir"
    sudo tar -C "$parent_dir" -czf "$archive" -- "$target_name"
    sudo sha256sum "$archive" | sudo tee "${archive}.sha256" >/dev/null
    sudo sha256sum -c "${archive}.sha256" >/dev/null
    sudo tar -tzf "$archive" >/dev/null
    sudo chmod 0600 "$archive" "${archive}.sha256"
    printf '%s\n' "$archive"
}

xui_replace_owned_web_root() {
    local target_dir="$1"
    local ownership_marker="$2"
    local source_dir="$3"
    local backup_archive

    [ -f "$source_dir/index.html" ] || return 1
    xui_require_owned_web_root "$target_dir" "$ownership_marker" || return 1
    backup_archive="$(xui_backup_owned_web_root "$target_dir")" || return 1
    XUI_WEB_ROOT_BACKUP_ARCHIVE="$backup_archive"

    if ! (
        cd "$source_dir"
        tar -cf - .
    ) | {
        sudo find "$target_dir" -mindepth 1 -maxdepth 1 ! -name '.multiserversubgen-xui-root' -exec rm -rf -- {} +
        sudo tar -xf - -C "$target_dir"
    }; then
        xui_restore_owned_web_root "$target_dir" || true
        return 1
    fi

    if ! sudo test -f "$target_dir/index.html"; then
        xui_restore_owned_web_root "$target_dir" || true
        echo "XUI web root update failed; rollback archive: ${backup_archive}" >&2
        return 1
    fi
}

xui_restore_owned_web_root() {
    local target_dir="$1"
    local backup_archive="${XUI_WEB_ROOT_BACKUP_ARCHIVE:-}"
    local parent_dir

    [ -n "$backup_archive" ] && sudo test -f "$backup_archive" || return 1
    sudo sha256sum -c "${backup_archive}.sha256" >/dev/null
    sudo tar -tzf "$backup_archive" >/dev/null
    parent_dir="$(dirname "$target_dir")"
    sudo rm -rf -- "$target_dir"
    sudo tar -C "$parent_dir" -xzf "$backup_archive"
}

xui_detect_public_ipv4() {
    local ip
    ip="$(ip route get 8.8.8.8 2>/dev/null | grep -Po 'src \\K\\S+' | head -n 1 || true)"
    if [[ ! "$ip" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$ ]]; then
        ip="$(curl -4 -fsS https://ipv4.icanhazip.com 2>/dev/null | tr -d '[:space:]' || true)"
    fi
    printf "%s" "$ip"
}

xui_resolve_ipv4_for_host() {
    local host="$1"
    getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1 {print $1}'
}

xui_should_use_letsencrypt() {
    local domain="$1"
    local cert_mode="${XUI_CERT_MODE:-auto}"
    local server_ip
    local domain_ip

    case "$cert_mode" in
        self-signed) return 1 ;;
        letsencrypt) ;;
        auto) ;;
        *) cert_mode="auto" ;;
    esac

    command -v certbot >/dev/null 2>&1 || return 1
    server_ip="$(xui_detect_public_ipv4)"
    domain_ip="$(xui_resolve_ipv4_for_host "$domain")"
    [ -n "$server_ip" ] || return 1
    [ -n "$domain_ip" ] || return 1
    [ "$server_ip" = "$domain_ip" ] || return 1

    case "$server_ip" in
        10.*|127.*|169.254.*|192.168.*|100.64.*|100.65.*|100.66.*|100.67.*|100.68.*|100.69.*|100.7[0-9].*|100.8[0-9].*|100.9[0-9].*)
            return 1
            ;;
        172.1[6-9].*|172.2[0-9].*|172.3[0-1].*)
            return 1
            ;;
    esac

    return 0
}

xui_ensure_domain_cert() {
    local domain="$1"
    local cert_var="$2"
    local key_var="$3"
    local le_cert="/etc/letsencrypt/live/${domain}/fullchain.pem"
    local le_key="/etc/letsencrypt/live/${domain}/privkey.pem"
    local tls_dir="/etc/ssl/xui-core/${domain}"
    local cert_path
    local key_path

    if [ -f "$le_cert" ] && [ -f "$le_key" ]; then
        printf -v "$cert_var" "%s" "$le_cert"
        printf -v "$key_var" "%s" "$le_key"
        return 0
    fi

    if xui_should_use_letsencrypt "$domain"; then
        sudo systemctl stop nginx >/dev/null 2>&1 || true
        if sudo certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email -d "$domain" >/dev/null 2>&1; then
            sudo systemctl start nginx >/dev/null 2>&1 || true
            if [ -f "$le_cert" ] && [ -f "$le_key" ]; then
                printf -v "$cert_var" "%s" "$le_cert"
                printf -v "$key_var" "%s" "$le_key"
                return 0
            fi
        fi
        sudo systemctl start nginx >/dev/null 2>&1 || true
    fi

    cert_path="${tls_dir}/fullchain.pem"
    key_path="${tls_dir}/privkey.pem"
    sudo mkdir -p "$tls_dir"
    if [ ! -f "$cert_path" ] || [ ! -f "$key_path" ]; then
        sudo openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout "$key_path" \
            -out "$cert_path" \
            -days 3650 \
            -subj "/CN=${domain}" >/dev/null 2>&1
        sudo chmod 600 "$key_path"
        sudo chmod 644 "$cert_path"
    fi

    printf -v "$cert_var" "%s" "$cert_path"
    printf -v "$key_var" "%s" "$key_path"
}

xui_managed_nginx_paths() {
    local domain="${1:-}"
    local reality_domain="${2:-}"
    cat <<'EOF'
/etc/nginx/nginx.conf
/etc/nginx/snippets/multiserversubgen-xui-includes.conf
/etc/nginx/stream-enabled/multiserversubgen-xui-stream.conf
/etc/nginx/sites-available/multiserversubgen-xui-redirect.conf
/etc/nginx/sites-enabled/multiserversubgen-xui-redirect.conf
/etc/nginx/sites-available/multiserversubgen-xui-main.conf
/etc/nginx/sites-enabled/multiserversubgen-xui-main.conf
/etc/nginx/sites-available/multiserversubgen-xui-reality.conf
/etc/nginx/sites-enabled/multiserversubgen-xui-reality.conf
EOF
    [ -n "$domain" ] && printf '%s\n' "/etc/ssl/xui-core/${domain}" "/etc/letsencrypt/live/${domain}"
    [ -n "$reality_domain" ] && printf '%s\n' "/etc/ssl/xui-core/${reality_domain}" "/etc/letsencrypt/live/${reality_domain}"
}

xui_backup_managed_nginx_files() {
    local domain="${1:-}"
    local reality_domain="${2:-}"
    local backup_root="/var/backups/multiserversubgen/xui-nginx"
    local backup_dir="${backup_root}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
    local stage_dir
    local archive="${backup_dir}/nginx-managed-files.tar.gz"
    local manifest="${backup_dir}/manifest.tsv"
    local path

    stage_dir="$(mktemp -d)"
    trap 'rm -rf -- "$stage_dir"' RETURN
    sudo install -d -m 0700 "$backup_dir"
    while IFS= read -r path; do
        if sudo test -e "$path" || sudo test -L "$path"; then
            printf 'present\t%s\n' "$path" | sudo tee -a "$manifest" >/dev/null
            sudo mkdir -p "${stage_dir}$(dirname "$path")"
            sudo cp -a -- "$path" "${stage_dir}${path}"
        else
            printf 'absent\t%s\n' "$path" | sudo tee -a "$manifest" >/dev/null
        fi
    done < <(xui_managed_nginx_paths "$domain" "$reality_domain")
    sudo tar -C "$stage_dir" -czf "$archive" .
    sudo sha256sum "$archive" | sudo tee "${archive}.sha256" >/dev/null
    sudo sha256sum -c "${archive}.sha256" >/dev/null
    sudo tar -tzf "$archive" >/dev/null
    sudo chmod 0600 "$archive" "$manifest" "${archive}.sha256"
    rm -rf -- "$stage_dir"
    trap - RETURN
    XUI_NGINX_BACKUP_DIR="$backup_dir"
}

xui_restore_managed_nginx_files() {
    local backup_dir="${XUI_NGINX_BACKUP_DIR:-}"
    local archive="${backup_dir}/nginx-managed-files.tar.gz"
    local manifest="${backup_dir}/manifest.tsv"
    local state path

    [ -n "$backup_dir" ] && sudo test -f "$archive" && sudo test -f "$manifest" || return 1
    sudo sha256sum -c "${archive}.sha256" >/dev/null
    sudo tar -tzf "$archive" >/dev/null
    while IFS=$'\t' read -r state path; do
        [ "$state" = "absent" ] && sudo rm -f -- "$path"
    done < <(sudo cat "$manifest")
    sudo tar -C / -xzf "$archive"
}

xui_assert_no_unmanaged_nginx_443_conflicts() {
    local managed_stream="/etc/nginx/stream-enabled/multiserversubgen-xui-stream.conf"
    local config_path
    local conflicts=()

    shopt -s nullglob
    for config_path in /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf /etc/nginx/stream-enabled/*.conf; do
        [ -f "$config_path" ] || [ -L "$config_path" ] || continue
        [ "$(readlink -f "$config_path" 2>/dev/null || printf '%s' "$config_path")" = "$managed_stream" ] && continue
        if grep -qsE 'listen[[:space:]]+([^#;[:space:]]+:)?443([[:space:];]|$)' "$config_path"; then
            conflicts+=("$config_path")
        fi
    done
    shopt -u nullglob

    if [ "${#conflicts[@]}" -gt 0 ]; then
        printf 'Refusing to replace unmanaged Nginx listener(s) on port 443:\n%s\n' "$(printf '  %s\n' "${conflicts[@]}")" >&2
        return 1
    fi
}

xui_ensure_stream_include() {
    local nginx_conf="/etc/nginx/nginx.conf"

    if sudo grep -q 'stream-enabled/\\*.conf' "$nginx_conf"; then
        return 0
    fi
    if sudo grep -qE '^[[:space:]]*stream[[:space:]]*\{' "$nginx_conf"; then
        echo "Refusing to modify an unmanaged Nginx stream block in ${nginx_conf}" >&2
        return 1
    fi

    sudo tee -a "$nginx_conf" >/dev/null <<'EOF'
# managed-by: multiserversubgen-xui
stream {
    include /etc/nginx/stream-enabled/*.conf;
}
EOF
}

xui_write_nginx_includes() {
    sudo mkdir -p /etc/nginx/snippets
    sudo tee /etc/nginx/snippets/multiserversubgen-xui-includes.conf >/dev/null <<EOF
# managed-by: multiserversubgen-xui
location /${PROFILE_XUI_SUB2SING_PATH}/ {
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_pass http://127.0.0.1:${PROFILE_XUI_SUB2SING_PORT}/;
}
location ~ ^/${PROFILE_XUI_WEB_PATH}/clashmeta/(.+)$ {
    default_type text/plain;
    root /var/www/subpage;
    try_files /clash.yaml =404;
}
location ~ ^/${PROFILE_XUI_WEB_PATH} {
    root /var/www/subpage;
    index index.html;
    try_files \$uri \$uri/ /index.html =404;
}
location /${PROFILE_XUI_SUB_PATH} {
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_pass https://127.0.0.1:${PROFILE_XUI_SUB_PORT};
}
location /${PROFILE_XUI_SUB_PATH}/ {
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_pass https://127.0.0.1:${PROFILE_XUI_SUB_PORT};
}
location /assets/ {
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_pass https://127.0.0.1:${PROFILE_XUI_SUB_PORT};
}
location /${PROFILE_XUI_JSON_PATH} {
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_pass https://127.0.0.1:${PROFILE_XUI_SUB_PORT};
}
location /${PROFILE_XUI_JSON_PATH}/ {
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_pass https://127.0.0.1:${PROFILE_XUI_SUB_PORT};
}
location /${PROFILE_XUI_XHTTP_PATH} {
    grpc_pass grpc://unix:/dev/shm/uds2023.sock;
    grpc_buffer_size 16k;
    grpc_socket_keepalive on;
    grpc_read_timeout 1h;
    grpc_send_timeout 1h;
    grpc_set_header Connection "";
    grpc_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    grpc_set_header X-Forwarded-Proto \$scheme;
    grpc_set_header X-Forwarded-Port \$server_port;
    grpc_set_header Host \$host;
    grpc_set_header X-Forwarded-Host \$host;
}
location ~ ^/(?<fwdport>\\d+)/(?<fwdpath>.*)\$ {
    client_max_body_size 0;
    client_body_timeout 1d;
    grpc_read_timeout 1d;
    grpc_socket_keepalive on;
    proxy_read_timeout 1d;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_socket_keepalive on;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    if (\$content_type ~* "GRPC") {
        grpc_pass grpc://127.0.0.1:\$fwdport\$is_args\$args;
        break;
    }
    if (\$http_upgrade ~* "(WEBSOCKET|WS)") {
        proxy_pass http://127.0.0.1:\$fwdport\$is_args\$args;
        break;
    }
    if (\$request_method ~* ^(PUT|POST|GET)\$) {
        proxy_pass http://127.0.0.1:\$fwdport\$is_args\$args;
        break;
    }
}
location / {
    try_files \$uri \$uri/ =404;
}
EOF
}

xui_write_stream_mux() {
    local domain="$1"
    local reality_domain="$2"
    sudo mkdir -p /etc/nginx/stream-enabled
    sudo tee /etc/nginx/stream-enabled/multiserversubgen-xui-stream.conf >/dev/null <<EOF
# managed-by: multiserversubgen-xui
map \$ssl_preread_server_name \$sni_name {
    hostnames;
    ${reality_domain} xray;
    ${domain} www;
    default xray;
}

upstream xray {
    server 127.0.0.1:8443;
}

upstream www {
    server 127.0.0.1:7443;
}

server {
    proxy_protocol on;
    set_real_ip_from unix:;
    listen 443;
    proxy_pass \$sni_name;
    ssl_preread on;
}
EOF

    xui_ensure_stream_include

    if [ -f /etc/nginx/modules-enabled/50-mod-stream.conf ]; then
        sudo python3 - <<'PY'
from pathlib import Path
path = Path("/etc/nginx/nginx.conf")
if path.exists():
    lines = path.read_text().splitlines()
    target = "load_module /usr/lib/nginx/modules/ngx_stream_module.so;"
    lines = [line for line in lines if line.strip() != target]
    path.write_text("\n".join(lines) + "\n")
PY
    elif ! sudo sh -c "grep -Rqs 'ngx_stream_module.so' /etc/nginx/nginx.conf /etc/nginx/modules-enabled /etc/nginx/conf.d /etc/nginx/modules-available 2>/dev/null"; then
        sudo sed -i '1s|^|load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n|' /etc/nginx/nginx.conf
    fi
}

xui_write_site_configs() {
    local domain="$1"
    local reality_domain="$2"
    local domain_cert="$3"
    local domain_key="$4"
    local reality_cert="$5"
    local reality_key="$6"

    sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

    sudo tee /etc/nginx/sites-available/multiserversubgen-xui-redirect.conf >/dev/null <<EOF
# managed-by: multiserversubgen-xui
server {
    listen 80;
    server_name ${domain} ${reality_domain};
    return 301 https://\$host\$request_uri;
}
EOF

    sudo tee /etc/nginx/sites-available/multiserversubgen-xui-main.conf >/dev/null <<EOF
# managed-by: multiserversubgen-xui
server {
    server_tokens off;
    server_name ${domain};
    listen 7443 ssl http2 proxy_protocol;
    listen [::]:7443 ssl http2 proxy_protocol;
    root /var/www/multiserversubgen-xui-root/;
    ssl_certificate ${domain_cert};
    ssl_certificate_key ${domain_key};

    location /${PROFILE_XUI_PANEL_PATH}/ {
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection Upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass https://127.0.0.1:${PROFILE_XUI_PANEL_PORT};
    }
    location /${PROFILE_XUI_PANEL_PATH} {
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection Upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass https://127.0.0.1:${PROFILE_XUI_PANEL_PORT};
    }
    include /etc/nginx/snippets/multiserversubgen-xui-includes.conf;
}
EOF

    sudo tee /etc/nginx/sites-available/multiserversubgen-xui-reality.conf >/dev/null <<EOF
# managed-by: multiserversubgen-xui
server {
    server_tokens off;
    server_name ${reality_domain};
    listen 9443 ssl http2;
    listen [::]:9443 ssl http2;
    root /var/www/multiserversubgen-xui-root/;
    ssl_certificate ${reality_cert};
    ssl_certificate_key ${reality_key};

    location /${PROFILE_XUI_PANEL_PATH}/ {
        proxy_redirect off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_pass http://127.0.0.1:${PROFILE_XUI_PANEL_PORT};
    }
    location /${PROFILE_XUI_PANEL_PATH} {
        proxy_redirect off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_pass http://127.0.0.1:${PROFILE_XUI_PANEL_PORT};
    }
    include /etc/nginx/snippets/multiserversubgen-xui-includes.conf;
}
EOF

    sudo ln -sf /etc/nginx/sites-available/multiserversubgen-xui-redirect.conf /etc/nginx/sites-enabled/multiserversubgen-xui-redirect.conf
    sudo ln -sf /etc/nginx/sites-available/multiserversubgen-xui-main.conf /etc/nginx/sites-enabled/multiserversubgen-xui-main.conf
    sudo ln -sf /etc/nginx/sites-available/multiserversubgen-xui-reality.conf /etc/nginx/sites-enabled/multiserversubgen-xui-reality.conf
}

xui_configure_nginx_and_tls() {
    local domain="$1"
    local reality_domain="$2"
    local domain_cert domain_key reality_cert reality_key

    xui_backup_managed_nginx_files "$domain" "$reality_domain"

    if ! xui_ensure_system_prerequisites \
        || ! xui_generate_panel_settings \
        || ! xui_assert_no_unmanaged_nginx_443_conflicts \
        || ! xui_install_root_landing_template \
        || ! xui_ensure_domain_cert "$domain" domain_cert domain_key \
        || ! xui_ensure_domain_cert "$reality_domain" reality_cert reality_key \
        || ! xui_write_nginx_includes \
        || ! xui_write_stream_mux "$domain" "$reality_domain" \
        || ! xui_write_site_configs "$domain" "$reality_domain" "$domain_cert" "$domain_key" "$reality_cert" "$reality_key" \
        || ! sudo nginx -t \
        || ! sudo systemctl reload nginx; then
        xui_restore_managed_nginx_files || true
        xui_restore_owned_web_root "/var/www/multiserversubgen-xui-root" || true
        sudo nginx -t && sudo systemctl reload nginx || true
        return 1
    fi
    xui_configure_fail2ban_security

    PROFILE_XUI_CERT_PATH="$domain_cert"
    PROFILE_XUI_CERT_KEY_PATH="$domain_key"
}

xui_configure_fail2ban_security() {
    local ssh_port
    local panel_path

    ssh_port="$(awk '/^[[:space:]]*Port[[:space:]]+[0-9]+/{print $2; exit}' /etc/ssh/sshd_config 2>/dev/null || true)"
    [ -n "$ssh_port" ] || ssh_port="22"

    panel_path="${PROFILE_XUI_PANEL_PATH:-}"
    panel_path="${panel_path#/}"
    panel_path="${panel_path%/}"
    [ -n "$panel_path" ] || panel_path="xui"

    sudo mkdir -p /etc/fail2ban/filter.d /etc/fail2ban/jail.d

    sudo tee /etc/fail2ban/filter.d/xui-panel-login.conf >/dev/null <<EOF
[Definition]
failregex = ^<HOST> -.* "(GET|POST) /${panel_path}/login[^\"]* HTTP/[0-9.]+" (200|401|403|404|429) .*
ignoreregex =
EOF

    sudo tee /etc/fail2ban/jail.d/xui-core.local >/dev/null <<EOF
[sshd]
enabled = true
port = ${ssh_port}
backend = systemd
maxretry = 6
findtime = 10m
bantime = 1h

[xui-panel-login]
enabled = true
port = http,https
filter = xui-panel-login
logpath = /var/log/nginx/access.log
maxretry = 15
findtime = 10m
bantime = 2h
action = %(action_)s
EOF

    sudo systemctl enable fail2ban >/dev/null 2>&1 || true
    sudo systemctl restart fail2ban >/dev/null 2>&1 || true
}

xui_print_runtime_summary() {
    printf "\n"
    printf "3x-ui panel: %s\n" "${PROFILE_XUI_PANEL_URL:-unknown}"
    printf "3x-ui user: %s\n" "${PROFILE_XUI_USERNAME:-unknown}"
    printf "3x-ui password: stored in protected service configuration\n"
    printf "3x-ui status: %s\n" "${PROFILE_XUI_STATUS:-unknown}"
    printf "Web sub page: %s\n" "${PROFILE_XUI_WEBSUB_URL:-unknown}"
    printf "sub2sing-box: %s\n" "${PROFILE_XUI_SUB2SING_URL:-unknown}"
    printf "sub2sing status: %s\n" "${PROFILE_XUI_SUB2SING_STATUS:-unknown}"
}
