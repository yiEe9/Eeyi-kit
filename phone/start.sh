#!/bin/bash
# 手机版入口（在 Termux 里运行）
#   bash phone/start.sh rootfs     装 proot-distro 并建 Debian 容器（只做一次）
#   bash phone/start.sh install    容器内装微信、X 环境与 OCR 依赖
#   bash phone/start.sh config     交互式生成人格/模型配置
#   bash phone/start.sh start      启动虚拟屏、微信与 bot
#   bash phone/start.sh stop       全部停止
#   bash phone/start.sh status     看运行状态
#   bash phone/start.sh logs [wx]  看日志
#   bash phone/start.sh wx-check   微信通道自检（不跑循环、不发消息）
#   bash phone/start.sh selfcheck  自检依赖、配置与目录
set -u

TERMUX_PREFIX=${TERMUX_PREFIX:-${PREFIX:-/data/data/com.termux/files/usr}}
REPO=$(cd "$(dirname "$0")/.." && pwd)
case "$REPO" in
  /storage/emulated/0/*) REPO=/sdcard/${REPO#/storage/emulated/0/} ;;
  /storage/self/primary/*) REPO=/sdcard/${REPO#/storage/self/primary/} ;;
esac
KIT_DIR=$REPO
[ -f "$KIT_DIR/phone/kit.env" ] && . "$KIT_DIR/phone/kit.env"

PD_DISTRO=${PD_DISTRO:-debian}
PD_ROOTFS=${PD_ROOTFS:-$TERMUX_PREFIX/var/lib/proot-distro/installed-rootfs/$PD_DISTRO}
WX_HOME=${WX_HOME:-/root/wx}
WX_CONFIG=${WX_CONFIG:-$WX_HOME/config.json}
WX_DISPLAY=${WX_DISPLAY:-:99}
WX_MIRROR=${WX_MIRROR:-}
LOGS=${LOGS:-$PD_ROOTFS$WX_HOME/logs}
export KIT_DIR PD_DISTRO PD_ROOTFS WX_HOME WX_CONFIG WX_DISPLAY WX_MIRROR LOGS
export ENTRY_HINT="bash phone/start.sh"

say() { echo "==> $*"; }
die() { echo "!! $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
手机版入口（在 Termux 里运行）
  bash phone/start.sh rootfs     装 proot-distro 并建 Debian 容器（只做一次）
  bash phone/start.sh install    容器内装微信、X 环境与 OCR 依赖
  bash phone/start.sh config     交互式生成人格/模型配置
  bash phone/start.sh start      启动虚拟屏、微信与 bot
  bash phone/start.sh stop       全部停止
  bash phone/start.sh status     看运行状态
  bash phone/start.sh logs [wx]  看日志
  bash phone/start.sh wx-check   微信通道自检（不跑循环、不发消息）
  bash phone/start.sh selfcheck  自检依赖、配置与目录
EOF
}

need_rootfs() {
  command -v proot-distro >/dev/null 2>&1 || {
    echo "缺 proot-distro。先运行：bash phone/start.sh rootfs" >&2
    exit 1
  }
  [ -d "$PD_ROOTFS/usr" ] || {
    echo "找不到 Debian 容器：$PD_ROOTFS" >&2
    echo "先运行：bash phone/start.sh rootfs" >&2
    exit 1
  }
  mkdir -p "$LOGS" || die "创建日志目录失败：$LOGS"
}

in_proot() { bash "$KIT_DIR/phone/proot.sh" "$@"; }

alive() { [ -f "$LOGS/$1.pid" ] && kill -0 "$(cat "$LOGS/$1.pid")" 2>/dev/null; }

bg() {
  local name=$1
  shift
  nohup bash "$KIT_DIR/phone/proot.sh" "$@" >>"$LOGS/$name.log" 2>&1 < /dev/null &
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

cmd_rootfs() {
  if ! command -v proot-distro >/dev/null 2>&1; then
    say "安装 proot-distro"
    pkg install -y proot-distro || die "pkg install proot-distro 失败"
  fi
  if proot-distro login "$PD_DISTRO" -- true >/dev/null 2>&1; then
    say "Debian 容器已可用：$PD_DISTRO"
    return
  fi
  say "安装 Debian 容器（下载 rootfs，视网络可能十几分钟）"
  proot-distro install "$PD_DISTRO" || die "proot-distro install $PD_DISTRO 失败"
  proot-distro login "$PD_DISTRO" -- true || die "容器装好了但 login 不可用"
  say "容器就绪：$PD_DISTRO"
}

cmd_install() {
  need_rootfs
  in_proot "$KIT_DIR/wechat/install.sh" "$@"
}

cmd_config() {
  need_rootfs
  in_proot -c "python3 '$KIT_DIR/shared/setup_config.py'"
}

cmd_start() {
  need_rootfs
  [ -f "$PD_ROOTFS$WX_CONFIG" ] || {
    echo "还没有配置。先运行：bash phone/start.sh config" >&2
    exit 1
  }
  start_one wx "$KIT_DIR/wechat/start-wx.sh"
}

cmd_stop() {
  stop_one wx
  if ! command -v proot-distro >/dev/null 2>&1 || [ ! -d "$PD_ROOTFS/usr" ]; then
    echo "!! 找不到 proot-distro 或 Debian 容器，容器内的微信/Xvfb/VNC 未清理" >&2
    return 1
  fi
  if ! in_proot "$KIT_DIR/wechat/wxstart.sh" stop; then
    echo "!! 容器内进程清理失败，看 $LOGS/wx.log" >&2
    return 1
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
  need_rootfs
  in_proot "$KIT_DIR/wechat/start-wx.sh" --selfcheck
}

cmd_selfcheck() {
  need_rootfs
  local fail=0
  say "检查容器内依赖"
  if in_proot -c "command -v python3 >/dev/null && command -v ffmpeg >/dev/null && command -v xdotool >/dev/null && command -v xclip >/dev/null && python3 -c 'import cv2, numpy, rapidocr_onnxruntime'"; then
    echo "  PASS python3 / ffmpeg / xdotool / xclip / OCR"
  else
    echo "  FAIL 容器依赖不全，先运行：bash phone/start.sh install" >&2
    fail=1
  fi
  if in_proot -c "[ -x /opt/wechat/wechat ] || command -v wechat >/dev/null"; then
    echo "  PASS 微信客户端"
  else
    echo "  FAIL 没找到微信客户端，先运行：bash phone/start.sh install" >&2
    fail=1
  fi
  if [ -f "$PD_ROOTFS$WX_CONFIG" ]; then
    echo "  PASS 配置文件：$WX_CONFIG"
  else
    echo "  FAIL 没有配置：$WX_CONFIG，先运行：bash phone/start.sh config" >&2
    fail=1
  fi
  if in_proot -c "python3 -m py_compile /root/wxbot3.py /root/wxatspi.py /root/wxmem.py"; then
    echo "  PASS 程序语法"
  else
    echo "  FAIL 程序缺失或语法错误，先运行：bash phone/start.sh install" >&2
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
  rootfs) cmd_rootfs ;;
  install) cmd_install "$@" ;;
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
