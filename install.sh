#!/usr/bin/env sh

set -eu

DEFAULT_VERSION="1.2.2"
REPOSITORY="https://github.com/xin-yi33/RxyCode.git"
UV_INSTALLER_URL="https://astral.sh/uv/install.sh"
BUN_INSTALLER_URL="https://bun.sh/install"
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
# Reject CR/LF without coreutils — dry-run tests isolate PATH to a fake bin.
cr=$(printf '\015')
case "$source_spec" in
*"
"*|*"$cr"*)
    printf '%s\n' \
        "RxyCode installation failed: RXYCODE_SOURCE must not contain line breaks." >&2
    exit 1
    ;;
esac

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

find_bun() {
    if command -v bun >/dev/null 2>&1; then
        command -v bun
        return 0
    fi

    for candidate in \
        "${BUN_INSTALL:-}/bin/bun" \
        "${HOME:-}/.bun/bin/bun"
    do
        case "$candidate" in
            /bin/bun) continue ;;
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

find_opentui_app_dir() {
    uv_bin=$1
    tools_root=$("$uv_bin" tool dir 2>/dev/null | head -n 1 || true)
    if [ -z "$tools_root" ]; then
        return 1
    fi
    tool_root="$tools_root/rxycode"
    for python in \
        "$tool_root/bin/python" \
        "$tool_root/bin/python3" \
        "$tool_root/Scripts/python.exe"
    do
        if [ -x "$python" ] || [ -f "$python" ]; then
            app_dir=$(
                "$python" -c \
"from pathlib import Path; import RxyCode.RxyCode1_1_0 as m; print(Path(m.__file__).resolve().parent / 'frontend' / 'opentui-app')" \
                    2>/dev/null || true
            )
            if [ -n "$app_dir" ] && [ -f "$app_dir/package.json" ]; then
                printf '%s\n' "$app_dir"
                return 0
            fi
        fi
    done
    return 1
}

uv_bin=$(find_uv || true)
bun_bin=$(find_bun || true)

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
    if [ -z "$bun_bin" ]; then
        printf '%s\n' \
            "[dry-run] download $BUN_INSTALLER_URL to a temporary file and execute it"
        bun_bin=bun
    fi
    printf '%s' "[dry-run] "
    quote_for_display "$bun_bin"
    printf '%s\n' " install  # in packaged frontend/opentui-app"
    exit 0
fi

temp_dir=''
cleanup() {
    if [ -n "$temp_dir" ] && [ -d "$temp_dir" ]; then
        case "$temp_dir" in
            "${TMPDIR:-/tmp}"/rxycode-uv.*|"${TMPDIR:-/tmp}"/rxycode-bun.*)
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

if [ -z "${RXYCODE_SKIP_BUN_INSTALL:-}" ] || [ "${RXYCODE_SKIP_BUN_INSTALL}" != "1" ]; then
    if [ -z "$bun_bin" ]; then
        if ! command -v curl >/dev/null 2>&1; then
            printf '%s\n' \
                "Warning: curl is required to install Bun; OpenTUI may fall back to Ink." >&2
        else
            temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/rxycode-bun.XXXXXXXX")
            installer_path="$temp_dir/bun-install.sh"
            printf '%s\n' "Downloading the official Bun installer from $BUN_INSTALLER_URL"
            curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
                --output "$installer_path" "$BUN_INSTALLER_URL"
            installer_bytes=$(wc -c < "$installer_path" | tr -d '[:space:]')
            case "$installer_bytes" in
                ''|*[!0-9]*)
                    printf '%s\n' \
                        "Warning: could not validate the Bun installer size." >&2
                    ;;
                *)
                    if [ "$installer_bytes" -gt 0 ] \
                        && [ "$installer_bytes" -le "$MAX_INSTALLER_BYTES" ] \
                        && grep -q 'bun' "$installer_path"
                    then
                        if sh "$installer_path"; then
                            bun_bin=$(find_bun || true)
                        else
                            printf '%s\n' \
                                "Warning: the Bun installer failed; OpenTUI may fall back to Ink." >&2
                        fi
                    else
                        printf '%s\n' \
                            "Warning: Bun installer looked invalid; OpenTUI may fall back to Ink." >&2
                    fi
                    ;;
            esac
        fi
    fi

    if [ -n "$bun_bin" ]; then
        if opentui_dir=$(find_opentui_app_dir "$uv_bin"); then
            printf '%s\n' "Installing OpenTUI frontend dependencies with Bun..."
            if ! (cd "$opentui_dir" && "$bun_bin" install); then
                printf '%s\n' \
                    "Warning: bun install failed in $opentui_dir; OpenTUI may not start until fixed." >&2
            fi
        else
            printf '%s\n' \
                "Warning: could not locate packaged OpenTUI app dir." >&2
        fi
    else
        printf '%s\n' \
            "Warning: Bun was not found. OpenTUI needs Bun; Ink fallback will be used until Bun is installed." >&2
    fi
fi

printf '%s\n' "RxyCode is installed. Run 'rxycode' from a new terminal."
if [ "$no_modify_path" -eq 1 ]; then
    printf '%s\n' "PATH was not modified; add the uv tool bin directory to PATH manually."
fi
if [ -z "${RXYCODE_SKIP_BUN_INSTALL:-}" ] || [ "${RXYCODE_SKIP_BUN_INSTALL}" != "1" ]; then
    if [ -n "$bun_bin" ]; then
        printf '%s\n' "OpenTUI uses Bun ($bun_bin). Open a new terminal if 'bun' is not on PATH yet."
    fi
fi
