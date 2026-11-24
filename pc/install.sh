#!/bin/bash
# 电脑版（Linux 桌面）安装脚本：系统依赖、微信 Linux 版、OCR 与微信通道程序。
# 支持 Debian 12 / Ubuntu 24.04 x86_64，普通用户 + sudo 运行。
set -u

PC_DIR=$(cd "$(dirname "$0")" && pwd)
KIT_DIR=$(cd "$PC_DIR/.." && pwd)
[ -f "$PC_DIR/kit.env" ] && . "$PC_DIR/kit.env"

PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
WX_HOME=${WX_HOME:-$PREFIX/wx}
WX_CONFIG=${WX_CONFIG:-$PREFIX/config.json}
WECHAT_DEB_URL=${WECHAT_DEB_URL:-https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb}

say() { echo "=== $*"; }
die() { echo "!! $*" >&2; exit 1; }

[ "$(uname -m)" = "x86_64" ] || die "电脑版只支持 x86_64（当前 $(uname -m)），手机请用手机版入口"
if [ "$(id -u)" = "0" ]; then
  SUDO=${SUDO:-}
else
  command -v sudo >/dev/null 2>&1 || die "需要 sudo 安装系统依赖与微信"
  SUDO=${SUDO:-sudo}
fi
PREFIX_NEW=0
[ -d "$PREFIX" ] || PREFIX_NEW=1
mkdir -p "$PREFIX" || die "创建 $PREFIX 失败"

apt_first_of() {
  local p
  for p in "$@"; do
    if $SUDO apt-get install -y --no-install-recommends "$p"; then
      return 0
    fi
  done
  return 1
}

say "安装系统依赖"
$SUDO apt-get update || die "apt-get update 失败，检查网络或换软件源"
$SUDO apt-get install -y --no-install-recommends \
  xvfb x11vnc xdotool xclip ffmpeg python3 python3-pip curl ca-certificates \
  python3-gi gir1.2-atspi-2.0 \
  libnss3 libnotify4 libsecret-1-0 libgbm1 libdbus-1-3 libxss1 libxtst6 \
  libx11-xcb1 libxkbcommon0 libxkbcommon-x11-0 libxcomposite1 libxdamage1 libxrandr2 \
  libxfixes3 libxrender1 libxi6 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libpango-1.0-0 libcairo2 libgl1 libegl1 \
  libfontconfig1 libfreetype6 libglib2.0-0 \
  || die "系统依赖装不上，检查网络或软件源"
apt_first_of libasound2t64 libasound2 || die "音频运行库 libasound2 装不上"
apt_first_of libgtk-3-0t64 libgtk-3-0 || die "GTK 运行库装不上"
apt_first_of libatspi2.0-0t64 libatspi2.0-0 || die "无障碍运行库 libatspi2.0 装不上"
apt_first_of libcups2t64 libcups2 || die "打印运行库 libcups2 装不上"
apt_first_of fonts-wqy-zenhei fonts-noto-cjk || die "中文字体装不上（fonts-wqy-zenhei / fonts-noto-cjk）"

say "安装微信 Linux 版（amd64）"
if [ -f "$KIT_DIR/WeChatLinux_x86_64.deb" ]; then
  cp "$KIT_DIR/WeChatLinux_x86_64.deb" /tmp/wechat.deb || die "复制本地微信安装包失败"
else
  curl -fL --retry 3 -o /tmp/wechat.deb "$WECHAT_DEB_URL" \
    || die "微信安装包下载失败，可手动放到 $KIT_DIR/WeChatLinux_x86_64.deb"
fi
$SUDO dpkg -i /tmp/wechat.deb || $SUDO apt-get install -y -f || die "微信依赖装不上"
[ -x /opt/wechat/wechat ] || command -v wechat >/dev/null || die "没找到微信可执行文件"

say "部署微信通道程序"
mkdir -p "$WX_HOME" "$WX_HOME/history" "$WX_HOME/memory" || die "创建 $WX_HOME 失败"
[ "$PREFIX_NEW" = "1" ] && chmod 700 "$PREFIX"
cp "$KIT_DIR/wechat/wxbot3.py" "$PREFIX/wxbot3.py" || die "复制 wxbot3.py 失败"
cp "$KIT_DIR/wechat/wxatspi.py" "$PREFIX/wxatspi.py" || die "复制 wxatspi.py 失败"
cp "$KIT_DIR/wechat/wxmem.py" "$PREFIX/wxmem.py" || die "复制 wxmem.py 失败"
cp "$KIT_DIR/wechat/wxtest.py" "$PREFIX/wxtest.py" || die "复制 wxtest.py 失败"
cp "$KIT_DIR/wechat/contacts.py" "$PREFIX/wxcontacts.py" || die "复制 contacts.py 失败"
cp "$KIT_DIR/wechat/wxstart.sh" "$PREFIX/wxstart.sh" || die "复制 wxstart.sh 失败"
chmod +x "$PREFIX/wxstart.sh"
[ -f "$WX_HOME/contacts.json" ] || echo "{}" > "$WX_HOME/contacts.json"
python3 -m py_compile "$PREFIX/wxbot3.py" "$PREFIX/wxatspi.py" "$PREFIX/wxmem.py" "$PREFIX/wxtest.py" \
  || die "微信通道语法检查失败"

say "安装 OCR 与图像依赖"
python3 -m pip install --user --break-system-packages --no-cache-dir \
  rapidocr-onnxruntime opencv-python-headless \
  || die "pip 安装 rapidocr-onnxruntime / opencv-python-headless 失败"
python3 -c "import cv2, numpy, rapidocr_onnxruntime" || die "OCR 依赖导入失败"
printf 'installed %s\nKIT_DIR=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$KIT_DIR" > "$WX_HOME/.kit" \
  || die "写标记文件失败：$WX_HOME/.kit"

cat <<EOF

装完了。接下来：
  1. cp persona/TEMPLATE.md persona/persona.txt，填人格（可选 persona/owner.txt、persona/other.txt）
  2. bash pc/start.sh config       # 写人格与模型（所有能力默认开启）
  3. bash pc/start.sh start        # 起虚拟屏与微信
  4. 用 VNC 客户端连 127.0.0.1:5900，扫码/手机确认登录微信
  5. bash pc/start.sh wx-check     # 自检（不跑循环、不发消息）
  6. bash pc/start.sh status       # 看运行状态
EOF
