# 架构与数据流

## 两个版本

```
手机版                                      电脑版
Android（未 root）                          Debian 12 / Ubuntu 24.04 x86_64
└── Termux                                  └── 桌面会话 / Xvfb
    ├── phone/start.sh                          ├── pc/start.sh
    └── proot-distro login debian               ├── pc/install.sh
        └── Debian 容器                          └── wechat/start-wx.sh
            ├── Xvfb :99                             ├── Xvfb :99
            ├── x11vnc 127.0.0.1:5900                ├── x11vnc 127.0.0.1:5900
            ├── 微信 Linux 客户端                     ├── 微信 Linux 客户端
            └── wxbot3.py                            └── wxbot3.py
```

两版共用 `persona/`、`wechat/`、`shared/`；只有入口、部署位置和进程托管方式不同。

- 手机版：`phone/start.sh` 在 Termux 里起一个 `proot-distro login debian` 进程，容器内由 `wechat/start-wx.sh` 起 Xvfb、x11vnc、微信和 bot。`phone/proot.sh` 只负责传环境变量（`PREFIX=/root`、`WX_HOME=/root/wx`、`WX_CONFIG`、`WX_DISPLAY`、`KIT_DIR`）并执行容器内命令。
- 电脑版：`pc/start.sh` 用 `nohup` 直接起 `wechat/start-wx.sh`，pid 记在 `$WX_HOME/logs/wx.pid`，`stop` 按 pid 先 `kill` 再 `kill -9`。

## 目录

```
phone-ai-kit/
├── persona/                 TEMPLATE.md（复制成 persona.txt 等）
├── wechat/                  wxbot3.py、wxatspi.py、wxmem.py、wxtest.py、contacts.py
│                            wxstart.sh、start-wx.sh、install.sh
├── shared/                  setup_config.py
├── phone/                   start.sh、proot.sh、kit.env.example
├── pc/                      start.sh、install.sh、kit.env.example
└── docs/
```

## 进程与显示

| 用途 | 地址 |
|---|---|
| 微信虚拟屏 | `:99`，1280×960（`WX_DISPLAY` 可改） |
| 微信 VNC | `127.0.0.1:5900`，无密码，只监听本机 |
| bot 主循环 | 一个 `wxbot3.py --loop --send` 进程 |
| 模型接口 | 由 `config.json` 的 `base_url` 决定 |

`wechat/wxstart.sh` 强制单实例：启动前先按 `$WX_HOME/wxbot.pid` 停掉本套件的旧 bot；pid 文件不存在时按 `$PREFIX/wxbot3.py` 绝对路径精确匹配，确认没有残留才启动，避免多开抢 OCR 和鼠标。

各进程 pid 写在 `$WX_HOME/`：`wxbot.pid`、`xvfb.pid`、`vnc.pid`、`wechat.pid`；停止只按这些 pid 文件停本套件启动的进程。

## 微信通道

```
每秒截屏（Xvfb :99）
   │
   ├─ 帧哈希没变 → 跳过
   ├─ AT-SPI 无障碍树读消息文本 / 会话名 / 输入框
   ├─ OCR（RapidOCR）逐字识别截图，按 x 坐标分左右
   ├─ OCR 读不到（表情/图片/复杂布局）→ 视觉模型兜底
   ├─ 融合：文字用 OCR/AT-SPI，顺序与表情/图片用视觉模型补
   └─ 有未读红点 → 切会话 → 有新消息 → 生成 → 剪贴板粘贴 → 回车 → 回读校验
```

生成分两步：先单独「心想」（写进 `$WX_HOME/inner.log`，不发出去），再把想法作为隐藏上下文生成正文。这样心里想的不会漏进消息。

坐标全部按窗口比例换算，每轮重新取窗口矩形（`window_rect()` 扫标题栏和左边缘；不能取非黑像素外接框，右键菜单会把框撑到屏幕外）。

更多细节与限制见 [wechat.md](wechat.md)。

## 数据落盘

所有运行时数据都在 `WX_HOME`：

| 数据 | 手机版（容器内） | 电脑版 |
|---|---|---|
| 配置 `config.json` | `/root/wx/config.json` | `$PREFIX/config.json` |
| `contacts.json` | `/root/wx/contacts.json` | `$PREFIX/wx/contacts.json` |
| `history/` | `/root/wx/history/` | `$PREFIX/wx/history/` |
| `memory/` | `/root/wx/memory/` | `$PREFIX/wx/memory/` |
| `state.json` `sent.json` `inner.log` | `/root/wx/` | `$PREFIX/wx/` |
| `style/` `stickers/` `graphs/` | `/root/wx/` | `$PREFIX/wx/` |
| 日志 `logs/` | `/root/wx/logs/` | `$PREFIX/wx/logs/` |

手机版容器内 `/root/wx` 对应手机上的 `$PREFIX/var/lib/proot-distro/installed-rootfs/debian/root/wx`，Termux 可以直接读写。电脑版 `PREFIX` 默认 `$HOME/.local/share/phone-ai`。

`memory/` 由 `wxmem.py` 维护：`<名字>/MEMORY.md` 是条目记忆，`<名字>/graph.json` 是记忆链，`MEMORY.md` 是每人一行的索引；整个目录会做成 git 仓库，写入后自动提交。自动提交需要系统已安装 `git`，否则跳过提交（记忆本身照常写入）。

## 为什么这么设计

- **人格不进代码**：正文、主人设定、其他人设定都是文本，换人格不用改一行代码；代码只认 `name`、`owner_call` 和三个标记（`<记住>`、`<好感>`、`<减分>`）。
- **每人一份记忆**：跨会话不会串；每次生成都会把其他人的档案摘要注入上下文，提到谁时再展开细节。
- **标记驱动**：`<记住>` 写长期记忆，`<好感>`/`<减分>` 调关系分，模型自己决定记什么，代码只负责落地和删除。
- **OCR / AT-SPI 双读**：AT-SPI 文本精确，OCR 几何可靠；两边互相校验，任一方不可用都能跑。
- **单实例**：微信 bot 多开会互抢 OCR 资源直接卡死，启动脚本强制先杀干净再起。
- **路径全走环境变量**：Python 侧只认 `WX_HOME` / `WX_CONFIG` / `PREFIX`；配置默认在 `WX_HOME` 下，可用环境变量覆盖，路径缺失时会明确报错。
