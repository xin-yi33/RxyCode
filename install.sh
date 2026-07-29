#!/usr/bin/env sh

set -eu

DEFAULT_VERSION="1.2.1"
REPOSITORY="https://github.com/xin-yi33/RxyCode.git"
UV_INSTALLER_URL="https://astral.sh/uv/install.sh"
MAX_INSTALLER_BYTES=2097152

while [ "$#" -gt 0 ]; do
    case "$1" in
        --force|-f)
            # Kept for compatibility; installs are always forced so reruns
            # are deterministic upgrades.
            ;;
        --help|-h)
            printf '%s\n' "Usage: install.sh [--force]"
            exit 0
            ;;
        *)
            printf '%s\n' "RxyCode installation failed: unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done

version=${RXYCODE_VERSION:-$DEFAULT_VERSION}
case "$version" in
    ''|*[!A-Za-z0-9._-]*)
        printf '%s\n' \
            "RxyCode installation failed: RXYCODE_VERSION contains invalid characters." >&2
        exit 1
        ;;
esac
case "$version" in
    v*) version_ref=$version ;;
    *) version_ref="v$version" ;;
esac

if [ -n "${RXYCODE_SOURCE:-}" ]; then
    source_spec=$RXYCODE_SOURCE
else
    source_spec="git+$REPOSITORY@$version_ref"
fi
source_without_line_breaks=$(printf '%s' "$source_spec" | tr -d '\015\012')
if [ "$source_without_line_breaks" != "$source_spec" ]; then
    printf '%s\n' \
        "RxyCode installation failed: RXYCODE_SOURCE must not contain line breaks." >&2
    exit 1
fi

no_modify_path=0
if [ "${RXYCODE_NO_MODIFY_PATH:-0}" = "1" ]; then
    no_modify_path=1
fi
dry_run=0
if [ "${RXYCODE_INSTALL_DRY_RUN:-0}" = "1" ]; then
    dry_run=1
fi

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return 0
    fi

    for candidate in \
        "${UV_INSTALL_DIR:-}/uv" \
        "${XDG_BIN_HOME:-}/uv" \
        "${HOME:-}/.local/bin/uv" \
        "${HOME:-}/.cargo/bin/uv"
    do
        case "$candidate" in
            /uv) continue ;;
        esac
        if [ -f "$candidate" ] && [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

quote_for_display() {
    value=$1
    case "$value" in
        *[!A-Za-z0-9_./:@+,=-]*)
            escaped=$(printf '%s' "$value" | sed "s/'/'\\\\''/g")
            printf "'%s'" "$escaped"
            ;;
        *)
            printf '%s' "$value"
            ;;
    esac
}

uv_bin=$(find_uv || true)

if [ "$dry_run" -eq 1 ]; then
    if [ -z "$uv_bin" ]; then
        printf '%s\n' \
            "[dry-run] download $UV_INSTALLER_URL to a temporary file and execute it"
        uv_bin=uv
    fi
    printf '%s' "[dry-run] "
    quote_for_display "$uv_bin"
    printf '%s' " tool install --force "
    quote_for_display "$source_spec"
    printf '\n'
    if [ "$no_modify_path" -eq 0 ]; then
        printf '%s' "[dry-run] "
        quote_for_display "$uv_bin"
        printf '%s\n' " tool update-shell"
    fi
    exit 0
fi

temp_dir=''
cleanup() {
    if [ -n "$temp_dir" ] && [ -d "$temp_dir" ]; then
        case "$temp_dir" in
            "${TMPDIR:-/tmp}"/rxycode-uv.*)
                rm -rf -- "$temp_dir"
                ;;
        esac
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -z "$uv_bin" ]; then
    if ! command -v curl >/dev/null 2>&1; then
        printf '%s\n' \
            "RxyCode installation failed: curl is required to install uv." >&2
        exit 1
    fi
    temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/rxycode-uv.XXXXXXXX")
    installer_path="$temp_dir/uv-install.sh"
    printf '%s\n' "Downloading the official uv installer from $UV_INSTALLER_URL"
    curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
        --output "$installer_path" "$UV_INSTALLER_URL"

    installer_bytes=$(wc -c < "$installer_path" | tr -d '[:space:]')
    case "$installer_bytes" in
        ''|*[!0-9]*)
            printf '%s\n' \
                "RxyCode installation failed: could not validate the uv installer size." >&2
            exit 1
            ;;
    esac
    if [ "$installer_bytes" -le 0 ] || [ "$installer_bytes" -gt "$MAX_INSTALLER_BYTES" ]; then
        printf '%s\n' \
            "RxyCode installation failed: the uv installer has an unexpected size." >&2
        exit 1
    fi
    if ! grep -q 'uv' "$installer_path"; then
        printf '%s\n' \
            "RxyCode installation failed: the downloaded file does not look like the uv installer." >&2
        exit 1
    fi

    if [ "$no_modify_path" -eq 1 ]; then
        UV_NO_MODIFY_PATH=1
        export UV_NO_MODIFY_PATH
    fi
    if ! sh "$installer_path"; then
        printf '%s\n' "RxyCode installation failed: the uv installer failed." >&2
        exit 1
    fi
    uv_bin=$(find_uv || true)
fi

if [ -z "$uv_bin" ]; then
    printf '%s\n' \
        "RxyCode installation failed: uv was installed but could not be found." >&2
    exit 1
fi

if ! "$uv_bin" tool install --force "$source_spec"; then
    printf '%s\n' "RxyCode installation failed: uv tool install failed." >&2
    exit 1
fi

if [ "$no_modify_path" -eq 0 ]; then
    if ! "$uv_bin" tool update-shell; then
        printf '%s\n' "RxyCode installation failed: uv could not update PATH." >&2
        exit 1
    fi
fi

printf '%s\n' "RxyCode is installed. Run 'rxycode' from a new terminal."
if [ "$no_modify_path" -eq 1 ]; then
    printf '%s\n' "PATH was not modified; add the uv tool bin directory to PATH manually."
fi
