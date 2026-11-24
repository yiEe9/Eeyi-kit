# 安装

两版共用 `persona/`、`wechat/`、`shared/`，入口不同：手机版 `phone/start.sh`，电脑版 `pc/start.sh`。

---

# 一、手机版（Termux + proot-distro）

## 0. 前置检查

- `uname -m` 是 `aarch64`（arm64 手机）。
- 存储剩 4 GB 以上：Debian rootfs、微信 deb（约 212 MB）、OCR 模型、聊天数据。
- 不需要 root；全部在 Termux 用户空间里。

## 1. Termux

装官方 Termux 或 ZeroTermux，打开后：

```bash
termux-setup-storage
pkg update
pkg install proot-distro nano
termux-wake-lock
```

把整个 `phone-ai-kit` 目录放到 Termux 家目录，例如 `~/phone-ai-kit`。放 `/sdcard` 也能跑，但需要 proot-distro 能访问共享存储；家目录最稳。

## 2. 建 Debian 容器

```bash
cd ~/phone-ai-kit
bash phone/start.sh rootfs
```

这一步会：

1. 没有 `proot-distro` 就 `pkg install -y proot-distro`；
2. `proot-distro install debian`；
3. 用 `proot-distro login debian -- true` 确认容器可用。

rootfs 下载慢就等；失败常见原因是网络、存储不足。重复运行会直接跳过。

## 3. 装微信通道

```bash
bash phone/start.sh install
```

容器内依次做：

1. `apt-get install` Xvfb、x11vnc、xdotool、xclip、ffmpeg、GTK/ASound/ATSPI、`python3-gi` 等；`libasound2` 会先试 `libasound2t64` 再退回旧名，GTK/atspi/cups 同理。
2. 下载并 `dpkg -i` 安装微信 Linux arm64：
   `https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_arm64.deb`
3. `pip3 install rapidocr-onnxruntime opencv-python-headless`。
4. 把 `wxbot3.py`、`wxatspi.py`、`wxmem.py`、`wxtest.py`、`wxcontacts.py`、`wxstart.sh` 复制到 `/root`；覆盖已有文件前先备份成 `<文件>.bak-时间`。
5. 建数据目录 `/root/wx` 和空的 `contacts.json`；如果 `contacts.json` 或 `state.json` 已存在且非空，默认拒绝安装，确认覆盖要加 `--force`。
6. 安装成功后写 `$WX_HOME/.kit` 标记。

离线安装：把 `WeChatLinux_arm64.deb` 放到工程根目录，脚本会优先用本地文件。

## 4. 写人格

```bash
cp persona/TEMPLATE.md persona/persona.txt
nano persona/persona.txt
```

可选：`persona/owner.txt`（只对主人）、`persona/other.txt`（只对其他人）。写法见 [persona.md](persona.md)。

## 5. 生成配置

```bash
bash phone/start.sh config
```

交互式询问名字、怎么称呼主人、接口地址、模型、API Key、历史/回复长度、新好友开场白。所有能力默认开启，不再询问开关。写到容器内 `/root/wx/config.json`（权限 600）。

重复运行会保留旧值：直接回车即沿用，只改人格时也走这个命令。API Key 输入 `-` 清空。

接口要求 OpenAI 兼容的 `POST {base_url}/chat/completions`，`Authorization: Bearer <key>`。要读图片，模型得支持 `image_url`。

## 6. 加联系人

备注名必须和微信会话列表里显示的一致（一般是备注，没有备注就是昵称）。

```bash
bash phone/proot.sh -c "python3 /root/wxcontacts.py add 备注名 owner"
bash phone/proot.sh -c "python3 /root/wxcontacts.py add 另一个人 other"
bash phone/proot.sh -c "python3 /root/wxcontacts.py list"
```

或者手动编辑 `/root/wx/contacts.json`。

## 7. 启动并登录

```bash
bash phone/start.sh start
```

容器内会起 Xvfb `:99`、x11vnc（`127.0.0.1:5900`）、微信和 `wxbot3.py`。首次登录用 VNC 客户端连 `127.0.0.1:5900`，扫码或手机确认。

VNC 无密码且只监听本机；手机和 Termux 在同一台设备上，可以用支持 VNC 的 App 连 `127.0.0.1:5900`，或用 `ssh -L 5900:127.0.0.1:5900` 转发到电脑。

登录后自检：

```bash
bash phone/start.sh wx-check
bash phone/start.sh status
```

## 8. 常用命令

```bash
bash phone/start.sh start
bash phone/start.sh stop
bash phone/start.sh status
bash phone/start.sh logs wx
bash phone/start.sh config
bash phone/start.sh selfcheck
```

日志在容器内 `/root/wx/logs/wx.log`，Termux 侧路径：

```bash
tail -f "$PREFIX/var/lib/proot-distro/installed-rootfs/debian/root/wx/logs/wx.log"
```

## 9. 开机自启

装 Termux:Boot，然后：

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/phone-ai.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sleep 20
bash ~/phone-ai-kit/phone/start.sh start
EOF
chmod +x ~/.termux/boot/phone-ai.sh
```

Android 会杀后台，需要在系统设置里关掉 Termux 的电池优化。

## 10. 升级

```bash
cd ~/phone-ai-kit
git pull
bash phone/start.sh stop
bash phone/start.sh install --force   # 已有部署时默认拒绝覆盖
bash phone/start.sh start
```

数据在 `/root/wx`，重装程序不会删除。人格与配置在仓库的 `persona/` 和 `/root/wx/config.json`。

---

# 二、电脑版（Linux 桌面）

## 0. 前置检查

- Debian 12 或 Ubuntu 24.04，`uname -m` 是 `x86_64`。
- 普通用户 + `sudo`。
- 安装目录默认 `$HOME/.local/share/phone-ai`（`PREFIX` 可改），不写 `/root`。
- 约 2 GB 空间；微信用 dpkg 装到 `/opt`。

## 1. 安装

```bash
cd ~/phone-ai-kit
bash pc/start.sh install
```

安装脚本做的事：

1. apt 安装 Xvfb、x11vnc、xdotool、xclip、ffmpeg、python3、pip、GTK/ASound/ATSPI、`python3-gi` 等；`libasound2` 先试 `libasound2t64`，GTK/atspi/cups 同理。
2. 下载并 `dpkg -i` 安装微信 Linux amd64：
   `https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb`
3. 把 `wxbot3.py`、`wxatspi.py`、`wxmem.py`、`wxtest.py`、`wxcontacts.py`、`wxstart.sh` 复制到 `$PREFIX`。
4. 建 `$WX_HOME`（默认 `$PREFIX/wx`）和空的 `contacts.json`。
5. `python3 -m pip install --user --break-system-packages rapidocr-onnxruntime opencv-python-headless`；字体先试 `fonts-wqy-zenhei`，装不上回退 `fonts-noto-cjk`。
6. 安装成功后写 `$WX_HOME/.kit` 标记。

只有 apt/dpkg 与 `/opt` 写入用 sudo；复制到 `$PREFIX` 的部分不用 sudo。

离线安装：把 `WeChatLinux_x86_64.deb` 放到工程根目录，脚本优先用本地文件。下载地址可用 `WECHAT_DEB_URL` 覆盖。

## 2. 写人格

```bash
cp persona/TEMPLATE.md persona/persona.txt
nano persona/persona.txt
```

可选 `persona/owner.txt`、`persona/other.txt`，写法见 [persona.md](persona.md)。

## 3. 生成配置

```bash
bash pc/start.sh config
```

写到 `$PREFIX/config.json`（权限 600）。交互与手机版相同。

## 4. 加联系人

```bash
PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
python3 "$PREFIX/wxcontacts.py" add 备注名 owner
python3 "$PREFIX/wxcontacts.py" add 另一个人 other
python3 "$PREFIX/wxcontacts.py" list
```

## 5. 启动并登录

```bash
bash pc/start.sh start
```

起 Xvfb `:99`、x11vnc `127.0.0.1:5900`、微信和 bot。VNC 连上去扫码/手机确认登录。

```bash
bash pc/start.sh wx-check
bash pc/start.sh status
```

## 6. 常用命令

```bash
bash pc/start.sh install
bash pc/start.sh config
bash pc/start.sh start
bash pc/start.sh stop
bash pc/start.sh status
bash pc/start.sh logs wx
bash pc/start.sh wx-check
bash pc/start.sh selfcheck
```

## 7. 开机自启（可选）

把下面一行加进桌面环境的 autostart：

```bash
bash ~/phone-ai-kit/pc/start.sh start
```

## 8. 升级

```bash
cd ~/phone-ai-kit
git pull
bash pc/start.sh stop
bash pc/start.sh install
bash pc/start.sh start
```

## 数据位置

| | 手机版（容器内） | 电脑版 |
|---|---|---|
| 配置 | `/root/wx/config.json` | `$PREFIX/config.json` |
| 联系人 / 历史 / 记忆 | `/root/wx/` | `$PREFIX/wx/` |
| 日志 | `/root/wx/logs/` | `$PREFIX/wx/logs/` |
| 程序 | `/root/wxbot3.py` 等 | `$PREFIX/wxbot3.py` 等 |
