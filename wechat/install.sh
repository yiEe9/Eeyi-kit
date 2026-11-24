#!/bin/bash
# 在 proot-distro 的 Debian 容器里安装微信通道：X 环境、微信 Linux 版、OCR/视觉依赖
set -u
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive
KIT_DIR=${KIT_DIR:-/sdcard/phone-ai}
PREFIX=${PREFIX:-/root}
SUDO=${SUDO:-}
WX_HOME=${WX_HOME:-$PREFIX/wx}
WX_CONFIG=${WX_CONFIG:-$WX_HOME/config.json}
ENTRY_HINT=${ENTRY_HINT:-bash phone/start.sh}

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) echo "未知参数：$arg（只支持 --force）" >&2; exit 1 ;;
  esac
done

WECHAT_DEB_URL=${WECHAT_DEB_URL:-https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_arm64.deb}

say() { echo "=== $*"; }
die() { echo "!! $*" >&2; exit 1; }

STAMP=$(date +%Y%m%d-%H%M)
backup_target() {
  local dst=$1 bak
  [ -e "$dst" ] || return 0
  bak="$dst.bak-$STAMP"
  cp -p "$dst" "$bak" || die "备份 $dst 失败"
  say "备份 $dst -> $bak"
}

say "检查已有部署"
EXISTING=""
for f in "$WX_HOME/contacts.json" "$WX_HOME/state.json"; do
  [ -s "$f" ] && EXISTING="$EXISTING $f"
done
if [ -n "$EXISTING" ] && [ "$FORCE" != "1" ]; then
  echo "检测到已有部署，确认要覆盖请加 --force" >&2
  echo "已有数据：$EXISTING" >&2
  echo "程序文件覆盖前会备份成 <文件>.bak-$STAMP" >&2
  exit 1
fi

apt_first_of() {
  local p
  for p in "$@"; do
    if $SUDO apt-get install -y --no-install-recommends "$p"; then
      return 0
    fi
  done
  return 1
}

say "安装依赖（Xvfb / VNC / 截图 / 点击 / OCR 运行时）"
$SUDO apt-get update || die "apt-get update 失败"
$SUDO apt-get install -y --no-install-recommends \
  xvfb x11vnc xdotool xclip ffmpeg curl ca-certificates procps fonts-wqy-zenhei \
  python3 python3-pip python3-gi gir1.2-atspi-2.0 \
  libnss3 libgbm1 libxkbcommon0 libxss1 libxtst6 \
  libx11-xcb1 libnotify4 libsecret-1-0 libdbus-1-3 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 \
  libxkbcommon-x11-0 libxcomposite1 libxdamage1 libxrandr2 libxfixes3 \
  libpango-1.0-0 libcairo2 libxrender1 libxi6 \
  || die "依赖装不上"
apt_first_of libgtk-3-0t64 libgtk-3-0 || die "GTK 运行库装不上"
apt_first_of libasound2t64 libasound2 || die "音频运行库装不上"
apt_first_of libatspi2.0-0t64 libatspi2.0-0 || die "无障碍运行库装不上"
apt_first_of libcups2t64 libcups2 || die "打印运行库装不上"

say "安装微信 Linux 版（arm64）"
if [ -f "$KIT_DIR/WeChatLinux_arm64.deb" ]; then
  cp "$KIT_DIR/WeChatLinux_arm64.deb" /tmp/wechat.deb
else
  curl -fL --retry 3 -o /tmp/wechat.deb "$WECHAT_DEB_URL" \
    || die "微信安装包下载失败，可手动放到 $KIT_DIR/WeChatLinux_arm64.deb"
fi
$SUDO dpkg -i --force-depends /tmp/wechat.deb
$SUDO apt-get install -y -f || die "补齐微信依赖失败"
[ -x /opt/wechat/wechat ] || command -v wechat >/dev/null || die "没找到微信可执行文件"

say "安装 OCR 与图像依赖（arm64 上会装 onnxruntime，比较慢）"
pip3 install --break-system-packages --no-cache-dir \
  rapidocr-onnxruntime opencv-python-headless \
  || pip3 install --no-cache-dir rapidocr-onnxruntime opencv-python-headless \
  || die "pip 安装失败"
python3 -c "import cv2, numpy, rapidocr_onnxruntime" || die "OCR 依赖导入失败"

say "部署程序"
mkdir -p "$PREFIX" "$WX_HOME" "$WX_HOME/history" "$WX_HOME/memory"
backup_target "$PREFIX/wxbot3.py"
backup_target "$PREFIX/wxatspi.py"
backup_target "$PREFIX/wxmem.py"
backup_target "$PREFIX/wxtest.py"
backup_target "$PREFIX/wxcontacts.py"
backup_target "$PREFIX/wxstart.sh"
cp "$KIT_DIR/wechat/wxbot3.py" "$PREFIX/wxbot3.py" || die "复制 wxbot3.py 失败"
cp "$KIT_DIR/wechat/wxatspi.py" "$PREFIX/wxatspi.py" || die "复制 wxatspi.py 失败"
cp "$KIT_DIR/wechat/wxmem.py" "$PREFIX/wxmem.py" || die "复制 wxmem.py 失败"
cp "$KIT_DIR/wechat/wxtest.py" "$PREFIX/wxtest.py" || die "复制 wxtest.py 失败"
cp "$KIT_DIR/wechat/contacts.py" "$PREFIX/wxcontacts.py" || die "复制 contacts.py 失败"
cp "$KIT_DIR/wechat/wxstart.sh" "$PREFIX/wxstart.sh" || die "复制 wxstart.sh 失败"
chmod +x "$PREFIX/wxstart.sh"
[ -f "$WX_HOME/contacts.json" ] || echo "{}" > "$WX_HOME/contacts.json"
python3 -m py_compile "$PREFIX/wxbot3.py" "$PREFIX/wxatspi.py" "$PREFIX/wxmem.py" "$PREFIX/wxtest.py" \
  || die "语法检查失败"
printf 'installed %s\nKIT_DIR=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$KIT_DIR" > "$WX_HOME/.kit" \
  || die "写标记文件失败：$WX_HOME/.kit"

cat <<EOF

微信通道装完了。接下来：
  1. 先把要聊的人加进白名单：
       python3 $PREFIX/wxcontacts.py add 备注名 owner
  2. bash phone/start.sh config   # 写人格与模型（所有能力默认开启）
  3. bash phone/start.sh start    # 起虚拟屏 + 微信 + bot，VNC 端口 127.0.0.1:5900
  4. 用 VNC 客户端连上看微信登录页，扫码/手机确认登录
  5. 自检（不进循环、不发消息）：bash phone/start.sh wx-check
EOF
