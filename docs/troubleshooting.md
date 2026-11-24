# 排错

电脑版命令里的 `$PREFIX` 默认是 `$HOME/.local/share/phone-ai`；没设置时先 `PREFIX=${PREFIX:-$HOME/.local/share/phone-ai}`。

先跑自检，按失败项修：

```bash
bash phone/start.sh selfcheck     # 手机版
bash pc/start.sh selfcheck        # 电脑版
bash phone/start.sh wx-check      # 只查微信通道（不跑循环）
bash pc/start.sh wx-check
```

## 找不到配置文件

```
找不到配置文件：/root/wx/config.json
先运行：bash phone/start.sh config 或 bash pc/start.sh config 生成配置
```

按提示运行 `config`。`wxbot3.py` 默认读取 `$WX_HOME/config.json`，可用 `WX_CONFIG` 环境变量覆盖；找不到就直接报错退出。

## AT-SPI 不可用

日志出现：

```
[atspi] 没找到微信无障碍树
[atspi] 初始化失败 ...
```

1. 确认装了 `python3-gi` 和 `gir1.2-atspi-2.0`（安装脚本已带）。
2. 确认 `DISPLAY` 指向微信所在的屏（默认 `:99`）。
3. 确认微信已经启动，不是只起了 Xvfb。
4. 仍然失败会**自动回退 OCR**，不影响收发，只是文本精度下降。

如果 AT-SPI 把消息顺序读错，日志会有 `[atspi] 方位不确定，回退 OCR`；这属于预期降级。

## Xvfb / 微信没起来

```bash
bash phone/start.sh status
bash phone/start.sh logs wx
```

- `Xvfb :99` 起不来：多半是 `:99` 被占用。`WX_DISPLAY=:100` 后 `stop`/`start`。
- x11vnc 起不来：看 5900 是否被占用；VNC 只监听 `127.0.0.1`。
- 微信没起来：确认 `/opt/wechat/wechat` 存在，或 `command -v wechat` 有输出；否则重跑 `install`。
- 微信窗口不出现：VNC 连上去看，可能是登录页、锁屏页或弹窗；危险弹窗守卫只会取消退出登录，不会自动登录。

## 扫码登录

首次启动后用 VNC 连 `127.0.0.1:5900`：

- 手机版：在同一台手机上用 VNC App 连 `127.0.0.1:5900`；
- 电脑版：本机 VNC 客户端连 `127.0.0.1:5900`；
- 远程：`ssh -L 5900:127.0.0.1:5900 用户@机器`。

登录页的二维码是微信自己画的，代码不读取、不复制二维码；只能人工扫。

## OCR 依赖导入失败

```
ModuleNotFoundError: No module named 'cv2'
ModuleNotFoundError: No module named 'rapidocr_onnxruntime'
```

重跑安装：

```bash
bash phone/start.sh install      # 手机版
bash pc/start.sh install         # 电脑版
```

电脑版如果 `pip --user` 装到了别的 Python，用 `python3 -c "import sys; print(sys.path)"` 确认 `~/.local/lib/python3.x/site-packages` 在路径里。

## 图片/表情识别不出来

- 视觉兜底需要模型支持 `image_url`；不支持就只发文字。
- 贴纸缓存 `$WX_HOME/sticker_cache.json` 可能过期，删掉后下一轮重建。
- 表情目录 `$WX_HOME/stickers.json` 数量对不上时，删掉让它重建。

## 群里不回

- 群聊点名常开：只有消息包含 `config.json` 的 `name` 或 `@名字最后一个字` 才回。检查 `name` 是否和群里叫法一致。
- `name` 为空时点名功能自动关闭，群里永远不回。
- 没在 `contacts.json` 里的群不会被处理。

## 朋友圈不动作

- 朋友圈功能常开；如果没有动作，先确认启动参数带 `--send`，再手动跑一次下面的命令看日志。
- 手动验证：`WX_HOME="$PREFIX/wx" WX_CONFIG="$PREFIX/config.json" python3 "$PREFIX/wxbot3.py" --moments`（电脑版）或 `bash phone/proot.sh -c "python3 /root/wxbot3.py --moments"`。
- 朋友圈窗口是独立窗口，找不到时日志会打印 `[moment] 打不开朋友圈`；先人工打开一次确认入口位置没变。

## 主动聊天不发

- 主动聊天常开；确认启动参数带 `--loop --send`。
- 需要聊天安静超过 8 分钟，且当前时段没用过；每日总量和同一人次数有限制。
- `--loop` 不带 `--send` 是 dry-run，只打印不发送。

## 发送了但聊天里没有

日志出现 `verify: not found in chat`：

- 输入框可能没聚焦，或粘贴失败；`xclip` 必须在运行。
- 微信窗口被弹窗遮挡；危险弹窗守卫会跳过，不会硬点。
- 网络断开会显示「当前网络不可用」，AT-SPI 会读到，等网络恢复。

## 安装被拒绝：检测到已有部署

`wechat/install.sh` 发现 `$WX_HOME/contacts.json` 或 `state.json` 非空时会拒绝覆盖，并提示「检测到已有部署，确认要覆盖请加 --force」。确认要覆盖（程序会先备份成 `<文件>.bak-时间`）时：

```bash
bash phone/start.sh install --force
```

## 启动被拒绝：检测到已在运行的微信/虚拟屏

如果 `$WX_HOME/.kit` 不存在，而系统里已经有 Xvfb、x11vnc 或微信，`start-wx.sh` 会拒绝启动，避免驱动另一套部署。确认是本套件的旧进程后先停：

```bash
bash phone/start.sh stop
```

如果确实属于另一套部署，换一个 `WX_HOME` / `PREFIX` 或 `WX_DISPLAY`。

## 多开 / 卡死

`wechat/wxstart.sh` 启动前会按 `$WX_HOME/wxbot.pid` 停掉本套件的旧 bot；pid 文件不存在时按 `$PREFIX/wxbot3.py` 绝对路径精确匹配，不会杀别的部署。如果仍然卡死：

```bash
bash phone/start.sh stop
bash phone/start.sh start
```

不要同时跑两个 `start-wx.sh`，OCR 和鼠标会互相抢。

## 日志与诊断

| 文件 | 看什么 |
|---|---|
| `$WX_HOME/logs/wx.log` | 进程启动、窗口、VNC、异常 |
| `$WX_HOME/inner.log` | 每轮心想 |
| `$WX_HOME/bot_log.md` | 每轮回话 |
| `$WX_HOME/atspi_shadow.jsonl` | AT-SPI 与 OCR 的对照记录（超过 2 MB 自动轮转） |
| `$WX_HOME/danger.png` | 最近一次危险弹窗截图 |
