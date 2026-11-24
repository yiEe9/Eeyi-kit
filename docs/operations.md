# 日常运维

电脑版命令里的 `$PREFIX` 默认是 `$HOME/.local/share/phone-ai`；如果当前 shell 没设置，先执行：

```bash
PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
```

## 命令

### 手机版（Termux）

| 命令 | 作用 |
|---|---|
| `bash phone/start.sh rootfs` | 装 proot-distro、建 Debian 容器（只做一次） |
| `bash phone/start.sh install` | 容器内装微信、X 环境、OCR 与程序 |
| `bash phone/start.sh config` | 改人格、模型与行为参数 |
| `bash phone/start.sh start` | 起 Xvfb、微信、VNC 与 bot |
| `bash phone/start.sh stop` | 按 pid 停 bot 与容器内本套件的微信/Xvfb/VNC |
| `bash phone/start.sh status` | 看 bot 是否在跑 |
| `bash phone/start.sh logs wx` | 看 `logs/wx.log` 尾部 |
| `bash phone/start.sh wx-check` | 微信通道自检（不跑循环、不发消息） |
| `bash phone/start.sh selfcheck` | 自检容器依赖、程序、配置 |

### 电脑版（Linux 桌面）

| 命令 | 作用 |
|---|---|
| `bash pc/start.sh install` | 装系统依赖、微信 amd64、OCR 与程序 |
| `bash pc/start.sh config` | 改人格、模型与行为参数 |
| `bash pc/start.sh start` | 起 Xvfb、微信、VNC 与 bot |
| `bash pc/start.sh stop` | 按 pid 停本套件的 bot、微信、Xvfb/VNC |
| `bash pc/start.sh status` | 看 bot 是否在跑 |
| `bash pc/start.sh logs wx` | 看 `logs/wx.log` 尾部 |
| `bash pc/start.sh wx-check` | 微信通道自检（不跑循环、不发消息） |
| `bash pc/start.sh selfcheck` | 自检系统依赖、程序、配置 |

手机版所有服务是「一个 `proot-distro login` 进程」，pid 记在 `$WX_HOME/logs/wx.pid`；`stop` 先 `kill` 再 `kill -9`，并在容器内按 `$WX_HOME` 下的 pid 文件停掉本套件的 bot、微信/Xvfb/VNC。电脑版同理，但进程直接在本机。

## 日志

| 路径 | 内容 |
|---|---|
| `$WX_HOME/logs/wx.log` | Xvfb/VNC/微信/bot 的进程输出 |
| `$WX_HOME/inner.log` | 每轮「心想」，不外发 |
| `$WX_HOME/bot_log.md` | 每轮回话的对方原话、心想、回复 |
| `$WX_HOME/usage.json` | 按天累计模型调用与 token |

手机版 `$WX_HOME` 是容器内 `/root/wx`，Termux 侧对应：

```bash
tail -f "$PREFIX/var/lib/proot-distro/installed-rootfs/debian/root/wx/logs/wx.log"
```

电脑版 `$WX_HOME` 默认 `$HOME/.local/share/phone-ai/wx`：

```bash
tail -f "$HOME/.local/share/phone-ai/wx/logs/wx.log"
```

## 备份

停止服务后复制 `$WX_HOME` 即可；配置、联系人、历史、记忆、表情、口吻库都在里面。

手机版：

```bash
bash phone/start.sh stop
cp -r "$PREFIX/var/lib/proot-distro/installed-rootfs/debian/root/wx" ~/backup-wx-$(date +%m%d)
bash phone/start.sh start
```

电脑版：

```bash
bash pc/start.sh stop
cp -r "$HOME/.local/share/phone-ai/wx" ~/backup-wx-$(date +%m%d)
cp "$HOME/.local/share/phone-ai/config.json" ~/backup-config-$(date +%m%d).json
bash pc/start.sh start
```

- `config.json` 含 API Key，权限 600；备份文件也要收紧权限。
- 只备份人格：`persona/` 三个文件 + `config.json` 里的 `name` / `system_prompt` / `owner_prompt` / `other_prompt` / `owner_call`。
- 恢复：停服务，把目录拷回 `$WX_HOME`，`chmod 600 config.json`，再启动。

**不要把 `$WX_HOME` 打进分享包**：里面有 Key、聊天记录、别人的隐私。

## 换人格 / 改设定

```bash
nano persona/persona.txt
bash phone/start.sh config     # 回车保留旧值
bash phone/start.sh stop && bash phone/start.sh start
```

电脑版把入口换成 `bash pc/start.sh config` / `start`。只改 API Key、模型或行为参数也一样走 `config`，不需要重装微信。

## 让某人失忆

```bash
# 手机版：容器内
bash phone/proot.sh -c "python3 /root/wxbot3.py --mem 备注名"
bash phone/proot.sh -c "python3 /root/wxbot3.py --mem-del 备注名 3"

# 电脑版
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --mem 备注名
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --mem-del 备注名 3
```

彻底清空某人：停服务，删 `$WX_HOME/history/<名字>.json`、`$WX_HOME/memory/<名字>/`、`$WX_HOME/style/<名字>.txt`，再启动。`state.json` 里的会话状态可以保留，也可以一起清。

## 用量

```bash
# 手机版
bash phone/proot.sh -c "python3 /root/wxbot3.py --usage"

# 电脑版
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --usage
```

按天列出调用次数、输入/输出 token、缓存命中。

## 改显示与日志位置

- `WX_DISPLAY`：虚拟屏编号，默认 `:99`；改完 `stop`/`start`。
- `WX_HOME`：数据目录；改了要同时改启动脚本和 `phone/proot.sh` 的传值，普通用户不建议改。
- 日志：手机版在容器内 `$WX_HOME/logs`（Termux 侧 `$PREFIX/var/lib/proot-distro/installed-rootfs/debian/root/wx/logs`），电脑版在 `$WX_HOME/logs`；手机版 `phone/start.sh logs wx` 和电脑版 `pc/start.sh logs wx` 都读这个位置。

## 账号被踢 / 需要重新登录

```bash
bash phone/start.sh stop
bash phone/start.sh start
# 用 VNC 连 127.0.0.1:5900，重新扫码/确认
```

电脑版把 `phone/start.sh` 换成 `pc/start.sh`。连续被踢说明账号被风控，停一天再试，别反复登录。

## 微信通道重启

```bash
bash phone/start.sh stop
bash phone/start.sh start
```

`start-wx.sh` 会重新拉起 Xvfb、微信、VNC 和 bot。登录页需要人工处理（见 [wechat.md](wechat.md)）。

## 分享给别人

带上：整个 `phone-ai-kit/`（不含 `logs/`、`*.deb`、`*.zip`、`persona/*.txt`、`kit.env`、`config.json`）。
不要带：

- `phone/kit.env`、`pc/kit.env`
- `$WX_HOME/`（含 Key、记忆、聊天记录）
- `logs/`
- `persona/persona.txt`（如果你不想把自己的角色给别人）

```bash
cd ~
zip -r phone-ai-kit.zip phone-ai-kit \
  -x 'phone-ai-kit/logs/*' 'phone-ai-kit/*.deb' 'phone-ai-kit/*.zip' \
     'phone-ai-kit/phone/kit.env' 'phone-ai-kit/pc/kit.env' \
     'phone-ai-kit/persona/*.txt'
```
