#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${VENV_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
[[ -x "$VENV_PYTHON" ]] || VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
RUN_DIR="$PROJECT_ROOT/data/run"
PID_FILE="$RUN_DIR/jarvis.pid"
DISABLED_FILE="$RUN_DIR/disabled"
LOG_FILE="$PROJECT_ROOT/logs/jarvis.log"

mkdir -p "$RUN_DIR" "$PROJECT_ROOT/logs"

usage() {
    printf '%s\n' "Usage: $0 {start|stop|restart|disable|enable|status|health|doctor|logs|service-install|service-uninstall}"
}

pid_is_running() {
    [[ -s "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null
}

require_python() {
    if [[ ! -x "$VENV_PYTHON" ]]; then
        printf '%s\n' "BLOCKED: missing $VENV_PYTHON; run scripts/install.sh" >&2
        exit 1
    fi
}

start() {
    require_python
    if [[ -e "$DISABLED_FILE" ]]; then
        printf '%s\n' 'JARVIS is disabled; run enable first.' >&2
        return 1
    fi
    if pid_is_running; then
        printf 'JARVIS already running (pid %s)\n' "$(cat "$PID_FILE")"
        return 0
    fi
    rm -f "$PID_FILE"
    nohup "$VENV_PYTHON" -m app.main --foreground >>"$LOG_FILE" 2>&1 &
    printf '%s\n' "$!" > "$PID_FILE"
    sleep 1
    if pid_is_running; then
        printf 'JARVIS started (pid %s)\n' "$(cat "$PID_FILE")"
        return 0
    fi
    printf '%s\n' 'JARVIS failed to remain running; inspect logs/jarvis.log.' >&2
    rm -f "$PID_FILE"
    return 1
}

stop() {
    if ! pid_is_running; then
        rm -f "$PID_FILE"
        printf '%s\n' 'JARVIS is stopped.'
        return 0
    fi
    local pid deadline
    pid="$(cat "$PID_FILE")"
    kill -TERM "$pid" 2>/dev/null || true
    deadline=$((SECONDS + 10))
    while kill -0 "$pid" 2>/dev/null && (( SECONDS < deadline )); do
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        printf '%s\n' 'JARVIS did not stop within 10 seconds.' >&2
        return 1
    fi
    rm -f "$PID_FILE"
    printf '%s\n' 'JARVIS stopped.'
}

status() {
    if [[ -e "$DISABLED_FILE" ]]; then
        printf '%s\n' 'JARVIS: disabled'
    elif pid_is_running; then
        printf 'JARVIS: running (pid %s)\n' "$(cat "$PID_FILE")"
    else
        rm -f "$PID_FILE"
        printf '%s\n' 'JARVIS: stopped'
    fi
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    restart) stop && start ;;
    disable) stop && : > "$DISABLED_FILE" && printf '%s\n' 'JARVIS disabled.' ;;
    enable) rm -f "$DISABLED_FILE" && printf '%s\n' 'JARVIS enabled.' ;;
    status) status ;;
    health) require_python; exec "$PROJECT_ROOT/scripts/healthcheck.sh" ;;
    doctor) exec "$PROJECT_ROOT/scripts/diagnostics.sh" ;;
    logs) [[ -f "$LOG_FILE" ]] && exec tail -n "${JARVIS_LOG_LINES:-100}" "$LOG_FILE" || { printf '%s\n' 'JARVIS log is empty.'; exit 0; } ;;
    service-install)
        require_python
        service_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
        service_file="$service_dir/jarvis.service"
        mkdir -p "$service_dir"
        sed -e "s|@VENV_PYTHON@|$VENV_PYTHON|g" -e "s|%h/JARVIS|$PROJECT_ROOT|g" \
            "$PROJECT_ROOT/packaging/jarvis.service.in" > "$service_file"
        if command -v systemctl >/dev/null 2>&1; then
            if ! systemctl --user daemon-reload || ! systemctl --user enable jarvis.service; then
                printf '%s\n' 'BLOCKED: user systemd is unavailable; service file was rendered but not enabled.' >&2
                exit 1
            fi
        fi
        printf 'Installed user service: %s\n' "$service_file"
        ;;
    service-uninstall)
        service_file="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/jarvis.service"
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --user disable --now jarvis.service 2>/dev/null || true
            systemctl --user daemon-reload
        fi
        rm -f "$service_file"
        printf 'Removed user service: %s\n' "$service_file"
        ;;
    *) usage; exit 2 ;;
esac