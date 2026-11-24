#!/bin/bash
# Termux 侧的容器入口：bash phone/proot.sh <容器内脚本> [参数...]
# 用 proot-distro 的 Debian 容器，把所有和路径有关的环境变量一次传进去。
set -u
unset LD_PRELOAD

REPO=$(cd "$(dirname "$0")/.." && pwd)
case "$REPO" in
  /storage/emulated/0/*) REPO=/sdcard/${REPO#/storage/emulated/0/} ;;
  /storage/self/primary/*) REPO=/sdcard/${REPO#/storage/self/primary/} ;;
esac
KIT_DIR=$REPO
[ -f "$KIT_DIR/phone/kit.env" ] && . "$KIT_DIR/phone/kit.env"

PD_DISTRO=${PD_DISTRO:-debian}
WX_HOME=${WX_HOME:-/root/wx}
WX_CONFIG=${WX_CONFIG:-$WX_HOME/config.json}
WX_DISPLAY=${WX_DISPLAY:-:99}
WX_MIRROR=${WX_MIRROR:-}

if ! command -v proot-distro >/dev/null 2>&1; then
  echo "缺 proot-distro。先运行：bash phone/start.sh rootfs" >&2
  exit 1
fi

exec proot-distro login "$PD_DISTRO" -- /usr/bin/env \
  HOME=/root \
  PREFIX=/root \
  WX_HOME="$WX_HOME" \
  WX_CONFIG="$WX_CONFIG" \
  WX_DISPLAY="$WX_DISPLAY" \
  WX_MIRROR="$WX_MIRROR" \
  KIT_DIR="$KIT_DIR" \
  ENTRY_HINT="${ENTRY_HINT:-bash phone/start.sh}" \
  LANG=zh_CN.UTF-8 \
  TERM=xterm-256color \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/bash "$@"
