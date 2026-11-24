#!/bin/bash
# 电脑版（Linux 桌面）入口：本机直接运行，不经过容器。
#   bash pc/start.sh install    装系统依赖、微信 Linux 版、OCR 与程序
#   bash pc/start.sh config     交互式生成人格/模型配置
#   bash pc/start.sh start      启动虚拟屏、微信与 bot
#   bash pc/start.sh stop       全部停止
#   bash pc/start.sh status     看运行状态
#   bash pc/start.sh logs [wx]  看日志
#   bash pc/start.sh wx-check   微信通道自检（不跑循环、不发消息）
#   bash pc/start.sh selfcheck  自检依赖、配置与目录
set -u

PC_DIR=$(cd "$(dirname "$0")" && pwd)
KIT_DIR=$(cd "$PC_DIR/.." && pwd)
[ -f "$PC_DIR/kit.env" ] && . "$PC_DIR/kit.env"

PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
WX_HOME=${WX_HOME:-$PREFIX/wx}
WX_CONFIG=${WX_CONFIG:-$PREFIX/config.json}
WX_DISPLAY=${WX_DISPLAY:-:99}
WX_MIRROR=${WX_MIRROR:-}
LOGS=${LOGS:-$WX_HOME/logs}
export KIT_DIR PREFIX WX_HOME WX_CONFIG WX_DISPLAY WX_MIRROR LOGS
export ENTRY_HINT="bash pc/start.sh"

say() { echo "==> $*"; }

usage() {
  cat <<'EOF'
电脑版（Linux 桌面）入口
  bash pc/start.sh install    装系统依赖、微信 Linux 版、OCR 与程序
  bash pc/start.sh config     交互式生成人格/模型配置
  bash pc/start.sh start      启动虚拟屏、微信与 bot
  bash pc/start.sh stop       全部停止
  bash pc/start.sh status     看运行状态
  bash pc/start.sh logs [wx]  看日志
  bash pc/start.sh wx-check   微信通道自检（不跑循环、不发消息）
  bash pc/start.sh selfcheck  自检依赖、配置与目录
EOF
}

alive() { [ -f "$LOGS/$1.pid" ] && kill -0 "$(cat "$LOGS/$1.pid")" 2>/dev/null; }

bg() {
  local name=$1
  shift
  nohup "$@" >>"$LOGS/$name.log" 2>&1 < /dev/null &
  echo $! >"$LOGS/$name.pid"
}

start_one() {
  local name=$1
  shift
  if alive "$name"; then
    say "$name 已在运行（pid $(cat "$LOGS/$name.pid")）"
    return
  fi
  bg "$name" "$@"
  sleep 2
  if alive "$name"; then
    say "$name 已启动（pid $(cat "$LOGS/$name.pid")，日志 $LOGS/$name.log）"
  else
    echo "!! $name 启动失败，看 $LOGS/$name.log" >&2
    tail -n 15 "$LOGS/$name.log" >&2
    return 1
  fi
}

stop_one() {
  local name=$1 pid
  [ -f "$LOGS/$name.pid" ] || { echo "$name 未在运行"; return 1; }
  pid=$(cat "$LOGS/$name.pid")
  kill "$pid" 2>/dev/null
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null
  rm -f "$LOGS/$name.pid"
  echo "$name 已停止"
  return 0
}

cmd_install() {
  bash "$PC_DIR/install.sh"
}

cmd_config() {
  python3 "$KIT_DIR/shared/setup_config.py" || exit 1
}

cmd_start() {
  mkdir -p "$LOGS" || {
    echo "创建日志目录失败：$LOGS" >&2
    exit 1
  }
  [ -f "$WX_CONFIG" ] || {
    echo "还没有配置。先运行：bash pc/start.sh config" >&2
    exit 1
  }
  [ -f "$PREFIX/wxbot3.py" ] || {
    echo "还没安装程序。先运行：bash pc/start.sh install" >&2
    exit 1
  }
  start_one wx bash "$KIT_DIR/wechat/start-wx.sh"
}

cmd_stop() {
  stop_one wx
  if [ -d "$PREFIX" ] && [ -f "$KIT_DIR/wechat/wxstart.sh" ]; then
    if ! bash "$KIT_DIR/wechat/wxstart.sh" stop; then
      echo "!! 清理本套件进程失败，看 $LOGS/wx.log" >&2
      return 1
    fi
  fi
  say "微信通道相关进程已清理"
}

cmd_status() {
  if alive wx; then
    echo "wx: 运行中 pid=$(cat "$LOGS/wx.pid")  $(tail -n 1 "$LOGS/wx.log" 2>/dev/null | cut -c1-90)"
  else
    echo "wx: 未运行"
  fi
}

cmd_logs() {
  local name=${1:-wx}
  [ -f "$LOGS/$name.log" ] || { echo "没有日志：$LOGS/$name.log" >&2; exit 1; }
  tail -n 60 "$LOGS/$name.log"
}

cmd_wx_check() {
  [ -f "$PREFIX/wxbot3.py" ] || {
    echo "还没安装程序。先运行：bash pc/start.sh install" >&2
    exit 1
  }
  bash "$KIT_DIR/wechat/start-wx.sh" --selfcheck
}

cmd_selfcheck() {
  local fail=0
  say "检查本机依赖"
  for b in python3 ffmpeg xdotool xclip Xvfb x11vnc; do
    if command -v "$b" >/dev/null 2>&1; then
      echo "  PASS $b"
    else
      echo "  FAIL 缺 $b，先运行：bash pc/start.sh install" >&2
      fail=1
    fi
  done
  if python3 -c "import cv2, numpy, rapidocr_onnxruntime" 2>/dev/null; then
    echo "  PASS OCR 依赖"
  else
    echo "  FAIL OCR 依赖缺失，先运行：bash pc/start.sh install" >&2
    fail=1
  fi
  if [ -x /opt/wechat/wechat ] || command -v wechat >/dev/null 2>&1; then
    echo "  PASS 微信客户端"
  else
    echo "  FAIL 没找到微信客户端，先运行：bash pc/start.sh install" >&2
    fail=1
  fi
  if [ -f "$WX_CONFIG" ]; then
    echo "  PASS 配置文件：$WX_CONFIG"
  else
    echo "  FAIL 没有配置：$WX_CONFIG，先运行：bash pc/start.sh config" >&2
    fail=1
  fi
  if [ -f "$PREFIX/wxbot3.py" ]; then
    if python3 -m py_compile "$PREFIX/wxbot3.py" "$PREFIX/wxatspi.py" "$PREFIX/wxmem.py"; then
      echo "  PASS 程序语法"
    else
      echo "  FAIL 程序语法错误，重跑：bash pc/start.sh install" >&2
      fail=1
    fi
  else
    echo "  FAIL 程序未安装，先运行：bash pc/start.sh install" >&2
    fail=1
  fi
  if [ "$fail" = "0" ]; then
    say "自检通过"
  else
    say "自检有失败项"
  fi
  return "$fail"
}

cmd=${1:-}
[ $# -gt 0 ] && shift

case "$cmd" in
  install) cmd_install ;;
  config) cmd_config ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  logs) cmd_logs "${1:-}" ;;
  wx-check) cmd_wx_check ;;
  selfcheck) cmd_selfcheck ;;
  ""|-h|--help|help) usage ;;
  *) echo "未知命令：$cmd" >&2; usage; exit 1 ;;
esac
