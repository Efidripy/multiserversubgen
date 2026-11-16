#!/bin/bash

# Install the root-owned PAM boundary before enabling the application socket.
pam_helper_install() {
    local project_name="${1:?project name required}"
    local source_root="${2:?source root required}"
    local project_uid project_group helper_dir socket_unit service_unit tmpfiles_unit
    project_uid="$(id -u "$project_name" 2>/dev/null || true)"
    project_group="$(id -gn "$project_name" 2>/dev/null || true)"
    if [[ ! "$project_uid" =~ ^[0-9]+$ || -z "$project_group" ]]; then
        echo "PAM helper: project identity is unavailable; keeping legacy shadow mode." >&2
        pam_helper_install_legacy "$project_name"
        return 0
    fi
    helper_dir=/usr/local/lib/sub-manager-pam
    socket_unit=/etc/systemd/system/sub-manager-pam.socket
    service_unit=/etc/systemd/system/sub-manager-pam@.service
    tmpfiles_unit=/etc/tmpfiles.d/sub-manager-pam.conf
    install -d -o root -g root -m 0755 "$helper_dir"
    install -o root -g root -m 0755 "$source_root/scripts/pam/sub_manager_pam.py" \
        "$helper_dir/sub_manager_pam.py"
    sed -e "s/__PROJECT_NAME__/$project_group/g" "$source_root/systemd/sub-manager-pam.socket" \
        | install -o root -g root -m 0644 /dev/stdin "$socket_unit"
    sed -e "s/__PROJECT_UID__/$project_uid/g" "$source_root/systemd/sub-manager-pam@.service" \
        | install -o root -g root -m 0644 /dev/stdin "$service_unit"
    sed -e "s/__PROJECT_NAME__/$project_group/g" "$source_root/systemd/sub-manager-pam-tmpfiles.conf" \
        | install -o root -g root -m 0644 /dev/stdin "$tmpfiles_unit"
    systemd-tmpfiles --create "$tmpfiles_unit" >/dev/null 2>&1 || true
    systemctl daemon-reload
    systemctl enable --now sub-manager-pam.socket >/dev/null 2>&1 || {
        echo "WARNING: PAM helper socket could not be started; using legacy shadow mode." >&2
        pam_helper_install_legacy "$project_name"
        return 0
    }
    # Run the probe as the service user: only then the helper takes the real PAM path
    # (a root caller is rejected by the peer-uid check before PAM is ever called).
    if runuser -u "$project_name" -- /usr/bin/python3 "$helper_dir/sub_manager_pam.py" \
        --self-check /run/sub-manager-pam/pam.sock --probe-user "$project_name" >/dev/null 2>&1; then
        install -d -m 0755 "/etc/systemd/system/${project_name}.service.d"
        cat > "/etc/systemd/system/${project_name}.service.d/pam-helper.conf" <<EOF
[Unit]
Requires=sub-manager-pam.socket
After=sub-manager-pam.socket

[Service]
Environment=PAM_HELPER_SOCKET=/run/sub-manager-pam/pam.sock
EOF
        rm -f "/etc/systemd/system/${project_name}.service.d/legacy-shadow.conf"
        systemctl daemon-reload
        return 0
    fi
    echo "WARNING: PAM helper self-check failed; using legacy shadow mode." >&2
    pam_helper_install_legacy "$project_name"
}

pam_helper_install_legacy() {
    local project_name="${1:?project name required}"
    install -d -m 0755 "/etc/systemd/system/${project_name}.service.d"
    cat > "/etc/systemd/system/${project_name}.service.d/legacy-shadow.conf" <<'EOF'
[Service]
SupplementaryGroups=shadow
EOF
    rm -f "/etc/systemd/system/${project_name}.service.d/pam-helper.conf"
    systemctl daemon-reload >/dev/null 2>&1 || true
}

pam_helper_remove() {
    local project_name="${1:?project name required}"
    systemctl disable --now sub-manager-pam.socket >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/sub-manager-pam.socket /etc/systemd/system/sub-manager-pam@.service
    rm -f /etc/tmpfiles.d/sub-manager-pam.conf
    rm -rf /usr/local/lib/sub-manager-pam /run/sub-manager-pam
    rm -f "/etc/systemd/system/${project_name}.service.d/pam-helper.conf" \
        "/etc/systemd/system/${project_name}.service.d/legacy-shadow.conf"
    rmdir "/etc/systemd/system/${project_name}.service.d" 2>/dev/null || true
    systemctl daemon-reload >/dev/null 2>&1 || true
}
