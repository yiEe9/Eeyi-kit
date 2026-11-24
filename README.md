# Eeyi kit

一个住在微信里的 AI 人格，跑在你自己的手机或电脑上。

这套是几个月前弄的，有漏洞、有 bug 都是正常的；本人还在学校学习，没有那么多时间。相比市面上其他方法，我这个几乎不会被封号。

它不是那种一问一答的机器人。它会看聊天、记住每个人说过的事，按关系的远近决定说话的分寸；会自己找人搭话、在朋友圈点个赞、发张表情包；你让它替你说句话，它也能切到那个人的会话去说。人格是一份文本，你自己写，代码里没有预设的人。

原理很土但有效：控制微信 Linux 版本身。用无障碍树读消息，读不准就截图做 OCR，再不行让模型看图；算好窗口比例去点击和粘贴。不接官方接口，也不碰协议。

如果喜欢的话，可以给我点个 Star 吗。

发现 bug 的话可以自己改一下，加油。

## 两个版本

| | 手机版 `phone/` | 电脑版 `pc/` |
|---|---|---|
| 跑在哪 | Android 手机，Termux + proot-distro 的 Debian 容器（arm64） | Debian 12 / Ubuntu 24.04 x86_64 桌面 |
| 需要什么 | 未 root 的 arm64 手机、Termux、约 4 GB 空间 | 普通用户 + sudo、约 2 GB 空间 |
| 怎么装 | `bash phone/start.sh rootfs` → `bash phone/start.sh install` | `bash pc/start.sh install` |
| 数据放哪 | 容器内 `$WX_HOME`（默认 `/root/wx`） | `$WX_HOME`（默认 `$PREFIX/wx`） |
| 进程怎么管 | Termux 里一个 `proot-distro login` 进程托住容器内的 Xvfb + 微信 + bot | 本机 `nohup`，pid 在 `$WX_HOME/logs` |
| 限制 | 受 Android 后台限制，需要 Termux:Boot、关电池优化 | 需要保持桌面会话或 Xvfb，首次登录要 VNC 扫码 |

两版共用 `persona/`、`wechat/`、`shared/`；`phone/` 与 `pc/` 的入口互不引用。

## 快速开始：手机版（Termux）

```bash
# 1. 装 Termux 依赖（proot-distro 提供 Debian 容器）
pkg update
pkg install proot-distro nano

# 2. 把仓库放到 Termux 能读到的位置，例如家目录
cd ~/phone-ai-kit

# 3. 建 Debian 容器（一次性，下载 rootfs）
bash phone/start.sh rootfs

# 4. 容器内装微信、Xvfb/VNC、xdotool、OCR
bash phone/start.sh install

# 5. 写人格与配置
cp persona/TEMPLATE.md persona/persona.txt
nano persona/persona.txt
bash phone/start.sh config

# 6. 加入要聊的人（备注名要和微信会话列表一致）
bash phone/proot.sh -c "python3 /root/wxcontacts.py add 备注名 owner"

# 7. 启动（首次登录用 VNC 连 127.0.0.1:5900 扫码）
bash phone/start.sh start

# 8. 自检与状态
bash phone/start.sh wx-check
bash phone/start.sh status
```

说明：

- 仓库放在 Termux 家目录最稳；放 `/sdcard` 需要 proot-distro 能访问共享存储。
- 手机版日志在容器内 `$WX_HOME/logs`，Termux 侧对应 `$PREFIX/var/lib/proot-distro/installed-rootfs/debian/root/wx/logs`。
- 开机自启：装 Termux:Boot，把 `bash ~/phone-ai-kit/phone/start.sh start` 放进 `~/.termux/boot/`。

## 快速开始：电脑版（Linux 桌面）

```bash
cd ~/phone-ai-kit

# 1. 写人格
cp persona/TEMPLATE.md persona/persona.txt
nano persona/persona.txt

# 2. 装系统依赖、微信 amd64、OCR 与程序（需要 sudo）
bash pc/start.sh install

# 3. 写配置（模型、Key、称呼）
bash pc/start.sh config

# 4. 加入要聊的人（备注名要和微信会话列表一致）
PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
python3 "$PREFIX/wxcontacts.py" add 备注名 owner

# 5. 启动（首次登录用 VNC 连 127.0.0.1:5900 扫码）
bash pc/start.sh start

# 6. 自检与状态
bash pc/start.sh wx-check
bash pc/start.sh status
```

电脑版默认安装到 `$PREFIX`（`$HOME/.local/share/phone-ai`），只有 apt/dpkg 和 `/opt` 下的微信用 sudo；复制程序与数据不写 `/root`。

## 命令

| 命令 | 手机版 | 电脑版 | 作用 |
|---|---|---|---|
| `rootfs` | 有 | 无 | 装 proot-distro 并建 Debian 容器 |
| `install` | 有 | 有 | 装系统依赖、微信、OCR、程序 |
| `config` | 有 | 有 | 生成/修改人格、模型与行为参数 |
| `start` | 有 | 有 | 起虚拟屏、微信与 bot |
| `stop` | 有 | 有 | 按 pid 停本套件的 bot、微信、Xvfb/VNC |
| `status` | 有 | 有 | 看 bot 是否在跑 |
| `logs [wx]` | 有 | 有 | 看日志尾部 |
| `wx-check` | 有 | 有 | 自检，不跑循环、不发消息 |
| `selfcheck` | 有 | 有 | 自检依赖、配置与目录 |

```bash
bash phone/start.sh <命令>     # 手机版
bash pc/start.sh <命令>        # 电脑版
```

## 能力总览

所有能力默认开启，没有开关。详细说明、触发条件与代价见 [docs/features.md](docs/features.md)。

| 能力 | 一句话 |
|---|---|
| 跨会话人物档案与跨人联动 | 注入其他人的档案；提到谁时能接上话 |
| 长期记忆库 | 每人一份 markdown 记忆，按内容注入 |
| 记忆链 | 激活扩散 + 语义补边，让相关记忆一起被想起 |
| 口吻库 | 采样主人手动打出的话，回复时参考 |
| 主动聊天 | 按时间段主动找人说话 |
| 久未回追问 | 自己最后一句长时间没回音时轻轻问一句 |
| 朋友圈 | 读动态、点赞、评论、回复评论 |
| 好友申请 | 自动通过待验证申请，可选开场白 |
| 表情库 | 识别、收藏、按情绪发表情包 |
| 代发 | 主人会话里用 `[[发送:名字\|内容]]` 代发 |
| 群聊点名 | 群里只在被点名时回 |
| 记忆镜像 | 设置 `WX_MIRROR` 后把记忆目录复制过去 |
| 话题循环锁 | 同一话题反复念时锁几轮 |
| 危险弹窗守卫 | 看到退出登录/锁屏弹窗只取消，不乱点 |
| AT-SPI 读消息 | 优先用无障碍树读精确文本，失败回退 OCR |
| OCR 兜底 | 本地 RapidOCR 逐字识别截图 |
| 发送回读校验 | 发完回读聊天区，确认真的发出去了 |

## 目录

```
phone-ai-kit/
├── README.md
├── LICENSE
├── .gitignore
├── persona/TEMPLATE.md     人格模板（复制成 persona.txt 使用）
├── wechat/                 wxbot3.py wxatspi.py wxmem.py wxtest.py contacts.py
│                           wxstart.sh start-wx.sh install.sh
├── shared/setup_config.py  交互式生成配置
├── phone/                  start.sh proot.sh kit.env.example
├── pc/                     start.sh install.sh kit.env.example
└── docs/                   architecture install persona operations wechat
                            troubleshooting security features
```

## 工作原理

```
微信 Linux 客户端（Xvfb :99）
   │  AT-SPI 无障碍树 / 截图 + RapidOCR / 视觉模型兜底
   ▼
wxbot3.py ── 判断新消息、生成回复、控制点击与粘贴 ──▶ 模型 API
   │
   └── 数据：$WX_HOME/contacts.json history/ memory/ state.json sent.json
              style/ stickers/ inner.log logs/
```

- 手机版：`phone/start.sh start` 在 Termux 起一个 `proot-distro login` 进程，容器内 `wechat/start-wx.sh` 起 Xvfb、x11vnc、微信和 `wxbot3.py`。
- 电脑版：`pc/start.sh start` 直接在本机起同一个 `wechat/start-wx.sh`。
- 坐标按微信窗口比例换算，每轮重新取窗口矩形；聊天生成逻辑与点击坐标来自实机版本，改动前先读 `wechat/wxbot3.py` 的注释。
- 所有路径由环境变量定位：`PREFIX` 是程序安装目录，`WX_HOME` 是数据目录，`WX_CONFIG` 是配置文件；配置缺失会明确报错。

细节见 [docs/architecture.md](docs/architecture.md)。

## 换人格

人格是三个纯文本文件：

- `persona/persona.txt`：正文，对所有人生效（必须自己写，仓库只带模板）
- `persona/owner.txt`：只对主人追加，可选
- `persona/other.txt`：只对其他人追加，可选

改完运行 `bash phone/start.sh config`（电脑版 `bash pc/start.sh config`），回车保留原值。写法和检查清单见 [docs/persona.md](docs/persona.md)。

## 风险

- 封号风险比常见的第三方方案低得多：这套驱动的是真实的微信 Linux 客户端，不改协议、不注入、不伪造登录，跟 NapCat 和各种「协议端」不是一回事。我自己用了几个月没出过事。但**这不等于零风险，也不是官方保证**，别拿主号赌。
- 微信通道是驱动真实客户端，不是官方接口；账号仍可能被风控、踢下线或限制，**不要用主号做实验**。
- 聊天记录、记忆、API Key 都以明文存在本机（`config.json` 权限 600），备份和分享时别把配置一起发出去。
- 所有能力默认开启：朋友圈、好友申请、跨会话档案、记忆镜像（设置 `WX_MIRROR` 时）、代发都会实际动作；部署前先想清楚谁能看到、谁会收到消息。
- 别用它冒充真人骗人、批量骚扰或做违法的事。人格设定里的「不是 AI」是角色扮演，不是诈骗许可。

完整说明见 [docs/security.md](docs/security.md)。

## 文档

- [架构与数据流](docs/architecture.md)
- [安装（手机版 Termux + proot-distro / 电脑版 Linux 桌面）](docs/install.md)
- [写人格](docs/persona.md)
- [日常运维、备份、升级](docs/operations.md)
- [微信通道细节](docs/wechat.md)
- [能力清单与代价](docs/features.md)
- [排错](docs/troubleshooting.md)
- [安全与合规](docs/security.md)

## 许可

MIT，见 [LICENSE](LICENSE)。第三方来源与许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

> 为什么不含 QQ：上游 NapCat 已停服（releases/tags 清空、下载地址 404），QQ 链路无法让新用户装起来，所以整条链路已移除。
