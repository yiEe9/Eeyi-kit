# 微信通道

微信 Linux 客户端没有可用接口，所以这套东西是「看屏幕 + 点鼠标」：Xvfb 里跑真实客户端，截图 + AT-SPI 读消息，`xdotool` 点击、`xclip` 粘贴。它驱动的是你自己的账号，有风控风险，别用主号做实验。

## 启动与停止

```bash
bash phone/start.sh start      # 手机版
bash phone/start.sh stop
bash phone/start.sh status
bash phone/start.sh logs wx
bash phone/start.sh wx-check   # 自检，不跑循环、不发消息

bash pc/start.sh start         # 电脑版
bash pc/start.sh stop
bash pc/start.sh status
bash pc/start.sh logs wx
bash pc/start.sh wx-check
```

`start` 会起：

1. Xvfb `:99`（1280×960）；
2. x11vnc，只监听 `127.0.0.1:5900`，无密码；
3. 微信 Linux 客户端 `/opt/wechat/wechat`（或 PATH 里的 `wechat`）；
4. `wxbot3.py --loop --send`。

只有 `$WX_HOME/.kit` 存在时才复用已在运行的 Xvfb/微信；否则如果检测到已有微信/虚拟屏，会拒绝启动，避免驱动另一套部署。

首次登录用 VNC 看屏幕，扫码或手机确认。VNC 只在本机，远程用 SSH 隧道：

```bash
ssh -L 5900:127.0.0.1:5900 用户@机器
```

## 读消息：AT-SPI 优先，OCR 兜底

- **AT-SPI**：`wechat/wxatspi.py` 遍历微信 Qt 暴露的无障碍树，读会话名、消息文本、输入框和状态（锁屏/断网）。文本精确，不受 OCR 错字影响；左右归属仍用截图几何校验。
- **OCR**：`RapidOCR` 对截图逐字识别，按 x 坐标分左右。AT-SPI 不可用、节点解析不确定或遇到贴纸/图片时回退 OCR。
- **视觉兜底**：OCR 也读不到（纯表情、图片、复杂布局）时，把聊天区裁图交给支持 `image_url` 的模型。
- **融合**：文字用 OCR/AT-SPI，顺序和表情/图片描述用视觉模型补；两边对不上时信 OCR 的逐字文本。

AT-SPI 依赖 `python3-gi` 和 `gir1.2-atspi-2.0`，安装脚本已装。初始化失败会打印 `[atspi] 初始化失败` 并自动走 OCR，不影响启动。

## 联系人白名单

只有 `contacts.json` 里的人才会被回复。备注名必须和微信会话列表显示一致（一般是备注，没有备注就是昵称）。

```bash
# 手机版（WX_HOME 显式指定，避免落到默认 /root/wx）
bash phone/proot.sh -c "WX_HOME=/root/wx python3 /root/wxcontacts.py add 备注名 owner"

# 电脑版（PREFIX 默认 $HOME/.local/share/phone-ai，WX_HOME=$PREFIX/wx）
PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
WX_HOME="$PREFIX/wx" python3 "$PREFIX/wxcontacts.py" add 备注名 owner
WX_HOME="$PREFIX/wx" python3 "$PREFIX/wxcontacts.py" add 另一个人 other
WX_HOME="$PREFIX/wx" python3 "$PREFIX/wxcontacts.py" list
```

`add` 的第三个参数是 `owner` 或 `other`，可选第四个参数是 1–10 的在意程度。脚本默认值也会按安装位置推到 `$PREFIX/wx`；显式写 `WX_HOME` 最稳。

也可以直接编辑 `$WX_HOME/contacts.json`：

```json
{
  "某个备注": {"name": "某个备注", "role": "owner", "weight": 10},
  "另一个人": {"name": "另一个人", "role": "other", "weight": 3}
}
```

## 群聊点名

群聊点名（常开）：消息里出现 `config.json` 的 `name` 或 `@名字最后一个字` 才回；被点名时会向上翻一屏补上下文。`name` 为空时该功能自动失效。

群里每个人的发言会按发言人归到各自记忆（`remember_group` / `group_remember`），不污染一对一历史。

## 好友申请

好友申请（常开）：

1. 侧栏通讯录图标红点亮 → 打开「新的朋友」；
2. 找「等待验证」→「前往验证」→ 确定；
3. 填备注（默认用对方名字）；
4. 加进 `contacts.json`，按 `wechat_opener` / `wechat_opener_late` 决定要不要先开口。

开场白在 `config` 里填，最多 3 条，用 `|` 分隔；留空就只加名单不主动说话。

## 口吻库

口吻库（常开）会从可见聊天记录里挑出「主人手动用这个号打出、不是 bot 发的」句子（长度 ≥3、不在 `sent.json` 里、不是占位符），存到 `$WX_HOME/style/<名字>.txt`。生成回复时只取最近 12 行作参考，不会整段照抄。

「主人手动回复」的识别同时用于阻止主动追问。

## 表情库

表情库（常开）：

- 对方发来贴纸：先识别角色/情绪/图上的字，再让模型决定收不收；收就加到微信原生表情（右键「添加到表情」）并保存到 `$WX_HOME/stickers/`。
- 回复之后：模型看情绪决定要不要补一个表情包；优先发微信收藏里的原图（动态贴纸会动），没有再发自有库的静态图。
- 启动时如果 `$WX_HOME/stickers.json` 为空，会打开一次表情面板建目录。

可选本地语义模型 `WX_EMB_DIR`（默认程序目录下 `models/bge-small-zh`），没有就退回全清单，不影响使用。

## 话题循环锁与危险弹窗守卫

- **循环锁**：自己最近 6 条里 ≥4 条出现同一个词，或对方明确说「别再说了」，锁 3 轮，提示模型换话题。
- **弹窗守卫**：屏幕出现「退出登录」「解锁以继续」时停止操作；退出登录确认框点「取消」，其它按 Esc 跳过本轮。截图保存到 `$WX_HOME/danger.png`。

这两项常开，没有开关。朋友圈操作里也有独立的 `moment_guard`，避免在朋友圈窗口误点退出登录。

## 发送回读校验

每条消息发出后重新截图，确认聊天区最后几条里真的有这句话；没有就打印 `verify: not found in chat`。这不能保证对方收到，只能保证客户端里看起来发出去了。

## 手动维护命令

```bash
# 手机版：进入容器执行
bash phone/proot.sh -c "python3 /root/wxbot3.py --selfcheck"
bash phone/proot.sh -c "python3 /root/wxbot3.py --usage"
bash phone/proot.sh -c "python3 /root/wxbot3.py --mem 备注名"
bash phone/proot.sh -c "python3 /root/wxbot3.py --mem-del 备注名 2"
bash phone/proot.sh -c "python3 /root/wxbot3.py --ctx 备注名"
bash phone/proot.sh -c "python3 /root/wxbot3.py --mem-graph 备注名"
bash phone/proot.sh -c "python3 /root/wxbot3.py --moments"

# 电脑版：带 WX_HOME / WX_CONFIG 执行
PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --selfcheck
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --usage
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --mem 备注名
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --mem-del 备注名 2
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --ctx 备注名
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --mem-graph 备注名
WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --moments
```

所有维护命令都可用，不再需要开关。

## 数据文件

| 文件 | 内容 |
|---|---|
| `$WX_HOME/config.json` | 人格、模型与行为参数（600） |
| `$WX_HOME/contacts.json` | 白名单与关系分 |
| `$WX_HOME/history/<名字>.json` | 每个会话最近 `history_limit` 条 |
| `$WX_HOME/memory/<名字>/MEMORY.md` | 长期记忆 |
| `$WX_HOME/memory/<名字>/graph.json` | 记忆链 |
| `$WX_HOME/state.json` | 未读处理、冷却、循环锁 |
| `$WX_HOME/sent.json` | bot 发过的话，用来区分人打的 |
| `$WX_HOME/style/<名字>.txt` | 口吻库 |
| `$WX_HOME/stickers/` `stickers.json` | 自有表情库 |
| `$WX_HOME/inner.log` | 每轮「心想」 |
| `$WX_HOME/bot_log.md` | 每轮回话归档 |
| `$WX_HOME/logs/wx.log` | 进程输出 |

## 限制

- 这是界面自动化，不是协议接入；微信改版可能让坐标、无障碍树或 OCR 规则失效，需要重新标定。
- VNC 无密码，只监听 `127.0.0.1`；不要把 5900 暴露到公网。
- 同一时间只能跑一个 bot 实例；`wechat/wxstart.sh` 会先按 `$WX_HOME/wxbot.pid` 停掉本套件的旧实例，pid 文件不存在时按 `$PREFIX/wxbot3.py` 绝对路径精确匹配，不会动别的部署。
- 账号被踢、掉登录、弹验证时，代码只会保守地停下或跳过，不会自动绕过验证。
