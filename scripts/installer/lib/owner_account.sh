#!/bin/bash

owner_account_validate_username() {
    local value="${1:-}"
    [[ "$value" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]
}

owner_account_validate_role_owners() {
    local value="${1:-}"
    [[ "$value" =~ ^[a-z_][a-z0-9_-]*(,[a-z_][a-z0-9_-]*)*$ ]]
}

owner_account_random_byte() {
    local value
    value="$(od -An -N1 -tu1 /dev/urandom | tr -d '[:space:]')" || return 1
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
}

owner_account_user_exists() {
    id -u -- "$1" >/dev/null 2>&1
}

owner_account_generate_username() {
    local length first rest candidate byte index random_pos
    local -a random_data=()
    while true; do
        random_pos=0
        random_data=()
        read -r -a random_data <<< "$(od -An -N128 -tu1 /dev/urandom | tr '\n' ' ')" || return 1
        [ "${#random_data[@]}" -ge 32 ] || return 1
        byte="${random_data[random_pos]}"
        random_pos=$((random_pos + 1))
        length=$((8 + byte % 9))

        byte="${random_data[random_pos]}"
        random_pos=$((random_pos + 1))
        first="$(printf '%s' abcdefghijklmnopqrstuvwxyz | cut -c $((byte % 26 + 1)))"
        rest=""
        while [ "${#rest}" -lt $((length - 1)) ]; do
            byte="${random_data[random_pos]}"
            random_pos=$((random_pos + 1))
            index=$((byte % 36 + 1))
            rest="${rest}$(printf '%s' abcdefghijklmnopqrstuvwxyz0123456789 | cut -c "$index")"
        done
        candidate="${first}${rest}"
        owner_account_validate_username "$candidate" || continue
        [ "$candidate" != "root" ] || continue
        owner_account_user_exists "$candidate" && continue
        case ",${OWNER_ACCOUNT_GENERATED_NAMES:-}," in
            *",${candidate},"*) continue ;;
        esac
        OWNER_ACCOUNT_GENERATED_NAMES="${OWNER_ACCOUNT_GENERATED_NAMES:-}${OWNER_ACCOUNT_GENERATED_NAMES:+,}${candidate}"
        printf '%s\n' "$candidate"
        return 0
    done
}

owner_account_generate_password() {
    local password="" byte index alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" random_pos=0
    local -a random_data=()
    read -r -a random_data <<< "$(od -An -N64 -tu1 /dev/urandom | tr '\n' ' ')" || return 1
    [ "${#random_data[@]}" -ge 16 ] || return 1
    while [ "${#password}" -lt 16 ]; do
        byte="${random_data[random_pos]}"
        random_pos=$((random_pos + 1))
        index=$((byte % 62 + 1))
        password="${password}$(printf '%s' "$alphabet" | cut -c "$index")"
    done
    printf '%s\n' "$password"
}

owner_account_terminal_available() {
    [ -t 0 ] || [ -t 1 ]
}

owner_account_prompt_password() {
    local password confirmation
    while true; do
        password=""
        confirmation=""
        read -r -s -p "Пароль владельца (ввод скрыт; Enter = сгенерировать случайный): " password
        printf '\n' >&2
        if [ -z "$password" ]; then
            OWNER_ACCOUNT_PASSWORD="$(owner_account_generate_password)" || return 1
            OWNER_ACCOUNT_PASSWORD_GENERATED=1
            return 0
        fi
        if [ "${#password}" -lt 8 ] || [ "${#password}" -gt 128 ]; then
            echo "Пароль должен содержать от 8 до 128 символов." >&2
            continue
        fi
        read -r -s -p "Повторите пароль владельца: " confirmation
        printf '\n' >&2
        if [ "$password" != "$confirmation" ]; then
            echo "Пароли не совпадают, повторите ввод." >&2
            continue
        fi
        OWNER_ACCOUNT_PASSWORD="$password"
        OWNER_ACCOUNT_PASSWORD_GENERATED=0
        return 0
    done
}

owner_account_collect() {
    local username="" password_from_env=0 username_from_env=0 use_existing
    OWNER_ACCOUNT_EXISTING=0
    OWNER_ACCOUNT_PASSWORD_GENERATED=0
    OWNER_ACCOUNT_GENERATED_NAMES="${OWNER_ACCOUNT_GENERATED_NAMES:-}"

    if [ "${OWNER_USERNAME+x}" = x ] && [ -n "${OWNER_USERNAME:-}" ]; then
        username_from_env=1
        username="$OWNER_USERNAME"
    fi
    if [ "${OWNER_PASSWORD+x}" = x ]; then
        password_from_env=1
    fi

    while true; do
        if [ -z "$username" ]; then
            if owner_account_terminal_available; then
                read -r -p "Владелец панели - имя пользователя Linux (Enter = сгенерировать случайное имя из 8-16 символов): " username
            fi
            if [ -z "$username" ]; then
                username="$(owner_account_generate_username)" || return 1
            fi
        fi
        if ! owner_account_validate_username "$username"; then
            if [ "$username_from_env" -eq 1 ]; then
                echo "Некорректное имя OWNER_USERNAME." >&2
                return 1
            fi
            echo "Имя пользователя должно соответствовать формату Linux-пользователя." >&2
            username=""
            continue
        fi

        if [ "$username" = "root" ]; then
            OWNER_ACCOUNT_EXISTING=1
            OWNER_ACCOUNT_USERNAME="$username"
            OWNER_ACCOUNT_PASSWORD=""
            OWNER_USERNAME="$username"
            ROLE_OWNERS="$username"
            return 0
        fi

        if owner_account_user_exists "$username"; then
            use_existing="n"
            if [ "$username_from_env" -eq 1 ] || ! owner_account_terminal_available; then
                use_existing="y"
            else
                read -r -p "Пользователь уже существует. Использовать его как владельца без смены пароля? (y/N): " use_existing
            fi
            if [[ "$use_existing" =~ ^[yYдД]$ ]]; then
                OWNER_ACCOUNT_EXISTING=1
                OWNER_ACCOUNT_USERNAME="$username"
                OWNER_ACCOUNT_PASSWORD=""
                OWNER_USERNAME="$username"
                ROLE_OWNERS="$username"
                return 0
            fi
            username=""
            username_from_env=0
            continue
        fi
        break
    done

    OWNER_ACCOUNT_USERNAME="$username"
    OWNER_USERNAME="$username"
    ROLE_OWNERS="$username"
    if [ "$password_from_env" -eq 1 ]; then
        password="${OWNER_PASSWORD:-}"
        if [ -z "$password" ]; then
            OWNER_ACCOUNT_PASSWORD="$(owner_account_generate_password)" || return 1
            OWNER_ACCOUNT_PASSWORD_GENERATED=1
        elif [ "${#password}" -lt 8 ] || [ "${#password}" -gt 128 ]; then
            echo "Некорректная длина OWNER_PASSWORD (допустимо 8-128 символов)." >&2
            return 1
        else
            OWNER_ACCOUNT_PASSWORD="$password"
        fi
    elif owner_account_terminal_available; then
        owner_account_prompt_password || return 1
    else
        OWNER_ACCOUNT_PASSWORD="$(owner_account_generate_password)" || return 1
        OWNER_ACCOUNT_PASSWORD_GENERATED=1
    fi
}

owner_account_create() {
    owner_account_validate_username "${OWNER_ACCOUNT_USERNAME:-}" || return 1
    [ "${OWNER_ACCOUNT_USERNAME:-}" = "root" ] && return 0
    [ "${OWNER_ACCOUNT_EXISTING:-0}" = "1" ] && return 0
    if ! owner_account_user_exists "$OWNER_ACCOUNT_USERNAME"; then
        useradd -m -s /usr/sbin/nologin "$OWNER_ACCOUNT_USERNAME" || return 1
        printf '%s:%s\n' "$OWNER_ACCOUNT_USERNAME" "$OWNER_ACCOUNT_PASSWORD" | chpasswd || return 1
    fi
}

owner_account_print_credentials() {
    local output="/dev/stdout"
    [ -w /dev/tty ] && output="/dev/tty"
    if [ "${OWNER_ACCOUNT_PASSWORD_GENERATED:-0}" = "1" ]; then
        {
            printf '%s\n' '============================================================'
            printf 'Владелец панели: %s\n' "$OWNER_ACCOUNT_USERNAME"
            printf 'Пароль владельца: %s\n' "$OWNER_ACCOUNT_PASSWORD"
            printf '%s\n' 'Сохраните эти данные, пароль больше нигде не хранится.'
            printf '%s\n' '============================================================'
        } > "$output"
    else
        printf 'Владелец панели: %s\n' "$OWNER_ACCOUNT_USERNAME" > "$output"
    fi
}

owner_account_extract_role_owners() {
    local file="$1" line value=""
    [ -f "$file" ] || return 1
    while IFS= read -r line; do
        if [[ "$line" =~ Environment=\"ROLE_OWNERS=([a-z_][a-z0-9_-]*(,[a-z_][a-z0-9_-]*)*)\" ]]; then
            value="${BASH_REMATCH[1]}"
        fi
    done < "$file"
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
}

owner_account_read_existing_role_owners() {
    local project="${1:?project name is required}"
    local systemd_dir="${OWNER_ACCOUNT_SYSTEMD_DIR:-/etc/systemd/system}"
    local value dropin
    value="$(owner_account_extract_role_owners "$systemd_dir/${project}.service" 2>/dev/null || true)"
    for dropin in "$systemd_dir/${project}.service.d"/*.conf; do
        [ -f "$dropin" ] || continue
        value="$(owner_account_extract_role_owners "$dropin" 2>/dev/null || printf '%s' "$value")"
    done
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
}
