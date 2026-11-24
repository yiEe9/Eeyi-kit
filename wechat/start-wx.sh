#!/bin/bash
# 启动微信通道：虚拟屏 + 微信 + VNC + bot。整个 proot 进程常驻。
set -u
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PREFIX=${PREFIX:-/root}
WX_HOME=${WX_HOME:-$PREFIX/wx}
WX_CONFIG=${WX_CONFIG:-$WX_HOME/config.json}
export PREFIX WX_HOME WX_CONFIG
export DISPLAY=${WX_DISPLAY:-:99}
export LANG=zh_CN.UTF-8
export TZ=Asia/Shanghai
mkdir -p /tmp/.X11-unix "$WX_HOME"

if [ ! -f "$WX_CONFIG" ]; then
  echo "找不到配置：$WX_CONFIG" >&2
  echo "先运行：${ENTRY_HINT:-bash phone/start.sh} config" >&2
  exit 1
fi
if [ ! -f "$PREFIX/wxbot3.py" ]; then
  echo "找不到程序：$PREFIX/wxbot3.py" >&2
  echo "先运行：${ENTRY_HINT:-bash phone/start.sh} install" >&2
  exit 1
fi

say() { echo "=== $*"; }

xvfb_running() { pgrep -f "Xvfb $DISPLAY " >/dev/null 2>&1; }
vnc_running() { pgrep -f "x11vnc -display $DISPLAY" >/dev/null 2>&1; }
wechat_running() { pgrep -f "opt/wechat/wechat" >/dev/null 2>&1 || pgrep -x wechat >/dev/null 2>&1; }

if [ ! -f "$WX_HOME/.kit" ]; then
  if xvfb_running || vnc_running || wechat_running; then
    echo "检测到已在运行的微信/虚拟屏，可能属于另一套部署，拒绝启动" >&2
    echo "如果确认是本套件的旧进程，先运行：bash $PREFIX/wxstart.sh stop" >&2
    exit 1
  fi
fi

if ! xvfb_running; then
  say "启动虚拟屏 $DISPLAY"
  Xvfb "$DISPLAY" -screen 0 1280x960x24 -nolisten tcp >/tmp/xvfb-wx.log 2>&1 &
  echo $! > "$WX_HOME/xvfb.pid"
  sleep 2
fi

if ! vnc_running; then
  say "启动 VNC（127.0.0.1:5900）"
  x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 127.0.0.1 -rfbport 5900 \
    >/tmp/x11vnc.log 2>&1 &
  echo $! > "$WX_HOME/vnc.pid"
  sleep 1
fi

if ! wechat_running; then
  say "启动微信"
  if [ -x /opt/wechat/wechat ]; then
    setsid nohup /opt/wechat/wechat >>/tmp/wechat.log 2>&1 < /dev/null &
  else
    setsid nohup wechat >>/tmp/wechat.log 2>&1 < /dev/null &
  fi
  echo $! > "$WX_HOME/wechat.pid"
  sleep 5
fi

if [ "${1:-}" = "--selfcheck" ]; then
  say "自检（不会发消息）"
  exec python3 -u "$PREFIX/wxbot3.py" --selfcheck
fi

say "启动 bot（窗口未登录时会空转等待，不会发消息）"
exec bash "$PREFIX/wxstart.sh" --fg --loop --send
