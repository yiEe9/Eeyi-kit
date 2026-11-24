"""长期记忆：markdown 条目、按预算注入、git 自动提交。

移植自 dsh-plugin-memory（github.com/LittleBlackTong/dsh-plugin-memory，MIT）：
  - 存储约定 MEMORY.md / log.md 与「markdown + git」的落盘方式
  - lib/boot.js 的注入预算（不整篇塞，按上限截断并标注）
  - lib/autocommit.js 的自动提交（有仓库才提交、失败不致命、debounce 60s）
原实现是 JS/Cordis 插件，这里按 bot 的结构改成 Python，并按联系人分目录。

检索设计参考 dsh-memory-plugin（github.com/ttweip/dsh-memory-plugin）的 PROTOCOL：
按需检索、条目聚合、字节硬预算；该仓库未声明许可证，未复制其代码。
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

ROOT = os.environ.get("WX_HOME") or "/root/wx"
MEM_ROOT = os.path.join(ROOT, "memory")
LOG_FILE = os.path.join(MEM_ROOT, "log.md")
INDEX_FILE = os.path.join(MEM_ROOT, "MEMORY.md")
GRAPH_ON = True


def set_graph(on):
    global GRAPH_ON
    GRAPH_ON = bool(on)

ENTRY_RE = re.compile(r"^- \*\*(.+?)\*\*[：:]\s*(.*)$")
MAX_ENTRIES = 12         # 单次注入最多几条
MAX_BYTES = 1500         # 注入字节硬预算
ENTRY_WIDTH = 220        # 单条截断宽度（字符）
RECENT = 3               # 无论关键词是否命中，至少带上最近几条
LOG_KEEP = 300
COMMIT_EVERY = 60        # 秒，debounce
LINK_TOP = 3             # 每个记忆节点最多连几条（控制噪声和扩散范围）
LINK_MIN = 0.05          # 关联系数低于此不连边
SPREAD = 0.5             # 扩散衰减：邻居得分 = 种子得分 × 边权 × SPREAD
STOP = {"记得", "什么", "怎么", "这个", "那个", "就是", "你还", "你还", "我们",
        "他们", "现在", "可以", "要是", "因为", "所以", "但是", "已经", "一个",
        "没事", "行了", "是不", "不不", "好了", "知道"}

_LAST_COMMIT = [0.0]


def _key(s):
    return re.sub(r"[\s\W_]+", "", s or "")


def _clip(text, width):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= width else text[:width] + "…"


def _truncate(text, limit):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    marker = f"\n…（超过 {limit}B 预算，已截断）"
    room = max(0, limit - len(marker.encode("utf-8")))
    cut = raw[:room].decode("utf-8", "ignore")
    if "\n" in cut:
        cut = cut.rsplit("\n", 1)[0]
    return cut + marker


def person_dir(name):
    return os.path.join(MEM_ROOT, name)


def mem_path(name):
    return os.path.join(person_dir(name), "MEMORY.md")


def entries(name):
    out = []
    try:
        with open(mem_path(name), encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    for i, line in enumerate(text.splitlines(), 1):
        m = ENTRY_RE.match(line.strip())
        if m:
            out.append({"line": i, "title": m.group(1).strip(), "text": m.group(2).strip()})
    return out


def visible(name, ent=None):
    """去掉被后来的说法包含的旧条目：新条目信息更全时，旧的自动隐身（文件里仍在，可追溯）。"""
    es = entries(name) if ent is None else ent
    out = []
    for i, e in enumerate(es):
        ek = _key(e["text"])
        covered = any(
            j > i and len(ek) >= 6 and (_key(o["text"]).startswith(ek) or ek in _key(o["text"]))
            for j, o in enumerate(es)
        )
        if not covered:
            out.append(e)
    return out


def add(name, body, title="", source=""):
    """追加一条记忆；重复的直接跳过。返回新条目或 None。"""
    body = re.sub(r"^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}[:：]\d{1,2})?[：: ]*", "", (body or "").strip())
    body = " ".join(body.split())[:160]
    key = _key(body)
    if len(key) < 5:
        return None
    es = entries(name)
    keys = [_key(e["text"]) for e in es]
    if key in keys:
        return None
    # 新说法比旧条目多出信息时应当落盘（旧条目由 visible() 自动隐去），
    # 所以先判"覆盖"再判"换个说法讲同一件事"，否则更全的版本会被当成重复丢掉。
    if not any(len(k) >= 6 and k in key for k in keys):
        for k in keys:
            if difflib.SequenceMatcher(None, k, key).ratio() >= 0.85 and abs(len(k) - len(key)) <= 6:
                return None
    stamp = time.strftime("%Y-%m-%d %H:%M")
    head = f"{stamp} {title}".strip() if title else stamp
    os.makedirs(person_dir(name), exist_ok=True)
    if not es:
        with open(mem_path(name), "w", encoding="utf-8") as f:
            f.write(f"# {name} 的记忆\n\n_条目由她自己沉淀，一行一条；旧说法被新说法包含时自动隐身，但文件里保留可追溯。_\n\n")
    with open(mem_path(name), "a", encoding="utf-8") as f:
        f.write(f"- **{head}**：{body}\n")
    _log(name, body, source)
    _sync_index()
    if GRAPH_ON:
        link(name)
    commit()
    return {"title": head, "text": body}


def _log(name, body, source):
    try:
        os.makedirs(MEM_ROOT, exist_ok=True)
        lines = []
        if os.path.exists(LOG_FILE):
            lines = open(LOG_FILE, encoding="utf-8").read().splitlines()[-LOG_KEEP:]
        lines.append(f"## [{time.strftime('%Y-%m-%d %H:%M')}] {name}：{_clip(body, 60)}"
                     + (f"（{source}）" if source else ""))
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _sync_index():
    """MEMORY.md 只放一行索引，正文不进索引（协议同 dsh 记忆库）。"""
    try:
        rows = []
        for n in sorted(os.listdir(MEM_ROOT)):
            p = os.path.join(MEM_ROOT, n, "MEMORY.md")
            if not os.path.isfile(p):
                continue
            es = visible(n)
            if not es:
                continue
            rows.append(f"- {n}（{len(es)} 条）：{_clip(es[-1]['text'], 40)} → {n}/MEMORY.md")
        os.makedirs(MEM_ROOT, exist_ok=True)
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            f.write("# 记忆索引\n\n_详情在各人的 MEMORY.md，这里只留一行。_\n\n" + "\n".join(rows) + "\n")
    except Exception:
        pass


def keywords(hist_texts):
    """从最近几句话里取检索词：中文二元组 + 英文数字词。"""
    out = []
    for t in hist_texts:
        s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", t or "")
        for w in s.split():
            if w.isascii():
                if len(w) >= 3:
                    out.append(w.lower())
            else:
                out.extend(w[i:i + 2] for i in range(len(w) - 1))
    seen, uniq = set(), []
    for w in out:
        if w in STOP:
            continue
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq[:16]


def digest(name, hist_texts=(), budget=MAX_BYTES):
    """给生成用的记忆块：关键词命中的在前，不够再补最近的，整体受字节预算约束。"""
    vis = visible(name)
    if not vis:
        return ""
    kws = keywords(hist_texts)
    def hits(e):
        return sum(1 for k in kws if k in e["text"] or k in e["title"])
    scored = sorted(vis, key=lambda e: (-hits(e), -e["line"]))
    picked = [e for e in scored if hits(e) > 0][:MAX_ENTRIES]
    if len(picked) < RECENT:
        picked += [e for e in vis[-RECENT:] if e not in picked]
    text = "\n".join(f"- {e['title']}：{_clip(e['text'], ENTRY_WIDTH)}" for e in picked)
    return _truncate(text, budget)


def _bigrams(s):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def node_id(text):
    return hashlib.md5(_key(text).encode()).hexdigest()[:8]


def _sim(a, b):
    """重叠系数而非 Jaccard：中文短句两两长相差很大，Jaccard 会把真关联压到阈值以下。"""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def graph_path(name):
    return os.path.join(person_dir(name), "graph.json")


def load_graph(name):
    try:
        with open(graph_path(name), encoding="utf-8") as f:
            g = json.load(f)
    except Exception:
        g = {}
    g.setdefault("nodes", {})
    g.setdefault("edges", [])
    return g


def save_graph(name, g):
    os.makedirs(person_dir(name), exist_ok=True)
    tmp = graph_path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False)
    os.replace(tmp, graph_path(name))


def _link_one(g, cur, prev):
    """把 cur 接到 prev 里最相关的几条上（双向图，每个节点限流控制噪声）。"""
    cid = node_id(cur["text"])
    g["nodes"][cid] = {"text": cur["text"], "t": cur["title"], "line": cur["line"]}
    cand = []
    for e in prev:
        if e["text"] == cur["text"]:
            continue
        s = _sim(cur["text"], e["text"])
        if s >= LINK_MIN:
            oid = node_id(e["text"])
            cand.append((s, oid))
            g["nodes"].setdefault(oid, {"text": e["text"], "t": e["title"], "line": e["line"]})
    cand.sort(reverse=True)
    deg = {}
    for ed in g["edges"]:
        deg[ed["a"]] = deg.get(ed["a"], 0) + 1
        deg[ed["b"]] = deg.get(ed["b"], 0) + 1
    added = 0
    for s, oid in cand[:LINK_TOP * 2]:
        if added >= LINK_TOP or deg.get(oid, 0) >= LINK_TOP * 2:
            continue
        g["edges"].append({"a": cid, "b": oid, "w": round(s, 3)})
        added += 1
    return added


def link(name):
    es = entries(name)
    if not es:
        return 0
    g = load_graph(name)
    n = _link_one(g, es[-1], es[:-1])
    g["edges"] = g["edges"][-600:]
    save_graph(name, g)
    return n


def rebuild(name):
    """按现有条目重建整张链图（迁移/手工改过条目后跑一次）。"""
    save_graph(name, {"nodes": {}, "edges": []})
    es = entries(name)
    g = load_graph(name)
    for i in range(len(es)):
        _link_one(g, es[i], es[:i])
    g["edges"] = g["edges"][-600:]
    save_graph(name, g)
    return len(g["edges"])


def link_to(name, text, others, w=0.6):
    """按语义建立显式连线（由模型判断相关性），与字面相似度得到的边共存。"""
    g = load_graph(name)
    cid = node_id(text)
    g["nodes"].setdefault(cid, {"text": text, "t": "", "line": 0})
    added = 0
    for o in others:
        oid = node_id(o)
        if oid == cid or not o:
            continue
        if any((e["a"], e["b"]) in ((cid, oid), (oid, cid)) for e in g["edges"]):
            continue
        g["edges"].append({"a": cid, "b": oid, "w": w, "why": "语义"})
        added += 1
    g["edges"] = g["edges"][-600:]
    save_graph(name, g)
    return added


def activate(name, hist_texts=(), hops=1):
    """命中词做种子，再沿链扩散一跳：想起相关的事，而不只是字面匹配。"""
    vis = visible(name)
    if not vis:
        return []
    kws = keywords(hist_texts)
    byid = {node_id(e["text"]): e for e in vis}
    score = {}
    for nid, e in byid.items():
        hits = sum(1 for k in kws if k in e["text"] or k in e["title"])
        if hits:
            score[nid] = float(hits) * 2.0
    if not score:
        return vis[-RECENT:]
    if hops:
        g = load_graph(name)
        adj = {}
        for ed in g.get("edges", []):
            adj.setdefault(ed["a"], []).append((ed["b"], float(ed.get("w", 0.3))))
            adj.setdefault(ed["b"], []).append((ed["a"], float(ed.get("w", 0.3))))
        for nid, s in list(score.items()):
            for other, w in adj.get(nid, []):
                if other in byid:
                    score[other] = max(score.get(other, 0.0), s * w * SPREAD)
    order = sorted(score, key=lambda i: (-score[i], -byid[i]["line"]))
    return [byid[i] for i in order]


def digest(name, hist_texts=(), budget=MAX_BYTES):
    """给生成用的记忆块：记忆链开启时先关键词命中再沿链扩散；关闭时只做字面检索。"""
    vis = visible(name)
    if not GRAPH_ON:
        if not vis:
            return ""
        kws = keywords(hist_texts)
        def hits(e):
            return sum(1 for k in kws if k in e["text"] or k in e["title"])
        scored = sorted(vis, key=lambda e: (-hits(e), -e["line"]))
        picked = [e for e in scored if hits(e) > 0][:MAX_ENTRIES]
        if len(picked) < RECENT:
            picked += [e for e in vis[-RECENT:] if e not in picked]
        text = "\n".join(f"- {e['title']}：{_clip(e['text'], ENTRY_WIDTH)}" for e in picked)
        return _truncate(text, budget)
    picked = activate(name, hist_texts)[:MAX_ENTRIES]
    if not picked:
        return ""
    if len(picked) < RECENT:
        picked += [e for e in vis[-RECENT:] if e not in picked]
    text = "\n".join(f"- {e['title']}：{_clip(e['text'], ENTRY_WIDTH)}" for e in picked)
    return _truncate(text, budget)


def chain(name, limit=40):
    """文本版记忆链：最近的在上面，缩进的就是跟它连着的事。"""
    vis = visible(name)
    if not vis:
        return "(还没有记忆)"
    g = load_graph(name)
    byid = {node_id(e["text"]): e for e in vis}
    adj = {}
    for ed in g.get("edges", []):
        if ed["a"] in byid and ed["b"] in byid:
            adj.setdefault(ed["a"], []).append((ed["b"], float(ed.get("w", 0))))
            adj.setdefault(ed["b"], []).append((ed["a"], float(ed.get("w", 0))))
    lines, seen = [], set()
    for e in vis[::-1]:
        nid = node_id(e["text"])
        if nid in seen:
            continue
        lines.append(f"- {e['title']}：{_clip(e['text'], 60)}")
        seen.add(nid)
        for other, w in sorted(adj.get(nid, []), key=lambda x: -x[1])[:LINK_TOP]:
            if other in seen:
                continue
            o = byid[other]
            lines.append(f"    ↳ {w:.2f} {o['title']}：{_clip(o['text'], 50)}")
            seen.add(other)
        if len(seen) >= limit:
            break
    unlinked = len(vis) - len(seen)
    if unlinked > 0:
        lines.append(f"…另有 {unlinked} 条没接上链（跟别人共词太少）")
    return "\n".join(lines)


def svg(name, path):
    """把记忆链画成一张图，手机上直接能看。"""
    import math
    vis = visible(name)
    if not vis:
        return None
    g = load_graph(name)
    byid = {node_id(e["text"]): e for e in vis}
    ids = list(byid)
    W = H = 900
    cx = cy = 450
    R = 330
    pos = {}
    for i, nid in enumerate(ids):
        ang = 2 * math.pi * i / max(1, len(ids)) - math.pi / 2
        pos[nid] = (cx + R * math.cos(ang), cy + R * math.sin(ang))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           '<rect width="100%" height="100%" fill="#0f1115"/>']
    for ed in g.get("edges", []):
        a, b = ed.get("a"), ed.get("b")
        if a in pos and b in pos:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            w = float(ed.get("w", 0.2))
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                       f'stroke="#3b82f6" stroke-opacity="{min(0.85, 0.2 + w):.2f}" stroke-width="{0.6 + 3 * w:.1f}"/>')
    for nid, (x, y) in pos.items():
        e = byid[nid]
        label = _clip(e["text"], 16).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="7" fill="#f59e0b"/>')
        out.append(f'<text x="{x:.0f}" y="{y + 22:.0f}" fill="#e5e7eb" font-size="13" '
                   f'text-anchor="middle">{e["title"][5:10]} {label}</text>')
    out.append(f'<text x="{cx}" y="{cy}" fill="#6b7280" font-size="14" text-anchor="middle">{len(ids)} 条记忆 / {len(g.get("edges", []))} 条链</text>')
    out.append("</svg>")
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return path


def recent(name, k=1):
    vis = visible(name)
    return [_clip(e["text"], 30) for e in vis[-k:]]


def delete(name, idx):
    """按 entries() 的顺序删第 idx 条（从 1 开始）。"""
    es = entries(name)
    if not (1 <= idx <= len(es)):
        return False
    keep = [f"- **{e['title']}**：{e['text']}" for i, e in enumerate(es, 1) if i != idx]
    head = f"# {name} 的记忆\n\n_条目由她自己沉淀，一行一条；旧说法被新说法包含时自动隐身，但文件里保留可追溯。_\n\n"
    with open(mem_path(name), "w", encoding="utf-8") as f:
        f.write(head + "\n".join(keep) + "\n")
    _sync_index()
    commit(force=True)
    return True


def ensure_repo():
    """记忆目录做成 git 仓库：改了能 diff、能回滚（用户要求「像 Git 那样可追溯」）。"""
    if os.path.isdir(os.path.join(MEM_ROOT, ".git")):
        return True
    if not git_available():
        return False
    try:
        os.makedirs(MEM_ROOT, exist_ok=True)
        subprocess.run(["git", "init", "-q", MEM_ROOT], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        for k, v in (("user.name", "bot-memory"), ("user.email", "bot@local")):
            subprocess.run(["git", "-C", MEM_ROOT, "config", k, v], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        with open(os.path.join(MEM_ROOT, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("*.png\n*.tmp\n")
        commit(force=True)
        return True
    except Exception:
        return False


def git_available():
    return shutil.which("git") is not None


def commit(msg="digest: auto-commit memory store", force=False):
    if not os.path.isdir(os.path.join(MEM_ROOT, ".git")):
        return False
    now = time.time()
    if not force and now - _LAST_COMMIT[0] < COMMIT_EVERY:
        return False
    try:
        subprocess.run(["git", "-C", MEM_ROOT, "add", "-A"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        r = subprocess.run(["git", "-C", MEM_ROOT, "commit", "-m",
                            f"{msg} {time.strftime('%Y-%m-%d %H:%M')}"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        _LAST_COMMIT[0] = now
        return r.returncode == 0
    except Exception:
        return False
