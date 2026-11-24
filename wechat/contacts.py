#!/usr/bin/env python3
"""微信联系人白名单维护。

  python3 contacts.py list
  python3 contacts.py add 备注名 owner|other [weight]
  python3 contacts.py rm 备注名
  python3 contacts.py note 备注名 昵称

备注名必须和微信会话列表里显示的一致（一般是备注，没有备注就是昵称）。
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_HERE) == "wechat":
    _BASE = os.path.dirname(_HERE)
else:
    _BASE = _HERE
ROOT = os.environ.get("WX_HOME") or os.path.join(os.environ.get("PREFIX") or _BASE, "wx")
FILE = os.path.join(ROOT, "contacts.json")


def load():
    try:
        return json.load(open(FILE, encoding="utf-8"))
    except Exception:
        return {}


def save(data):
    os.makedirs(ROOT, exist_ok=True)
    json.dump(data, open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    data = load()
    cmd = args[0]

    if cmd == "list":
        if not data:
            print("（空）")
        for name, v in data.items():
            print("%-16s %-6s weight=%-2s %s" % (
                name, v.get("role", "other"), v.get("weight", 5),
                v.get("note") or v.get("nick") or ""))
        return 0

    if cmd == "add":
        if len(args) < 3:
            print("用法：contacts.py add 备注名 owner|other [weight]")
            return 1
        name, role = args[1], args[2]
        if role not in ("owner", "other"):
            print("role 只能是 owner 或 other")
            return 1
        ent = data.setdefault(name, {"name": name})
        ent["role"] = role
        if len(args) > 3:
            ent["weight"] = max(1, min(10, int(args[3])))
        else:
            ent.setdefault("weight", 10 if role == "owner" else 3)
        save(data)
        print("已写入：%s（%s，weight=%s）" % (name, role, ent.get("weight")))
        return 0

    if cmd == "rm":
        if len(args) < 2:
            return 1
        data.pop(args[1], None)
        save(data)
        print("已删除：" + args[1])
        return 0

    if cmd == "note":
        if len(args) < 3:
            print("用法：contacts.py note 备注名 昵称")
            return 1
        data.setdefault(args[1], {"name": args[1]})["note"] = args[2]
        save(data)
        print("已记录：" + args[1] + " → " + args[2])
        return 0

    print("未知命令：" + cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
