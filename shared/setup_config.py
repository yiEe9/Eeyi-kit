#!/usr/bin/env python3
"""交互式生成微信通道配置。人格正文从文件读入，不写死在代码里。

配置位置由 WX_CONFIG 决定，默认 $WX_HOME/config.json。
"""
import json
import os
import sys

KIT = os.environ.get("KIT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WX_HOME = os.environ.get("WX_HOME") or "/root/wx"
CFG_PATH = os.environ.get("WX_CONFIG") or os.path.join(WX_HOME, "config.json")
ENTRY_HINT = os.environ.get("ENTRY_HINT") or "bash phone/start.sh"
PERSONA = os.path.join(KIT, "persona", "persona.txt")
OWNER_FILE = os.path.join(KIT, "persona", "owner.txt")
OTHER_FILE = os.path.join(KIT, "persona", "other.txt")

DEFAULTS = {
    "utc_offset": 8,
    "history_limit": 30,
    "reply_limit": 400,
    "min_interval": 5,
    "humanize": True,
    "wechat_opener": [],
    "wechat_opener_late": [],
}


def ask(label, default=""):
    hint = " [%s]" % default if default not in ("", None) else ""
    try:
        s = input(label + hint + "：").strip()
    except EOFError:
        print()
        s = ""
    return s or default


def ask_yes(label, default):
    d = "Y/n" if default else "y/N"
    s = ask(label + "（%s）" % d, "").lower()
    if not s:
        return default
    return s in ("y", "yes", "是")


def read_text(path):
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8").read().strip()


def ask_num(label, default, cast=int):
    s = ask(label, str(default))
    try:
        return cast(s)
    except (TypeError, ValueError):
        print("要填数字，按 %s 处理" % default)
        return default


def ask_list(label, default):
    cur = " | ".join(str(x) for x in (default or []))
    s = ask(label + "（用 | 分隔，可留空）", cur)
    return [x.strip() for x in s.split("|") if x.strip()][:3]


def main():
    old = {}
    if os.path.exists(CFG_PATH):
        try:
            old = json.load(open(CFG_PATH, encoding="utf-8"))
        except Exception:
            print("现有配置读不了，按新配置处理")
    os.makedirs(WX_HOME, exist_ok=True)

    if not os.path.exists(PERSONA):
        print("找不到人格正文：" + PERSONA)
        print("把 persona/TEMPLATE.md 复制成 persona/persona.txt，填好后再运行。")
        return 1
    body = read_text(PERSONA)
    if len(body) < 100:
        print("人格正文太短（%d 字），先在 %s 里写完整" % (len(body), PERSONA))
        return 1

    print("=== 人格 ===")
    name = ask("名字（对外自称）", old.get("name") or "")
    if not name:
        print("名字不能为空")
        return 1
    print("已读取人格正文 %d 字" % len(body))

    print("\n=== 主人 ===")
    print("主人的消息会额外注入 owner.txt，其他人注入 other.txt；文件为空则该栏不生效。")
    owner_call = ask("怎么称呼主人", old.get("owner_call") or "你")
    owner_prompt = read_text(OWNER_FILE) or (old.get("owner_prompt") or "")
    other_prompt = read_text(OTHER_FILE) or (old.get("other_prompt") or "")

    print("\n=== 模型 ===")
    base_url = ask("接口地址 base_url", old.get("base_url") or "https://api.deepseek.com")
    model = ask("模型名", old.get("model") or "deepseek-chat")
    old_key = old.get("api_key") or ""
    shown = "已保存 " + old_key[:4] + "…" if old_key else "未设置"
    key = ask("API Key（回车保留 %s，输入 - 清空）" % shown, "")
    if key == "-":
        key = ""
    elif not key:
        key = old_key
    utc = ask_num("时区偏移（小时）", old.get("utc_offset", 8), float)

    print("\n=== 行为 ===")
    history_limit = ask_num("每个会话保留多少条历史", old.get("history_limit", 30))
    reply_limit = ask_num("单条回复最多多少字", old.get("reply_limit", 400))
    min_interval = ask_num("同一会话最小回复间隔（秒，兼容旧配置）", old.get("min_interval", 5))
    humanize = ask_yes("像真人一样打字（延迟、偶尔打错、偶尔不回）", old.get("humanize", True))
    opener = ask_list("新好友开场白", old.get("wechat_opener") or DEFAULTS["wechat_opener"])
    opener_late = ask_list("加了很久没说话时的开场白（不填就用上面的）",
                           old.get("wechat_opener_late") or DEFAULTS["wechat_opener_late"])

    keep = ("name", "system_prompt", "owner_prompt", "other_prompt", "owner_call",
            "base_url", "model", "api_key", "utc_offset", "history_limit", "reply_limit",
            "min_interval", "humanize", "wechat_opener", "wechat_opener_late")
    cfg = dict(DEFAULTS)
    cfg.update({k: old[k] for k in keep if k in old})
    cfg.update({
        "name": name,
        "system_prompt": body,
        "owner_prompt": owner_prompt,
        "other_prompt": other_prompt,
        "owner_call": owner_call or "你",
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": key,
        "utc_offset": utc,
        "history_limit": history_limit,
        "reply_limit": reply_limit,
        "min_interval": min_interval,
        "humanize": humanize,
        "wechat_opener": opener,
        "wechat_opener_late": opener_late,
    })
    for d in ("memory", "history", "style", "stickers", "graphs"):
        os.makedirs(os.path.join(WX_HOME, d), exist_ok=True)
    os.makedirs(os.path.dirname(CFG_PATH) or ".", exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(CFG_PATH, 0o600)

    print("\n已写入 " + CFG_PATH)
    print("  名字：%s" % name)
    print("  人格：%d 字" % len(body))
    print("  称呼主人：%s" % cfg["owner_call"])
    print("  模型：%s @ %s" % (model, base_url))
    print("  API Key：%s" % ("已配置" if key else "未配置"))
    print("  能力：全部开启（没有开关）")
    print("\n下一步：%s start" % ENTRY_HINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
