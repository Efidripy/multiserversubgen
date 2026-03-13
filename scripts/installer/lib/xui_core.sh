#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/locale.sh"

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

xui_pick_release_tag() {
    if [ -n "${XUI_VERSION:-}" ]; then
        printf "%s" "${XUI_VERSION}"
        return 0
    fi

    local tag
    tag="$(curl -fsSL https://api.github.com/repos/MHSanaei/3x-ui/releases/latest 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || true)"
    if [ -z "$tag" ]; then
        tag="v2.6.6"
    fi
    printf "%s" "$tag"
}

xui_download_release() {
    local target_archive="$1"
    local tag="$2"
    local arch

    arch="$(xui_arch)" || return 1
    curl -fsSL "https://github.com/MHSanaei/3x-ui/releases/download/${tag}/x-ui-linux-${arch}.tar.gz" -o "$target_archive"
}

xui_seed_nginx_bootstrap_files() {
    sudo mkdir -p /etc/nginx/conf.d /etc/nginx/modules-enabled /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/snippets /etc/nginx/stream-enabled
    if [ ! -f /etc/nginx/nginx.conf ]; then
        sudo tee /etc/nginx/nginx.conf >/dev/null <<'EOF'
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 1024;
}

http {
    default_type application/octet-stream;
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
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
        -o Dpkg::Options::="--force-confnew" \
        wget \
        curl \
        tar \
        tzdata \
        nginx \
        libnginx-mod-stream \
        openssl \
        sqlite3 \
        certbot \
        python3-certbot-nginx >/dev/null; then
        sudo DEBIAN_FRONTEND=noninteractive dpkg --force-confnew --configure -a >/dev/null 2>&1 || true
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -f -y -o Dpkg::Options::="--force-confnew" >/dev/null 2>&1 || true
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
            -o Dpkg::Options::="--force-confnew" \
            wget \
            curl \
            tar \
            tzdata \
            nginx \
            libnginx-mod-stream \
            openssl \
            sqlite3 \
            certbot \
            python3-certbot-nginx >/dev/null
    fi
    sudo DEBIAN_FRONTEND=noninteractive dpkg --force-confnew --configure -a >/dev/null 2>&1 || true
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -f -y -o Dpkg::Options::="--force-confnew" >/dev/null 2>&1 || true

    if [ ! -f /etc/nginx/nginx.conf ]; then
        xui_seed_nginx_bootstrap_files
        sudo DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y -q \
            -o Dpkg::Options::="--force-confnew" \
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

    arch="$(xui_arch)" || {
        echo "Unsupported CPU architecture for x-ui" >&2
        return 1
    }

    workdir="$(mktemp -d)"
    archive="${workdir}/x-ui-linux-${arch}.tar.gz"

    xui_ensure_system_prerequisites

    xui_download_release "$archive" "$tag"
    curl -fsSL https://raw.githubusercontent.com/MHSanaei/3x-ui/main/x-ui.sh -o "${workdir}/x-ui-temp"

    if [ -d /usr/local/x-ui ]; then
        sudo systemctl stop x-ui >/dev/null 2>&1 || true
        sudo rm -rf /usr/local/x-ui
    fi

    sudo mkdir -p /usr/local
    sudo tar -xzf "$archive" -C /usr/local
    sudo chmod +x /usr/local/x-ui/x-ui /usr/local/x-ui/x-ui.sh

    if [[ "$arch" == armv5 || "$arch" == armv6 || "$arch" == armv7 ]]; then
        sudo mv "/usr/local/x-ui/bin/xray-linux-${arch}" /usr/local/x-ui/bin/xray-linux-arm
        sudo chmod +x /usr/local/x-ui/bin/xray-linux-arm
    elif [ -f "/usr/local/x-ui/bin/xray-linux-${arch}" ]; then
        sudo chmod +x "/usr/local/x-ui/bin/xray-linux-${arch}"
    fi

    sudo mv -f "${workdir}/x-ui-temp" /usr/bin/x-ui
    sudo chmod +x /usr/bin/x-ui

    if [ -f /usr/local/x-ui/x-ui.service.debian ]; then
        sudo cp -f /usr/local/x-ui/x-ui.service.debian /etc/systemd/system/x-ui.service
    fi

    sudo systemctl daemon-reload
    sudo systemctl enable x-ui >/dev/null
    sudo systemctl start x-ui
    sudo x-ui migrate >/dev/null 2>&1 || true

    rm -rf "$workdir"
}

xui_generate_panel_settings() {
    PROFILE_XUI_PANEL_PORT="${PROFILE_XUI_PANEL_PORT:-$(shuf -i 20000-49000 -n 1)}"
    PROFILE_XUI_PANEL_PATH="${PROFILE_XUI_PANEL_PATH:-$(xui_random_token 10)}"
    PROFILE_XUI_USERNAME="${PROFILE_XUI_USERNAME:-$(xui_random_token 10)}"
    PROFILE_XUI_PASSWORD="${PROFILE_XUI_PASSWORD:-$(xui_random_token 14)}"
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
}

xui_install_sub2sing_box() {
    local version="${SUB2SING_BOX_VERSION:-0.0.9}"
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

xui_write_nginx_includes() {
    sudo mkdir -p /etc/nginx/snippets
    sudo tee /etc/nginx/snippets/includes.conf >/dev/null <<EOF
# Generated by internal x-ui core.
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
    sudo rm -f /etc/nginx/stream-enabled/xui-stream.conf
    sudo tee /etc/nginx/stream-enabled/stream.conf >/dev/null <<EOF
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

    sudo grep -q "stream-enabled/\\*.conf" /etc/nginx/nginx.conf || sudo tee -a /etc/nginx/nginx.conf >/dev/null <<'EOF'
stream { include /etc/nginx/stream-enabled/*.conf; }
EOF

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

    sudo tee /etc/nginx/sites-available/80.conf >/dev/null <<EOF
server {
    listen 80;
    server_name ${domain} ${reality_domain};
    return 301 https://\$host\$request_uri;
}
EOF

    sudo tee "/etc/nginx/sites-available/${domain}" >/dev/null <<EOF
server {
    server_tokens off;
    server_name ${domain};
    listen 7443 ssl http2 proxy_protocol;
    listen [::]:7443 ssl http2 proxy_protocol;
    root /var/www/html/;
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
    include /etc/nginx/snippets/includes.conf;
}
EOF

    sudo tee "/etc/nginx/sites-available/${reality_domain}" >/dev/null <<EOF
server {
    server_tokens off;
    server_name ${reality_domain};
    listen 9443 ssl http2;
    listen [::]:9443 ssl http2;
    root /var/www/html/;
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
    include /etc/nginx/snippets/includes.conf;
}
EOF

    sudo ln -sf /etc/nginx/sites-available/80.conf /etc/nginx/sites-enabled/80.conf
    sudo ln -sf "/etc/nginx/sites-available/${domain}" "/etc/nginx/sites-enabled/${domain}"
    sudo ln -sf "/etc/nginx/sites-available/${reality_domain}" "/etc/nginx/sites-enabled/${reality_domain}"
}

xui_configure_nginx_and_tls() {
    local domain="$1"
    local reality_domain="$2"
    local domain_cert domain_key reality_cert reality_key

    xui_ensure_system_prerequisites
    xui_generate_panel_settings
    xui_ensure_domain_cert "$domain" domain_cert domain_key
    xui_ensure_domain_cert "$reality_domain" reality_cert reality_key
    xui_write_nginx_includes
    xui_write_stream_mux "$domain" "$reality_domain"
    xui_write_site_configs "$domain" "$reality_domain" "$domain_cert" "$domain_key" "$reality_cert" "$reality_key"
    sudo nginx -t
    sudo systemctl reload nginx

    PROFILE_XUI_CERT_PATH="$domain_cert"
    PROFILE_XUI_CERT_KEY_PATH="$domain_key"
}

xui_print_runtime_summary() {
    printf "\n"
    printf "3x-ui panel: %s\n" "${PROFILE_XUI_PANEL_URL:-unknown}"
    printf "3x-ui user: %s\n" "${PROFILE_XUI_USERNAME:-unknown}"
    printf "3x-ui password: %s\n" "${PROFILE_XUI_PASSWORD:-unknown}"
    printf "3x-ui status: %s\n" "${PROFILE_XUI_STATUS:-unknown}"
    printf "Web sub page: %s\n" "${PROFILE_XUI_WEBSUB_URL:-unknown}"
    printf "sub2sing-box: %s\n" "${PROFILE_XUI_SUB2SING_URL:-unknown}"
    printf "sub2sing status: %s\n" "${PROFILE_XUI_SUB2SING_STATUS:-unknown}"
}
