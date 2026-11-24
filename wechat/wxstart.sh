#!/bin/bash
# 微信 bot 启动/停止：只管理本套件启动的进程
#   bash wxstart.sh --loop --send      后台起一个
#   bash wxstart.sh --fg --loop --send 前台起（给 start-wx.sh 用）
#   bash wxstart.sh stop               停本套件的 bot、微信、Xvfb、VNC
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PREFIX=${PREFIX:-/root}
WX_HOME=${WX_HOME:-$PREFIX/wx}
WX_CONFIG=${WX_CONFIG:-$WX_HOME/config.json}
export PREFIX WX_HOME WX_CONFIG
export DISPLAY=${WX_DISPLAY:-:99}
export TZ=Asia/Shanghai
WX_PY=${WX_PY:-$PREFIX/wxbot3.py}
export WX_PY
cd "$PREFIX" || exit 1

PIDFILE="$WX_HOME/wxbot.pid"

pid_alive() {
    local pid
    [ -f "$1" ] || return 1
    pid=$(cat "$1" 2>/dev/null)
    case "$pid" in ""|*[!0-9]*) return 1 ;; esac
    kill -0 "$pid" 2>/dev/null
}

stop_pidfile() {
    local name=$1 file=$2 pid
    [ -f "$file" ] || return 1
    pid=$(cat "$file" 2>/dev/null)
    case "$pid" in ""|*[!0-9]*) rm -f "$file"; return 1 ;; esac
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        for i in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$pid" 2>/dev/null
        echo "stopped $name pid=$pid"
    fi
    rm -f "$file"
    return 0
}

stop_bot() {
    local pid pids found cmd
    if pid_alive "$PIDFILE"; then
        stop_pidfile bot "$PIDFILE"
        return 0
    fi
    rm -f "$PIDFILE"
    pids=$(pgrep -f -- "$WX_PY" 2>/dev/null || true)
    found=""
    for pid in $pids; do
        cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
        # 只认 python 进程 + 本套件绝对路径，免得误杀命令行里恰好带这个路径的编辑器/日志命令
        case "$cmd" in
            *python*"$WX_PY"*) found="$found $pid" ;;
        esac
    done
    [ -n "$found" ] || { echo "没有在运行的 $WX_PY"; return 0; }
    # 只按绝对路径精确匹配，不碰别的 wxbot3.py 部署
    for pid in $found; do kill "$pid" 2>/dev/null; done
    sleep 2
    for pid in $found; do kill -9 "$pid" 2>/dev/null; done
    echo "stopped pid=$(echo $found | tr ' ' ',')"
}

if [ "${1:-}" = "stop" ]; then
    stop_bot
    stop_pidfile wechat "$WX_HOME/wechat.pid"
    stop_pidfile vnc "$WX_HOME/vnc.pid"
    stop_pidfile xvfb "$WX_HOME/xvfb.pid"
    exit 0
fi

stop_bot

FG=0
if [ "${1:-}" = "--fg" ]; then FG=1; shift; fi

mkdir -p "$WX_HOME/logs"

if [ "$FG" = "1" ]; then
    python3 -u "$WX_PY" "$@" &
    child=$!
    echo "$child" > "$PIDFILE"
    term() { kill "$child" 2>/dev/null; }
    trap term TERM INT HUP
    wait "$child"
    rc=$?
    rm -f "$PIDFILE"
    exit "$rc"
fi

nohup python3 -u "$WX_PY" "$@" > "$WX_HOME/logs/wx.log" 2>&1 < /dev/null &
child=$!
echo "$child" > "$PIDFILE"
sleep 4
if kill -0 "$child" 2>/dev/null; then
    echo "started pid=$child mode=$*"
else
    rm -f "$PIDFILE"
    echo "启动失败，看 $WX_HOME/logs/wx.log" >&2
    exit 1
fi
