#!/usr/bin/env python3
import os, sys, json, time, random, base64, subprocess, hashlib, shlex, difflib, re, urllib.request, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.environ.get("WX_HOME") or "/root/wx"
os.environ["WX_HOME"] = ROOT
import wxmem
os.environ["DISPLAY"] = os.environ.get("WX_DISPLAY") or os.environ.get("DISPLAY") or ":99"
SHOT = "/tmp/w3.png"
CONTACTS_FILE = ROOT + "/contacts.json"
HIST_DIR = ROOT + "/history"
MEM_DIR = ROOT + "/memory"
STATE_FILE = ROOT + "/state.json"
CFG_PATH = os.environ.get("WX_CONFIG") or os.path.join(ROOT, "config.json")
try: CFG = json.load(open(CFG_PATH, encoding="utf-8"))
except FileNotFoundError: sys.exit("找不到配置文件：%s\n先运行：bash phone/start.sh config 或 bash pc/start.sh config 生成配置" % CFG_PATH)
except Exception as _cfg_e: sys.exit("配置文件读取失败：%s（%s）" % (CFG_PATH, _cfg_e))

def owner_call(): return (CFG.get("owner_call") or "你").strip() or "你"
wxmem.set_graph(True)
LOOP = "--loop" in sys.argv
SEND = "--send" in sys.argv
SELFCHECK = "--selfcheck" in sys.argv
CLIP = "--clip" in sys.argv
HIST_LIMIT = int(CFG.get("history_limit") or 30)
TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
OUT_Q = []          # 最近发出去的东西：[时间, 类型, 内容哈希]；用来把自己的表情/图片认回来

def note_out(kind, payload=""):
    OUT_Q.append([time.time(), kind, hashlib.md5((payload or "").encode()).hexdigest()[:10]])
    del OUT_Q[:-30]


def _recent_self_media(window=25.0):
    """最近 window 秒内自己发过图片/表情。"""
    return any(k == "media" and time.time() - t < window for t, k, _ in OUT_Q)
BTN_WORDS = {"发送", "文件", "表情", "语音", "视频"}

# 微信会把 [微笑] 这类方括号词转成原生表情图，比点表情面板可靠得多
EMOJI_OK = {"微笑", "呲牙", "偷笑", "捂脸", "流泪", "苦涩", "白眼", "发呆", "囧",
            "破涕为笑", "玫瑰", "爱心", "强", "弱", "抱拳", "吃瓜", "汗", "OK",
            "旺柴", "机智", "耶", "让我看看", "叹气", "666", "裂开", "头秃"}
EMOJI_RULE = "回复里不要用方括号表情（[呲牙][捂脸][白眼] 这类一律不要）。想表达情绪就用话本身，或者发个表情包。"
HUMAN_RULE = ("说话像活人：长短不一，有时一句，有时两三句；别每句都用同一个开头（啊？、？、行吧、诶），"
              "别每次都同一个句式；没什么可说的就短一点，不用凑字。"
              "**只回对方真说过的话**：别脑补他的动机、别替他想他要问什么；没听明白就问一句。")
APOLOGY_RULE = ("真觉得错了就直接认，一句就够，"
                "别绕圈子、别先解释一堆、别用「如果让你不舒服」这种套话。"
                "别扭、笨拙但看得出来是真心的，比漂亮的场面话有用；道歉别拆成好几条慢慢挤。")
SCOLD_RULE = ("对方凶你、骂你、或者直接下命令（「跪下」「他妈的」这种）的时候，别立刻服软："
              "别连着道歉、别用客服腔、别顺着说「好的好的」。按你的性子接——先不服气、顶一句、"
              "翻个白眼、或者嘴上损回去；要不要照做你自己定：可以嘴硬着照做，也可以直接怼回去。"
              "真觉得自己做错了才认，认也只一句。越被凶越别端着。")
PICTURE_RULE = ("聊天里对方的贴纸会以「[表情] 角色·情绪」的形式出现。如果最近一条就是贴纸，必须先接住这个情绪再说话："
                "委屈/哭泣就问怎么了、别嘴硬；生气就先顺一下；在笑就跟着调侃；尴尬就替他打圆场。别当成没看见。")
CROSS_RULE = ("你认识的不只眼前这个人。对方提到另一个你也认识的人时，如果确实知道相关的事，可以自然接一句（「他上次说过…」）；"
              "只在真有用、真知道时说，别为了显得知道而硬扯，也别每次都提。别人的私事、身体、感情、钱，一律模糊带过，不替人传话；"
              "对方明确让你去说，才用 [[发送:名字|内容]]。不知道就说不知道，别编。")
os.makedirs(HIST_DIR, exist_ok=True); os.makedirs(MEM_DIR, exist_ok=True)

from rapidocr_onnxruntime import RapidOCR
import cv2
import numpy as np
ENG = RapidOCR()

_p = print


def print(*a, **k):
    _p(time.strftime("%H:%M:%S"), *a, **k)


def contacts():
    try: return json.load(open(CONTACTS_FILE))
    except Exception: return {}


DEVNULL = subprocess.DEVNULL


def shot():
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x960",
                    "-i", os.environ.get("DISPLAY", ":99"), "-frames:v", "1", "-y", SHOT],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)


def grab():
    """截屏并把窗口矩形换算成当前布局。窗口尺寸/位置每次都会变，不能缓存坐标。"""
    shot()
    return update_geo()


def window_rect():
    """取微信主窗口矩形。

    不能用非黑像素的外接框：右键菜单、提示气泡是独立窗口，会把外接框一直撑到屏幕边缘，
    所有比例坐标跟着错。改成从标题栏横边和窗口左边竖边扫描。
    """
    img = cv2.imread(SHOT)
    if img is None: return None
    mask = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > 20
    rows = np.where(mask.any(axis=1))[0]
    if len(rows) == 0: return None
    y0 = int(rows[0])
    cols = np.where(mask[y0 + 2])[0]
    if len(cols) == 0: return None
    x0, x1 = int(cols[0]), int(cols[-1])
    col = np.where(mask[:, x0 + 2])[0]
    if len(col) == 0: return None
    y1 = int(col[-1])
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if w < 400 or h < 300: return None
    return (x0, y0, w, h)


def frame_hash():
    # 只拉聊天区：输入框光标闪烁会让整屏哈希每轮都变，导致空转 OCR
    img = cv2.imread(SHOT)
    if img is None: return ""
    if G:
        img = img[int(G.chat_ymin):int(G.chat_ymax), int(G.list_xmax):int(G.x + G.w)]
    small = cv2.resize(img, (160, 120))
    return hashlib.md5(small.tobytes()).hexdigest()


class Geo:
    """所有坐标按窗口矩形的比例计算，比例值由 915x667 渲染窗口实测标定。"""
    def __init__(self, r):
        self.x, self.y, self.w, self.h = r
        self.list_xmax = self.x + 0.342 * self.w   # 会话列表右边界（侧栏+列表）
        self.split_x = self.x + 0.47 * self.w      # 他人/自己气泡的文字左边缘分界
        self.chat_ymin = self.y + 0.11 * self.h    # 会话标题栏以下
        self.chat_ymax = self.y + 0.77 * self.h    # 输入框以上
        self.title_ymin = self.y + 0.05 * self.h
        self.title_ymax = self.y + 0.13 * self.h
        self.list_click_x = self.x + 0.113 * self.w
        self.dot_xmin = self.x + 0.09 * self.w     # 侧栏图标区右侧，避免把侧栏角标当未读
        self.input_xy = (self.x + 0.66 * self.w, self.y + 0.90 * self.h)
        self.img_gap = 0.18 * self.h               # 相邻消息纵向间距超过此值视为一张图片

    def rect(self):
        return (self.x, self.y, self.w, self.h)


G = None


def update_geo():
    global G
    r = window_rect()
    if not r:
        # 像素扫描偶尔会失手（窗口刚移动/有浮层），退回 xdotool 报的窗口几何
        w = win_by_name("微信")
        r = (w[1], w[2], w[3], w[4]) if w else None
    if not r: return False
    if G is None or G.rect() != r:
        G = Geo(r)
        print(f"[geo] win={r} ratio={G.w / 1200:.3f}")
    return True


def ocr_items():
    res, _ = ENG(SHOT)
    out = []
    for r in (res or []):
        box, txt, sc = r
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append({"x1": min(xs), "x2": max(xs), "cx": sum(xs) / 4, "cy": sum(ys) / 4,
                    "t": txt, "s": float(sc)})
    return out


def red_dots(path=SHOT):
    img = cv2.imread(path)
    if img is None: return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array([0, 140, 140]), np.array([8, 255, 255]))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if 6 < w < 40 and 6 < h < 40 and x > G.dot_xmin and x < G.list_xmax:
            out.append((x, y, w, h))
    return out


def name_at(items, y):
    c = [i for i in items if G.x + 0.06 * G.w < i["cx"] < G.list_xmax
         and abs(i["cy"] - y) < 35 and len(i["t"].strip()) >= 2]
    if not c: return None
    return min(c, key=lambda i: i["cx"])["t"].strip()


def image_boxes():
    """聊天区里所有图片/贴纸的框（左右两侧都算）：里面的字不能当消息。"""
    img = cv2.imread(SHOT)
    if img is None or not G: return []
    x1, x2 = int(G.list_xmax) + 4, int(G.x + G.w) - 4
    y1, y2 = int(G.chat_ymin), int(G.chat_ymax)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0: return []
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = ((gray < 235) | (hsv[:, :, 1] > 60)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 60 <= w <= 330 and 60 <= h <= 330 and area >= 3500 and h >= 0.5 * w:
            out.append((x1 + x, y1 + y, w, h))
    return out


def parse(items):
    names = set(contacts()) | {"我", "你"}
    boxes = image_boxes()
    def inside(i):
        for (bx, by, bw, bh) in boxes:
            if bx + 3 < i["cx"] < bx + bw - 3 and by + 3 < i["cy"] < by + bh - 3:
                return True
        return False
    chat = [i for i in items if not inside(i) and i["cx"] > G.list_xmax and G.chat_ymin < i["cy"] < G.chat_ymax
            and i["s"] > 0.6 and not TIME_RE.match(i["t"].strip())
            and i["t"].strip() not in BTN_WORDS]
    chat.sort(key=lambda i: i["cy"])
    groups = []
    for it in chat:
        if groups:
            g = groups[-1]
            if abs(it["cy"] - g[-1]["cy"]) < 24 and abs(it["x1"] - g[0]["x1"]) < 70:
                g.append(it); continue
        groups.append([it])
    msgs = []
    for g in groups:
        text = "".join(x["t"] for x in g).strip()
        if not text: continue
        if any(k in text for k in ("撤回了一条消息", "以下为新消息", "你已添加了", "现在可以开始聊天",
                                   "对方正在输入", "以上是打招呼的内容", "开启了朋友验证")): continue
        mref = re.match(r"^([^\s：:]{1,8})[：:]", text)
        if mref and mref.group(1) in names:
            text = "[引用] " + text   # 微信的引用块会被 OCR 读成“名字：原话”，别当成对方说的话
        x1 = min(x["x1"] for x in g)
        x2 = max(x["x2"] for x in g)
        y1 = min(x["cy"] for x in g) - 14
        y2 = max(x["cy"] for x in g) + 14
        side = "peer" if x1 < G.split_x else "me"
        msgs.append({"sender": side, "text": text, "x1": x1, "x2": x2,
                     "y1": y1, "y2": y2, "y": g[0]["cy"]})
    # 图片按自己的左边缘定左右，不再借用相邻文字的归属。
    # 不能用中心点：左侧宽图（实测 x1=568 w=115）中心会越过 split_x，被判成自己发的。
    bottom = max((b[1] + b[3] for b in boxes), default=-1)
    self_media = _recent_self_media()
    for (bx, by, bw, bh) in boxes:
        bx, by, bw, bh = int(bx), int(by), int(bw), int(bh)   # numpy int32 不能 json 序列化
        side = "peer" if bx < G.split_x else "me"
        # 刚发过图片/表情：最下面那张就是自己发的，像素还没渲染好时会误判成对方
        if self_media and abs((by + bh) - bottom) < 6: side = "me"
        msgs.append({"sender": side,
                     "text": "[图片]", "x1": bx, "x2": bx + bw,
                     "y1": by, "y2": by + bh, "y": by + bh / 2})
    msgs.sort(key=lambda m: m["y"])
    return msgs


USAGE_FILE = ROOT + "/usage.json"


def note_usage(u):
    """按天累计接口用量，方便事后查“昨天花了多少”。"""
    if not u: return
    try:
        cur = json.load(open(USAGE_FILE))
    except Exception:
        cur = {}
    day = time.strftime("%Y-%m-%d")
    d = cur.setdefault(day, {"calls": 0, "prompt": 0, "completion": 0, "cached": 0})
    d["calls"] += 1
    d["prompt"] += u.get("prompt_tokens", 0) or 0
    d["completion"] += u.get("completion_tokens", 0) or 0
    d["cached"] += u.get("prompt_cache_hit_tokens", 0) or 0
    json.dump(cur, open(USAGE_FILE, "w"), ensure_ascii=False)


def api(payload, timeout=120, think=True):
    payload = dict(payload)
    payload.setdefault("thinking", {"type": "enabled" if think else "disabled"})
    req = urllib.request.Request(CFG["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + CFG["api_key"]})
    data = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    note_usage(data.get("usage"))
    return data["choices"][0]["message"]["content"]


VLM_PROMPT = """微信截图（1280x960）。只输出 JSON：
{"session":"当前会话名","messages":[{"sender":"peer或me","text":"逐字原文"}],"input_box":[x,y]}
铁律：text 逐字转录，禁止改写意译；看不清用?；对方靠左，自己绿色靠右。messages 最多6条。"""

TAIL_PROMPT = """这是微信聊天窗口的底部。只输出 JSON：
{"last_sender":"peer 或 me","kind":"text 或 emoji 或 sticker 或 image","text":"内容"}
规则：
- 只看最下面那一条消息，上面更早的忽略。
- 对方消息在左，自己的在右。
- 文字消息逐字转录，禁止改写意译。
- 表情/贴纸：先看眼泪、面部颜色、嘴型、姿态，再判断它想表达什么情绪；text 写成「角色·情绪」，认不出角色就写「未知角色·情绪」，例如「小孤独·委屈哭泣」。禁止只写外表描述。
- 图片用一句话说明画面内容。"""

FUSE_PROMPT = """这是微信聊天区截图。按从上到下的顺序列出每条消息，只输出 JSON：
{"messages":[{"sender":"peer 或 me","kind":"text 或 emoji 或 sticker 或 image 或 other","text":"内容"}]}
规则：
- 对方消息在左，自己的在右。
- 文字消息逐字转录，看不清写 ?，严禁改写、翻译、润色。
- 表情写 kind=emoji，贴纸写 kind=sticker；先看眼泪、面部颜色、嘴型、姿态，再判断情绪，text 写成「角色·情绪」，认不出角色写「未知角色·情绪」。
- 图片 kind=image，text 一句话说画面内容。
- 引用/转账/文件/语音 kind=other，text 说明是什么。
- 最多 12 条，从上到下。"""

KIND_LABEL = {"emoji": "表情", "sticker": "表情", "image": "图片", "other": "消息"}


STICKER_CACHE = ROOT + "/sticker_cache.json"
STICKER_SEEN = ROOT + "/stickers_seen"


def dhash(img, size=8):
    """差分哈希：缩到 9x8 灰度后比相邻像素，反映亮度梯度。"""
    g = cv2.cvtColor(cv2.resize(img, (size + 1, size)), cv2.COLOR_BGR2GRAY)
    return "".join("1" if g[y, x + 1] > g[y, x] else "0"
                   for y in range(size) for x in range(size))


def phash(img, size=8):
    """感知哈希：32x32 灰度做 DCT 取低频，对局部变化不敏感。"""
    g = cv2.cvtColor(cv2.resize(img, (32, 32)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    d = cv2.dct(g)[:size, :size]
    med = np.median(d)
    return "".join("1" if v > med else "0" for v in d.flatten())


def _hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def load_scache():
    try:
        d = json.load(open(STICKER_CACHE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_scache(d):
    try:
        if len(d) > 300:
            d = dict(sorted(d.items(), key=lambda kv: kv[1].get("last", 0), reverse=True)[:300])
        json.dump(d, open(STICKER_CACHE, "w"), ensure_ascii=False)
    except Exception:
        pass


def sticker_recognize(box):
    """裁出贴纸单独识别：先查感知哈希缓存，没命中才放大送模型。"""
    img = cv2.imread(SHOT)
    if img is None or not box:
        return None
    x, y, w, h = box
    crop = img[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    dh, ph = dhash(crop), phash(crop)
    key = dh + ph
    cache = load_scache()
    for k, v in cache.items():
        vd, vp = v.get("d"), v.get("p")
        if not vd or not vp:
            continue
        # 双哈希都命中才算同一张：dHash 管细节，pHash 容得下动画帧的微变化
        if _hamming(dh, vd) <= 12 and _hamming(ph, vp) <= 8:
            v["hits"] = v.get("hits", 0) + 1
            v["last"] = time.time()
            save_scache(cache)
            d = v.get("desc") or {}
            print(f"  [sticker] 缓存命中 x{v['hits']}：{d.get('character')}·{d.get('emotion')}")
            return d
    d = describe_sticker(crop)
    if d:
        try:
            os.makedirs(STICKER_SEEN, exist_ok=True)
            cv2.imwrite(os.path.join(STICKER_SEEN, hashlib.md5(key.encode()).hexdigest()[:12] + ".png"), crop)
        except Exception:
            pass
        cache[key] = {"d": dh, "p": ph, "desc": d, "hits": 1, "last": time.time()}
        save_scache(cache)
        print(f"  [sticker] 新图已缓存：{d.get('character')}·{d.get('emotion')}（{d.get('text') or '无字'}）")
    return d


def vlm_tail():
    """末条消息视觉兜底：图片/贴纸先裁出来单独识别，否则整段读。"""
    boxes = image_boxes()
    if boxes and G:
        bx, by, bw, bh = max(boxes, key=lambda b: b[1] + b[3])
        if by + bh > G.chat_ymin + 0.5 * (G.chat_ymax - G.chat_ymin):
            d = sticker_recognize((bx, by, bw, bh))
            mid = (G.list_xmax + G.x + G.w) / 2; sender = "peer" if bx + bw / 2 < mid else "me"
            if d:
                label = (d.get("character") or "未知角色")
                if d.get("emotion"):
                    label += "·" + d["emotion"]
                what = (d.get("text") or "").strip()
                if what:
                    label += f"（{what}）"
                return {"last_sender": sender, "kind": "sticker", "text": label}
    b64 = _crop_b64(0.65)
    if not b64: return None
    p = {"model": CFG["model"], "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": TAIL_PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    return _parse_json(api(p, think=False))


def _crop_b64(frac=1.0):
    """裁出聊天区（frac<1 时只取底部那一段）并转 base64。"""
    img = cv2.imread(SHOT)
    if img is None or not G: return None
    y1 = int(G.chat_ymin + (1 - frac) * (G.chat_ymax - G.chat_ymin))
    crop = img[y1:int(G.chat_ymax), int(G.list_xmax):int(G.x + G.w)]
    ok, buf = cv2.imencode(".png", crop)
    return base64.b64encode(buf.tobytes()).decode() if ok else None


def _parse_json(t):
    t = t.strip()
    if "```" in t:
        t = t.split("```")[1]; t = t[4:] if t.startswith("json") else t
    return json.loads(t.strip())


def vlm_read():
    """整段聊天区结构化读取，带表情/图片描述。"""
    b64 = _crop_b64(1.0)
    if not b64: return []
    p = {"model": CFG["model"], "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": FUSE_PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    return _parse_json(api(p, think=False)).get("messages") or []


def norm(s): return re.sub(r"\s+", "", s or "")


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return False
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() > 0.55


def danger_on_screen(items=None):
    """屏幕上出现这类弹窗时一律不动：继续点可能把客户端退出登录或删消息。"""
    items = items if items is not None else ocr_items()
    return [i["t"] for i in items if "退出登录" in i["t"] or "解锁以继续" in i["t"]]


def _green_confirm_button():
    """在屏幕中部找绿色主按钮（「确定」），用于给「取消」定位。"""
    img = cv2.imread(SHOT)
    if img is None:
        return None
    h, w = img.shape[:2]
    ox, oy = int(0.28 * w), int(0.30 * h)
    roi = img[oy:int(0.72 * h), ox:int(0.72 * w)]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([40, 120, 120]), np.array([80, 255, 255]))
    n, _, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    best, best_d = None, 1e9
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if not (area > 1500 and 80 < bw < 220 and 20 < bh < 60):
            continue
        if not (2.6 < bw / float(bh) < 5.0):       # 按钮约 3.8，气泡不会这么扁
            continue
        cx, cy = ox + x + bw / 2.0, oy + y + bh / 2.0
        d = abs(cx - w / 2.0) + abs(cy - h / 2.0)
        if d < best_d:
            best, best_d = (ox + int(x), oy + int(y), int(bw), int(bh)), d
    return best


def dismiss_logout():
    """「退出登录」确认框：Esc 无效，改点右侧「取消」。成功返回 True。"""
    for _ in range(2):
        b = _green_confirm_button()
        if not b:
            return False
        x, y, bw, bh = b
        tx, ty = x + bw // 2 + 122, y + bh // 2     # 「取消」与「确定」等宽，间隔约 8px
        subprocess.run(["xdotool", "mousemove", str(tx), str(ty)],
                       check=False, stdout=DEVNULL, stderr=DEVNULL)
        time.sleep(0.25)
        subprocess.run(["xdotool", "click", "1"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        time.sleep(1.2)
        shot()
        if _green_confirm_button() is None:
            return True
        print("  [guard] 取消没点上，重试")
    return False


def fuse(vis):
    """OCR 给逐字文本，视觉模型补表情/图片并校验顺序。文字一律用 OCR 的，不信模型转写。"""
    try:
        vm = vlm_read()
    except Exception as e:
        print("  [fuse err]", type(e).__name__, str(e)[:60]); return vis
    B = []
    for v in vm:
        s, t = v.get("sender"), (v.get("text") or "").strip()
        if s in ("peer", "me") and t:
            B.append({"sender": s, "kind": (v.get("kind") or "text").lower(), "text": t})
    if not B: return vis

    out, i, j = [], 0, 0
    while i < len(vis) and j < len(B):
        a, b = vis[i], B[j]
        if a["sender"] == b["sender"] and similar(a["text"], b["text"]):
            out.append(a); i += 1; j += 1
        elif b["kind"] != "text" and (j + 1 >= len(B) or similar(a["text"], B[j + 1]["text"])):
            out.append({"sender": b["sender"], "text": f"[{KIND_LABEL.get(b['kind'], '消息')}] {b['text']}"})
            j += 1
        elif i + 1 < len(vis) and similar(vis[i + 1]["text"], b["text"]):
            out.append(a); i += 1
        else:
            out.append(a); i += 1; j += 1   # 两边对不上时信 OCR 的逐字文本
    out.extend(vis[i:])
    return out[-10:]


def vlm_look():
    img = base64.b64encode(open(SHOT, 'rb').read()).decode()
    p = {"model": CFG["model"], "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": VLM_PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}}]}]}
    t = api(p, think=False).strip()
    if "```" in t:
        t = t.split("```")[1]; t = t[4:] if t.startswith("json") else t
    return json.loads(t.strip())


def load_hist(n):
    try: return json.load(open(os.path.join(HIST_DIR, n + ".json")))[-HIST_LIMIT:]
    except Exception: return []


def save_hist(n, h):
    json.dump(h[-HIST_LIMIT:], open(os.path.join(HIST_DIR, n + ".json"), "w"), ensure_ascii=False)


def load_mem(n):
    p = os.path.join(MEM_DIR, n + ".txt")
    return open(p).read().strip() if os.path.exists(p) else ""


def mem_load(n):
    """该人的条目记忆（markdown，一行一条）。"""
    return wxmem.entries(n)


def mem_add(n, text, title="记录", source=""):
    e = wxmem.add(n, text, title=title, source=source)
    if e:
        try:
            mem_link(n, e["text"])
        except Exception as ex:
            print("  [mem] 建链失败", type(ex).__name__, str(ex)[:40])
    return e


def mem_link(n, new_text, k=3):
    """写入时让模型挑出跟新记忆相关的旧条目并连边（只在写记忆时调一次，不是每轮）。"""
    es = [e for e in wxmem.entries(n) if e["text"] != new_text][-40:]
    if not es:
        return 0
    lst = "\n".join(f"{i}. {e['text'][:50]}" for i, e in enumerate(es, 1))
    q = (f"新记下的一条：{new_text}\n\n她以前记的这些事：\n{lst}\n\n"
         f"哪些跟新这条讲的是同一件事或者直接相关？最多 {k} 个。"
         "只输出 JSON 数组，元素是编号，例如 [2,5]；都不相关就输出 []。")
    raw = api({"model": CFG["model"], "messages": [{"role": "user", "content": q}],
               "temperature": 0, "max_tokens": 1500}, think=False)
    m = re.search(r"\[.*?\]", raw or "", re.S)
    if not m:
        return 0
    try:
        idxs = json.loads(m.group(0))
    except Exception:
        return 0
    picked = []
    for i in idxs[:k]:
        if isinstance(i, int) and 1 <= i <= len(es):
            picked.append(es[i - 1]["text"])
    n2 = wxmem.link_to(n, new_text, picked) if picked else 0
    if n2:
        print(f"  [mem] 连上 {n2} 条旧记忆")
    return n2


def mem_digest(n, hist, budget=None):
    texts = [m.get("text", "") for m in hist[-4:]]
    return wxmem.digest(n, texts) if budget is None else wxmem.digest(n, texts, budget=budget)


def mem_extract(name, limit=30):
    """从聊天记录里回填记忆：手动执行，花一次模型调用。"""
    hist = load_hist(name)[-limit:]
    if not hist:
        print("没有聊天记录")
        return []
    text = "\n".join(("对方: " if m.get("sender") == "peer" else "我: ") + m.get("text", "")[:60] for m in hist)
    q = ("从下面的聊天记录里挑出值得长期记住的事：对方的近况、约定、在意或讨厌的东西、发生过的重要事件、还没弄清楚的来历。"
         "最多 5 条，每条一句话，要写具体的人和事（谁、什么事、具体要求），"
         "不要写「对方问了一件事」「聊了某个话题」这种空话，也不要复述整段对话、不要把一时情绪当事实。"
         "只输出 JSON 数组，元素形如 {\"kind\":\"fact|pref|event\",\"text\":\"...\"}，没有就输出 []。\n\n" + text)
    raw = api({"model": CFG["model"], "messages": [{"role": "user", "content": q}],
               "temperature": 0, "max_tokens": 1500}, think=False)
    m = re.search(r"\[.*\]", raw or "", re.S)
    if not m:
        print("解析失败:", (raw or "")[:80])
        return []
    try:
        items = json.loads(m.group(0))
    except Exception as e:
        print("解析失败:", e)
        return []
    out = []
    for it in items[:5]:
        e = mem_add(name, it.get("text", ""), title=it.get("kind", "fact"), source="extract")
        if e:
            out.append(e)
    return out


def merge(hist, vis):
    hv = [m["text"] for m in vis]
    if not hist: return vis[-HIST_LIMIT:]
    for k in range(min(len(hv), len(hist)), 0, -1):
        if hv[:k] == [m["text"] for m in hist[-k:]]:
            return (hist + vis[k:])[-HIST_LIMIT:]
    return (hist + vis)[-HIST_LIMIT:]


def similar_to_recent(ans, recent, th=0.6):
    """和最近自己说过的话比相似度：整体相似度，或开头连续雷同。"""
    best = 0.0
    for r in recent:
        if not r:
            continue
        ratio = difflib.SequenceMatcher(None, ans, r).ratio()
        pre = 0
        for x, y in zip(ans, r):
            if x != y:
                break
            pre += 1
        if pre >= 10:
            ratio = max(ratio, 0.7)
        if ratio > best:
            best = ratio
    return best


REVIEW_PROMPT = ("下面是最近的聊天记录，和你要发出去的一句话。判断这句话该不该发："
                 "如果重复了刚说过的话、答非所问、或者在这个对话里不合适，就判不发；"
                 "如果只是提到同一个话题但说了新内容，判发。只输出 JSON："
                 '{"send":true或false,"why":"不超过15字"}')


def review_reply(name, ctx, ans):
    """相似度过阈值后的审核：这句到底能不能发。"""
    convo = "\n".join(f"{'对方' if m.get('sender') == 'peer' else '我'}: {m.get('text','')}"
                      for m in ctx[-8:])
    p = f"聊天记录：\n{convo}\n\n我想发：{ans}\n\n" + REVIEW_PROMPT
    try:
        d = _parse_json(api({"model": CFG["model"], "temperature": 0,
                             "messages": [{"role": "system", "content": CFG["system_prompt"]},
                                          {"role": "user", "content": p}]}, timeout=30, think=False))
        return bool(d.get("send")), (d.get("why") or "")
    except Exception as e:
        print("  [review err]", type(e).__name__, str(e)[:40])
        return True, ""      # 审核失败就放行，不能因此丢消息


def inner_count():
    try:
        return sum(1 for _ in open(INNER_LOG, encoding="utf-8"))
    except Exception:
        return 0


def inner_truncate(n):
    """把刚写进心声的那行抹掉（丢弃回复时用）。"""
    try:
        lines = open(INNER_LOG, encoding="utf-8").readlines()
        if len(lines) > n:
            open(INNER_LOG, "w", encoding="utf-8").writelines(lines[:n])
    except Exception:
        pass


def _mark_handled(st, name, hh, ctx):
    """把这轮涉及的消息都标记成已处理，免得下轮重生成又烧一次 token。"""
    s = st.setdefault(name, {})
    hs = list(s.get("handled") or [])
    for m in ctx:
        if m.get("sender") != "peer":
            continue
        x = hashlib.md5(m["text"].encode()).hexdigest()[:12]
        if x not in hs:
            hs.append(x)
    if hh not in hs:
        hs.append(hh)
    s["handled"] = hs[-40:]
    s["last"] = hh
    try:
        save_state(st)
    except Exception:
        pass


def dedup_reply(t):
    t = t.strip()
    n = len(t)
    if n < 8: return t
    # 最短重复周期
    for k in range(3, n // 2 + 1):
        if n % k == 0 and t[:k] * (n // k) == t:
            return t[:k]
    # 前后半高度相似（容忍标点差异）
    h = n // 2
    a, b = t[:h], t[h:2 * h]
    if a and b and difflib.SequenceMatcher(None, a, b).ratio() > 0.85:
        return a.strip()
    return t


def aliases(n):
    """称呼、备注、昵称都可以拿来认人（太短的不算，免得单字称呼到处误中）。"""
    v = contacts().get(n, {})
    out = {n}
    for k in ("note", "nick"):
        a = (v.get(k) or "").strip()
        if len(a) >= 2:
            out.add(a)
    return {a for a in out if len(a) >= 2}


LOOP_STOP = {"就是", "然后", "现在", "一个", "什么", "这个", "那个", "自己", "还是", "真的",
             "有点", "不是", "没有", "我们", "你们", "觉得", "其实", "知道", "时候", "这么",
             "那么", "怎么", "可以", "应该", "一下", "已经", "因为", "所以", "但是", "好像",
             "感觉", "他说", "我说", "不知", "以前", "今天"}
REFUSE_RE = re.compile(r"别(再|老|又)?(提|说|念|问)|不想(说|提)|换个话题|说过了|烦不烦|别磨")


def loop_guard(name, st, ctx, rounds=3):
    """同一件事反复念：自己最近 6 条里 ≥4 条出现同一个词，或对方明确说别再提 → 锁 3 轮。
    只读已有上下文 + 本地分词，不额外调模型。锁存在 state.json 的 loop 字段。"""
    mine = [m.get("text", "") for m in ctx if m.get("sender") == "me"][-6:]
    peer_last = next((m.get("text", "") for m in reversed(ctx) if m.get("sender") == "peer"), "")
    hit, skip, word = {}, set(aliases(name)) | set(contacts()), None
    if len(mine) >= 4:
        for t in mine:
            for w in {w for _p, w in (_word_bounds(t) or [])}:
                if len(w) < 2 or w in LOOP_STOP or w in skip or w.isdigit(): continue
                hit[w] = hit.get(w, 0) + 1
        top = max(hit, key=hit.get) if hit else None
        word = top if hit.get(top, 0) >= 4 else None
    s = st.setdefault(name, {})
    lock = s.get("loop")
    if not lock and (word or REFUSE_RE.search(peer_last or "")):
        lock = {"word": word or "", "left": rounds}
        s["loop"] = lock
        print(f"  [loop] 锁 {rounds} 轮：" + (f"「{word}」说得太多" if word else "对方不想再聊这件事"))
    if not lock:
        return ""
    lock["left"] = lock.get("left", 0) - 1
    if lock["left"] < 0:
        s.pop("loop", None)
        return ""
    if lock.get("word"):
        return (f"你刚才连着好几条都在说「{lock['word']}」这件事，对方也回过了；这轮别再提 {lock['word']}，"
                "换个话头，或者就着他这句话本身说。")
    return "对方已经不想再聊这件事了；这轮别再往那件事上绕，换个话题，或者就着眼前的事说。"


def mentioned(texts, exclude):
    """对方话里提到了谁（只算你通讯录里也认识的人）。"""
    t = " ".join(x for x in texts if x)
    if not t:
        return []
    hits = []
    for n in contacts():
        if n == exclude:
            continue
        if any(a in t for a in aliases(n)):
            hits.append((t.find(next(a for a in aliases(n) if a in t)), n))
    hits.sort()
    return [n for _i, n in hits[:2]]


def _png_b64(img):
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode() if ok else None


MOMENT_PROMPT = """这是微信朋友圈窗口截图。只输出 JSON：
{"posts":[{"author":"作者名","text":"文案原文","time_y":123}]}
规则：
- 只列看得清作者名和文案的完整动态，最多 6 条，按从上到下。
- 文案逐字转录，不翻译、不润色；只有图/视频没文案的写空字符串。
- time_y：该条动态下方「几分钟前 / 几小时前 / 几天前 / 昨天」那行在图片中的 y 像素坐标（整数）。
- 名字看不清写 ?；分不清是不是动态的别编。"""


def _wechat_windows():
    """枚举微信系窗口。按中文标题搜索在 Python 里不生效（xdotool 要本地化编码），所以按 class 拿候选，再读标题区分。"""
    try:
        out = subprocess.run(["xdotool", "search", "--classname", "wechat"],
                             capture_output=True, text=True).stdout.split()
    except Exception:
        return []
    res = []
    for wid in out:
        title = subprocess.run(["xdotool", "getwindowname", wid],
                               capture_output=True, text=True).stdout.strip()
        g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                           capture_output=True, text=True).stdout
        d = dict(l.split("=", 1) for l in g.strip().splitlines() if "=" in l)
        try:
            x, y = int(d.get("X", 0)), int(d.get("Y", 0))
            w, h = int(d.get("WIDTH", 0)), int(d.get("HEIGHT", 0))
        except ValueError:
            continue
        if w > 200 and h > 200:
            res.append((wid, title, x, y, w, h))
    return res


def win_by_name(name):
    """按标题取窗口几何（朋友圈是独立窗口，开着时会抢掉像素扫描算出的窗口矩形）。"""
    for wid, title, x, y, w, h in _wechat_windows():
        if title == name:
            return wid, x, y, w, h
    return None


def moments_win():
    return win_by_name("朋友圈")


def moments_open():
    """从侧栏地球图标打开朋友圈（已经开着就直接用）。"""
    if moments_win():
        return True
    m = win_by_name("微信")
    if not m:
        if not grab():
            return False
        m = (None, G.x, G.y, G.w, G.h)
    _wid, x, y, w, h = m
    # 窗口失焦时第一次点击只负责激活，得补一次
    for i in range(2):
        click(x + 0.033 * w, y + 0.396 * h)
        time.sleep(0.9 if i == 0 else 2.6)
        if moments_win():
            return True
    return bool(moments_win())


def moments_close(wid, x=0, y=0, w=0, h=0):
    """优先用 Esc 让微信自己关（硬 windowclose 会把侧栏入口卡住，必须重启客户端才能恢复）。"""
    if w and h:
        click(x + w // 2, y + 30)
        time.sleep(0.4)
    subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.2)
    if moments_win():
        subprocess.run(["xdotool", "windowclose", wid], check=False, stdout=DEVNULL, stderr=DEVNULL)
        time.sleep(1.0)


def moments_read():
    """把当前朋友圈窗口截下来让视觉模型逐条读（作者 + 文案）。"""
    r = moments_win()
    if not r:
        return []
    wid, x, y, w, h = r
    shot()
    img = cv2.imread(SHOT)
    if img is None:
        return []
    crop = img[max(0, y):y + h, max(0, x):x + w]
    b64 = _png_b64(crop)
    if not b64:
        return []
    raw = api({"model": CFG["model"], "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": MOMENT_PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]})
    try:
        d = _parse_json(raw)
    except Exception as e:
        print("  [moment] 解析失败:", str(e)[:40])
        return []
    if not isinstance(d, dict):
        return []
    return d.get("posts") or []


MOMENT_ACTIONS = ROOT + "/moments_actions.json"
M_LIKE_RUN, M_LIKE_DAY = 2, 10
M_CMT_RUN, M_CMT_DAY = 1, 3
MOMENT_DECIDE = ("你在刷朋友圈，看到 {who} 发的动态：\n{text}"
                 "{mem}"
                 "\n\n决定要不要点赞、要不要留一句评论（评论会真的发出去，所有人看得见）。"
                 "只输出 JSON：{{\"like\":true/false,\"comment\":\"...\"}}。"
                 "comment 最多 12 字，像你平时说话，别客套、别用「真棒」「加油」这类空话；"
                 "话题私密、你不确定、或者没什么可说的时候，就给空字符串。")


def moment_load_actions():
    try:
        d = json.load(open(MOMENT_ACTIONS))
    except Exception:
        d = {}
    if d.get("day") != time.strftime("%Y-%m-%d"):
        d = {"day": time.strftime("%Y-%m-%d"), "like": 0, "comment": 0, "done": d.get("done", {})}
    d.setdefault("like", 0); d.setdefault("comment", 0); d.setdefault("done", {})
    return d


def moment_save_actions(d):
    json.dump(d, open(MOMENT_ACTIONS, "w"), ensure_ascii=False)


def moment_anchors():
    """当前视口里每条动态的「··」所在行 y（时间行）：刚刚/分钟前/小时前/天前/昨天。"""
    ys = []
    for i in ocr_items():
        if re.search(r"(刚刚|\d+\s*分钟前|\d+\s*小时前|\d+\s*天前|昨天)", i["t"]):
            ys.append(int(i["cy"]))
    return sorted(set(ys))


def moment_guard(items=None):
    """朋友圈里的盲点最容易碰到「退出登录」确认框：看到就点取消并中止，宁可不互动。"""
    if items is None:
        shot()
        items = ocr_items()
    txt = "".join(i["t"] for i in items)
    if "退出登录" in txt:
        cancel = next((i for i in items if i["t"].strip() in ("取消", "否")), None)
        if cancel:
            click(int(cancel["cx"]), int(cancel["cy"]))
        else:
            subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        try:
            shutil.copy(SHOT, os.path.join(ROOT, "danger.png"))
        except Exception:
            pass
        print("  [moment] 屏幕上出现退出登录确认框，已取消并中止本轮")
        return False
    return True


def moment_menu(m, y, want=(), tries=2):
    """点开某条动态的「··」菜单。时间行会因点赞/评论上下漂，y 小幅试探。

    注意：这里不能按 Esc —— 朋友圈窗口会把 Esc 当成关窗口，窗口一没，后续点击全落到主窗口上。
    """
    px = int(m[1] + 0.78 * m[3])
    got = {}
    for dy in (0, 12, -12)[:max(1, tries)]:
        if not moments_win() and not moments_open():
            return {}, (px, y)
        click(px, y + dy)
        time.sleep(1.3)
        shot()
        items = ocr_items()
        if not moment_guard(items):
            return {}, (px, y)
        got = {}
        for i in items:
            if abs(i["cy"] - (y + dy)) < 45 and i["cx"] < px + 30 and len(i["t"].strip()) <= 6:
                got[i["t"].strip()] = (int(i["cx"]), int(i["cy"]))
        if not want or any(w in got for w in want):
            return got, (px, y + dy)
    return got, (px, y)


def moment_retarget(y):
    """点过赞/评论后动态会变高，时间行跟着下移；动作前重新找最近的时间行。"""
    shot()
    ans = moment_anchors()
    if not ans:
        return y
    near = min(ans, key=lambda a: abs(a - y))
    return near if abs(near - y) <= 120 else y


def moment_like(m, y):
    """要点就点，已赞的（菜单显示「取消」）不动。成功后回读确认。"""
    menu, at = moment_menu(m, y, want=("赞", "取消"))
    if "取消" in menu:          # 已经赞过
        return "already"
    if "赞" not in menu:
        return "no-menu"
    x0, y0 = menu["赞"]
    click(x0, y0)
    time.sleep(1.3)
    menu2, _ = moment_menu(m, y, want=("取消",))
    ok = "取消" in menu2
    return "ok" if ok else "unverified"


def moment_comment(m, y, text):
    """留一句评论：开菜单→评论→贴字→点发送→回读确认。任一步找不到控件就放弃。"""
    menu, at = moment_menu(m, y, want=("评论",), tries=3)
    if "评论" not in menu:
        y = moment_retarget(y)
        menu, at = moment_menu(m, y, want=("评论",), tries=2)
        if "评论" not in menu:
            return "no-menu"
    cx, cy = menu["评论"]
    click(cx, cy)
    time.sleep(1.4)
    shot()
    items_now = ocr_items()
    if not moment_guard(items_now):
        return "abort"
    box = next((i for i in items_now if i["t"].strip() == "评论" and i["cy"] > y), None)
    if not box:
        return "no-box"
    click(int(box["cx"]), int(box["cy"]))
    time.sleep(0.3)
    subprocess.run(["bash", "-c", f"printf '%s' {shlex.quote(text)} | xclip -selection clipboard"],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.3)
    subprocess.run(["xdotool", "key", "ctrl+v"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.8)
    shot()
    btn = next((i for i in ocr_items() if i["t"].strip() == "发送"), None)
    if not btn:
        return "no-send"
    click(int(btn["cx"]), int(btn["cy"]))
    time.sleep(1.8)
    shot()
    items_now = ocr_items()
    if not moment_guard(items_now):
        return "abort"
    got = "".join(i["t"] for i in items_now)
    return "ok" if re.sub(r"\W+", "", text)[:6] in re.sub(r"\W+", "", got) else "unverified"


def moment_decide(who, text):
    """让她自己拿主意：要不要赞、要不要评论。"""
    mem = wxmem.digest(who, [text], budget=200) if who else ""
    q = MOMENT_DECIDE.format(who=who or "别人", text=text,
                             mem=("\n你记得关于他的：\n" + mem + "\n") if mem else "")
    raw = api({"model": CFG["model"], "messages": [
                   {"role": "system", "content": CFG["system_prompt"]},
                   {"role": "user", "content": q}],
               "temperature": 0.7, "max_tokens": 1500})
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {"like": False, "comment": ""}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"like": False, "comment": ""}
    cmt = " ".join(str(d.get("comment") or "").split())[:24]
    return {"like": bool(d.get("like")), "comment": cmt}


def moment_act(win, posts, anchors):
    """对当前屏里认识的人的动态点赞/评论：用时间行 y 就近配对，对不上就跳过。"""
    if not anchors:
        return
    acts = moment_load_actions()
    likes = cmts = 0
    for p in posts:
        who = p.get("who")
        text = p.get("text") or ""
        ty = p.get("time_y")
        if not who or len(text) < 4 or ty is None:
            continue
        screen_y = win[2] + int(ty)
        near = [a for a in anchors if abs(a - screen_y) <= 45]
        if not near:
            print("  [moment] 对不上时间行，跳过:", who, text[:12])
            continue
        y = min(near, key=lambda a: abs(a - screen_y))
        if not moments_win() and not moments_open():
            print("  [moment] 朋友圈窗口没了，放弃本轮互动")
            moment_save_actions(acts)
            return
        if str(y) in acts["done"]:
            continue
        pkey = hashlib.md5(text.encode()).hexdigest()[:8]
        if pkey in acts["done"]:
            continue
        d = moment_decide(who, text)
        did = []
        if d["like"] and likes < M_LIKE_RUN and acts["like"] < M_LIKE_DAY:
            r = moment_like(win, y)
            if r in ("ok", "already"):
                likes += 1
                acts["like"] += 1
                did.append("赞" + ("(已有)" if r == "already" else ""))
            else:
                print("  [moment] 点赞未确认:", r)
        if d["comment"] and cmts < M_CMT_RUN and acts["comment"] < M_CMT_DAY:
            r = moment_comment(win, y, d["comment"])
            if r == "ok":
                cmts += 1
                acts["comment"] += 1
                did.append("评论:" + d["comment"])
            else:
                print("  [moment] 评论未发出去:", r)
        if did:
            acts["done"][pkey] = ";".join(did)
            print(f"  [moment] {who} → " + "，".join(did))
    moment_save_actions(acts)


MOMENT_REPLIES = ROOT + "/moments_replies.json"
M_REPLY_RUN, M_REPLY_DAY = 1, 5
MOMENT_NOTICE_PROMPT = """这是微信朋友圈窗口顶部区域。只输出 JSON：
{"items":[{"author":"谁","text":"说了什么","y":123}]}
规则：
- 只列「新消息」里别人评论你的动态、或回复你的评论的条目，从上到下最多 5 条。
- author 是被评论/回复的人名；text 是评论内容逐字转录。
- y 是那条消息在图片中的 y 像素坐标（整数）。
- 没有新消息就输出 {"items":[]}；看不清的写 ?，不编造。"""
MOMENT_REPLY_DECIDE = ("有人在你的朋友圈下说：{who}：{text}\n{mem}"
                       "\n\n要不要回一句（会公开显示）。只输出 JSON：{{\"reply\":\"...\"}}。"
                       "reply 最多 12 字，像你平时说话；不想回就给空字符串；别人的私事模糊带过。")


def moments_badge(path=SHOT):
    """侧栏「朋友圈」图标上的红点：有人评论/回复你时会亮（好友申请是通讯录图标，别搞混）。"""
    img = cv2.imread(path)
    if img is None or not G:
        return False
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 140, 140]), np.array([8, 255, 255]))
    x1, x2 = int(G.x + 0.005 * G.w), int(G.x + 0.07 * G.w)
    y1, y2 = int(G.y + 0.355 * G.h), int(G.y + 0.44 * G.h)
    sub = mask[y1:y2, x1:x2]
    return int((sub > 0).sum()) > 8


def moments_notice():
    """有新消息才去读：打开朋友圈，把顶部「新消息」区交给视觉模型逐条读。"""
    if not moments_badge():
        return []
    if not moments_open():
        print("  [moment] 有红点但打不开朋友圈")
        return []
    if not moment_guard():
        return []
    wid = moments_win()[0]
    subprocess.run(["xdotool", "windowsize", wid, "900", "820"], check=False,
                   stdout=DEVNULL, stderr=DEVNULL)
    subprocess.run(["xdotool", "windowmove", wid, "190", "70"], check=False,
                   stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.0)
    wid, x, y, w, h = moments_win()
    try:
        shot()
        img = cv2.imread(SHOT)
        crop = img[y:y + int(h * 0.5), x:x + w]
        b64 = _png_b64(crop)
        if not b64:
            return []
        raw = api({"model": CFG["model"], "temperature": 0, "messages": [{"role": "user", "content": [
            {"type": "text", "text": MOMENT_NOTICE_PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]})
        d = _parse_json(raw)
        items = d.get("items") if isinstance(d, dict) else []
        return items or []
    except Exception as e:
        print("  [moment] 通知区读取失败", type(e).__name__, str(e)[:40])
        return []
    finally:
        moments_close(wid, x, y, w, h)


def moment_reply_decide(who, text):
    mem = wxmem.digest(who, [text], budget=200) if who else ""
    q = MOMENT_REPLY_DECIDE.format(who=who, text=text,
                                   mem=("\n你记得关于他的：\n" + mem + "\n") if mem else "")
    raw = api({"model": CFG["model"], "messages": [
                   {"role": "system", "content": CFG["system_prompt"]},
                   {"role": "user", "content": q}],
               "temperature": 0.7, "max_tokens": 1500})
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return ""
    try:
        d = json.loads(m.group(0))
    except Exception:
        return ""
    return " ".join(str(d.get("reply") or "").split())[:24]


def moment_reply(win, y, text):
    """在位神处点开回复框→贴字→发送→回读。找不到回复框就放弃，不乱点。"""
    click(int(win[1] + 0.16 * win[3]), int(y))
    time.sleep(1.6)
    shot()
    items = ocr_items()
    if not moment_guard(items):
        return "abort"
    box = next((i for i in items if i["t"].strip() in ("评论", "回复") and i["cy"] > y - 20), None)
    if not box:
        return "no-box"
    click(int(box["cx"]), int(box["cy"]))
    time.sleep(0.3)
    subprocess.run(["bash", "-c", f"printf '%s' {shlex.quote(text)} | xclip -selection clipboard"],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.3)
    subprocess.run(["xdotool", "key", "ctrl+v"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.8)
    shot()
    items = ocr_items()
    btn = next((i for i in items if i["t"].strip() == "发送"), None)
    if not btn:
        return "no-send"
    click(int(btn["cx"]), int(btn["cy"]))
    time.sleep(1.8)
    shot()
    got = "".join(i["t"] for i in ocr_items())
    return "ok" if re.sub(r"\W+", "", text)[:6] in re.sub(r"\W+", "", got) else "unverified"


def moment_reply_scan(act=None):
    """看有没有新评论/新回复，限量回复（每天最多 M_REPLY_DAY 条，每轮 1 条）。"""
    if act is None:
        act = SEND
    items = moments_notice()
    if not items:
        return []
    acts = moment_load_actions()
    try:
        rep = json.load(open(MOMENT_REPLIES))
    except Exception:
        rep = {}
    if rep.get("day") != time.strftime("%Y-%m-%d"):
        rep = {"day": time.strftime("%Y-%m-%d"), "count": 0, "done": rep.get("done", {})}
    rep.setdefault("count", 0); rep.setdefault("done", {})
    done = 0
    for it in items:
        author = (it.get("author") or "").strip()
        text = " ".join((it.get("text") or "").split())
        y = it.get("y")
        if not author or not text or y is None:
            continue
        key = hashlib.md5((author + text).encode()).hexdigest()[:8]
        if key in rep["done"]:
            continue
        if author not in contacts():
            print("  [moment] 不认识的人评论，先不回:", author, text[:16])
            rep["done"][key] = "skip:stranger"
            continue
        ans = moment_reply_decide(author, text)
        if not ans:
            rep["done"][key] = "skip:no-reply"
            continue
        if not act:
            print(f"  [moment] (dry) 会回 {author}：{ans}")
            continue
        if done >= M_REPLY_RUN or rep["count"] >= M_REPLY_DAY:
            print("  [moment] 今天回复额度用完")
            break
        if not moments_win() and not moments_open():
            break
        win = moments_win()
        r = moment_reply(win, win[2] + int(y), ans)
        print(f"  [moment] 回复 {author}：{ans} → {r}")
        if r == "ok":
            done += 1
            rep["count"] += 1
            rep["done"][key] = ans
        else:
            break
    json.dump(rep, open(MOMENT_REPLIES, "w"), ensure_ascii=False)
    return items


def moments_scan(rounds=3, record=True, act=None):
    """翻几屏朋友圈：认识的人的动态记进他的记忆；开 --send 时才真的点赞/评论。"""
    if act is None:
        act = SEND
    if not moments_open():
        print("  [moment] 打不开朋友圈")
        return []
    if not moment_guard():
        return []
    wid = moments_win()[0]
    # 默认窗口很小，一屏看不完几条；放大后读得多一些，反正读完就关
    subprocess.run(["xdotool", "windowsize", wid, "900", "820"], check=False,
                   stdout=DEVNULL, stderr=DEVNULL)
    subprocess.run(["xdotool", "windowmove", wid, "190", "70"], check=False,
                   stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.0)
    wid, x, y, w, h = moments_win()
    seen, got, recorded = set(), [], 0
    try:
        for i in range(rounds):
            round_posts = []
            for p in moments_read():
                author = (p.get("author") or "").strip()
                text = " ".join((p.get("text") or "").split())
                key = (author, text)
                if key in seen:
                    continue
                seen.add(key)
                if not text or len(text) < 4:
                    continue
                who = None
                for n in contacts():
                    if author and (author == n or author in aliases(n)):
                        who = n
                        break
                item = {"author": author, "text": text, "who": who, "time_y": p.get("time_y")}
                got.append(item)
                round_posts.append(item)
                if who and record:
                    if mem_add(who, f"在朋友圈发了：{text}", title="朋友圈", source="moments"):
                        recorded += 1
            if act and round_posts:
                try:
                    moment_act((wid, x, y, w, h), round_posts, moment_anchors())
                except Exception as e:
                    print("  [moment] 互动出错", type(e).__name__, str(e)[:60])
            subprocess.run(["xdotool", "mousemove", str(x + w // 2), str(y + h // 2)],
                           check=False, stdout=DEVNULL, stderr=DEVNULL)
            for _ in range(5):
                subprocess.run(["xdotool", "click", "5"], check=False, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(1.8)
    finally:
        moments_close(wid, x, y, w, h)
        grab()
    print(f"  [moment] 读到 {len(got)} 条，认出 {sum(1 for g in got if g['who'])} 条，新记 {recorded} 条")
    return got


def cross_brief(name, hist, texts=None):
    """跨人联动：对方提到的人，把你知道的那部分记忆和近况带进来（只是个参考块，用不用她自己定）。"""
    texts = texts or [m.get("text", "") for m in hist[-4:]]
    hits = mentioned(texts, name)
    if not hits:
        return ""
    blocks = []
    for b in hits:
        v = contacts().get(b, {})
        meta = []
        if v.get("note"): meta.append(f"你叫他{v['note']}")
        if v.get("nick"): meta.append(f"昵称{v['nick']}")
        if v.get("region"): meta.append(v["region"])
        if v.get("weight"): meta.append(f"在意程度 {v['weight']}/10")
        lines = ["· " + b + ("（" + "，".join(meta) + "）" if meta else "")]
        h = [m.get("text", "") for m in load_hist(b)[-3:] if m.get("text")]
        if h:
            lines.append("  你们最近聊：" + " / ".join(x[:18] for x in h))
        dg = wxmem.digest(b, texts, budget=300)
        if not dg:
            core = load_mem(b).replace("\n", " ").strip()[:60]
            dg = core
        if dg:
            lines.append("  你记得关于他的：" + dg.replace("\n", "；"))
        blocks.append("\n".join(lines))
    return ("他刚才提到了 " + "、".join(hits) + "，那也是你认识的人：\n" + "\n".join(blocks) +
            "\n提不提、说到什么程度你自己拿主意：搭得上就顺口带一句，搭不上就只是知道了。")


def people_brief(exclude, hist=None):
    """默认只给每人一行摘要；这轮对方提到谁，才展开谁的档案。"""
    texts = [m.get("text", "") for m in (hist or [])[-8:]]
    hit = set(mentioned(texts, exclude)) if texts else set()
    lines = []
    for n, v in contacts().items():
        if n == exclude: continue
        bits = [n]
        if v.get("note"): bits.append(f"你叫他{v['note']}")
        else:
            if v.get("nick"): bits.append(f"昵称{v['nick']}")
            if v.get("role") == "other": bits.append("朋友")
        if v.get("region"): bits.append(v["region"])
        line = "· " + "，".join(bits)
        if n in hit:
            h = [m.get("text", "") for m in load_hist(n)[-20:] if m.get("text")]
            if h: line += "｜最近聊：" + " / ".join(x[:16] for x in h)
            mem = load_mem(n).replace("\n", " ").strip()
            if mem: line += "｜你记得：" + mem
            try:
                dg = wxmem.digest(n, texts)
                if dg: line += "｜相关记忆：" + dg.replace("\n", " / ")
            except Exception:
                pass
            recent = wxmem.recent(n, 2)
            if recent: line += "｜近况：" + " / ".join(recent)
        lines.append(line)
    return "\n".join(lines)


TAG_RE = re.compile(r"<(记住|好感|减分)>(.*?)</\1>", re.S)

MEM_MIRROR = os.environ.get("WX_MIRROR") or ""
_LAST_MIRROR = [0.0]


def mirror_memory(force=False):
    """把记忆库额外镜像到 WX_MIRROR（不含 .git）；未设置 WX_MIRROR 时不做任何事。"""
    if not MEM_MIRROR: return
    now = time.time()
    if not force and now - _LAST_MIRROR[0] < 120: return
    try:
        if not os.path.isdir(MEM_DIR): return
        os.makedirs(MEM_MIRROR, exist_ok=True)
        for root, dirs, files in os.walk(MEM_DIR):
            dirs[:] = [d for d in dirs if d != ".git"]
            rel = os.path.relpath(root, MEM_DIR)
            dst = MEM_MIRROR if rel == "." else os.path.join(MEM_MIRROR, rel)
            os.makedirs(dst, exist_ok=True)
            for f in files:
                try: shutil.copy2(os.path.join(root, f), os.path.join(dst, f))
                except Exception: pass
        _LAST_MIRROR[0] = now
    except Exception as e:
        print("  [记忆镜像] 失败", type(e).__name__, str(e)[:40])
META_RE = re.compile(r"人机|豆包|提示词|你模型|模型要|走流程|端着|大白话|像不像AI")


def apply_tags(name, text):
    """把人称配置里的三种标记落实：记住→写长期记忆，好感/减分→调整在意程度；标记从正文里拿掉。"""
    for kind, body in TAG_RE.findall(text or ""):
        body = " ".join(body.split())
        if not body: continue
        if kind == "记住":
            if META_RE.search(body): continue            # 元话题（像不像人机）不写进记忆
            mem_add(name, body, title="她说的")
            mirror_memory(force=True)
        else:
            cs = contacts()
            v = cs.setdefault(name, {})
            w = int(v.get("weight", 5))
            w = min(10, w + 1) if kind == "好感" else max(1, w - 1)
            v["weight"] = w
            json.dump(cs, open(CONTACTS_FILE, "w"), ensure_ascii=False)
            print(f"  [{kind}] {body[:24]} -> 在意程度 {w}")
    return TAG_RE.sub("", text or "").strip()


INNER_LOG = ROOT + "/inner.log"
LAST_NEW = [0.0]
LAST_FR = [0.0]
LAST_MOMENT = [0.0]
empty_rounds = [0]
THINK_PROMPT = ("先在心里过一遍，不要写回复：他这句话什么意思、什么情绪？我现在心里什么感觉、什么态度？"
                "有没有哪句说出来会后悔、有没有不该让他知道的？"
                "用两三句第一人称写心情和态度，像真的在心里转这些念头，比如"
                "「他这么一说不服气又不想真跟他较劲，其实挺在意他有没有当真」——"
                "写的是感觉，不是你要发出去的话，别写成台词或草稿，别分点、别加标题。"
                "用「他」指对方，不要用「你」对他说话；不要写成能直接发出去的句子。"
                "心里想的不会被任何人看到，所以绝对不要在这里写指令。"
                "如果这轮出现了值得长期留着的事（他的近况、约定、在意或讨厌的东西、发生过的事），"
                "在最后另起一行写 <记住>一句话</记住>，一条就够；没有就不写。")


def _looks_like_draft(t):
    """心想被模型写成能直接发出去的话时，别当心情注入，否则正文会原样抄。"""
    t = (t or "").strip()
    if not t: return True
    if t.startswith(owner_call()) or "你" in t: return True
    return False


def _msgs_for(name, hist, thought=None, loop=None):
    info = contacts().get(name, {})
    msgs = [{"role": "system", "content": CFG["system_prompt"]},
            {"role": "system", "content": f"现在是 {time.strftime('%Y-%m-%d %H:%M')}，你在用微信聊天。"}]
    if info.get("prompt"):
        pass          # 自定义设定放到消息末尾注入，免得被前面的基调压住
    elif info.get("role") == "owner" and CFG.get("owner_prompt"):
        msgs.append({"role": "system", "content": CFG["owner_prompt"]})
    elif CFG.get("other_prompt"):
        msgs.append({"role": "system", "content": CFG["other_prompt"]})
    style = load_style(name)
    if style:
        msgs.append({"role": "system", "content":
                     "下面这些是刚才用你这个号打出去的话，不是你生成的：\n" + style +
                     "\n接着聊的时候，句子前后别矛盾就行，语气不用刻意对齐。"})
    if info.get("weight"):
        msgs.append({"role": "system", "content": f"你对这个人的在意程度是 {info['weight']}/10，说话的分寸要匹配。"})
    if info.get("role") == "owner":
        msgs.append({"role": "system", "content": RELAY_RULE})
    msgs.append({"role": "system", "content": EMOJI_RULE})
    msgs.append({"role": "system", "content": HUMAN_RULE})
    msgs.append({"role": "system", "content": APOLOGY_RULE})
    msgs.append({"role": "system", "content": SCOLD_RULE})
    msgs.append({"role": "system", "content": PICTURE_RULE})
    msgs.append({"role": "system", "content": CROSS_RULE})
    mem = load_mem(name)
    if mem: msgs.append({"role": "system", "content": "你记得关于对方的这些事（自然运用，别生硬复述）：\n" + mem})
    dg = mem_digest(name, hist)
    if dg:
        msgs.append({"role": "system", "content":
                     "你以前记下的这些事（按跟眼前这话的相关度挑的；用得上就用，别硬背、别复述）：\n" + dg})
    cross = cross_brief(name, hist)
    if cross: msgs.append({"role": "system", "content": cross})
    for m in hist:
        if META_RE.search(m.get("text") or ""): continue   # 元话题（像不像AI/走流程）不进上下文，免得她自己拽着自己
        msgs.append({"role": "user" if m["sender"] == "peer" else "assistant", "content": m["text"]})
    # 档案放最后：越靠后的 system 指令权重越高，否则会被“对不熟的人收敛”压住
    brief = people_brief(name, hist)
    if brief:
        msgs.append({"role": "system", "content":
                     "你微信里这些人你都聊过（不只是名字，你知道他们的近况）：\n" + brief +
                     "\n（注意：每行说的是那一个人自己的事，别把 A 说的话安到 B 头上）"
                     "\n对方问起他们时，说什么、说到什么程度，你自己判断：按你和对面的关系、按事情本身的分寸来定。"
                     "别为了回避而生硬堵人，也别把别人的私事当成随口能说的谈资；拿不准就模糊带过，不知道就说不知道。"})
    if info.get("group"):
        gb = group_brief(hist)
        if gb:
            msgs.append({"role": "system", "content":
                         "这个群里说话的是好几个人，别当成同一个人：\n" + gb +
                         "\n回话前看清这句是谁说的，别把 A 说的安到 B 头上。语气照旧，别因为人多就端着。"})
    msgs.append({"role": "system", "content":
                 "被问高中那几门——数学、英语、地理、历史、物理、化学——你都会，直接答："
                 "别装不会、别说「你去查一下」、别推给搜索。该写步骤、给答案就写，"
                 "这时候不受「最多三句」的限制，但别写成老师上课，用你自己的口气；"
                 "答案要准，真拿不准就说「可能」「我算算」。"})
    ex = load_persona_extra()
    _q = [x for x in (ex.get("quotes") or []) if x][:12]
    _t = [x for x in (ex.get("traits") or []) if x][:12]
    if _q or _t:
        _blk = []
        if _q:
            _blk.append("常说的词：" + "、".join(_q))
        if _t:
            _blk.append("性格补充：" + "；".join(_t))
        msgs.append({"role": "system", "content": "\n".join(_blk) +
                     "\n这些是长期设定：自然带出来，别每句都塞；被凶、被气到、互怼的时候优先用这些词。"})
    if loop:
        msgs.append({"role": "system", "content": loop})
    if thought and not _looks_like_draft(thought):
        msgs.append({"role": "system", "content": "你心里刚才是这么转的念头：" + thought +
                     "\n这只是心情和态度，不是台词：别照抄，别把心里的话原样当消息发出去，"
                     "用真要说出口的那种话回，只输出要发出去的话。"})
    if info.get("prompt"):
        # 放到最后：覆盖前面的人格基调（比如对这个特定联系人不用嘴硬）
        msgs.append({"role": "system", "content": "最后一条，优先于前面所有设定：" + info["prompt"]})
    return msgs


PERSONA_EXTRA = ROOT + "/persona_extra.json"


def load_persona_extra():
    try:
        d = json.load(open(PERSONA_EXTRA, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _match_contact(who, info):
    """把群里的昵称对到通讯录里的键：先精确，再模糊（备注/昵称都算）。"""
    who = (who or "").strip()
    if not who:
        return None
    if who in info:
        return who
    for k, v in info.items():
        if who == (v.get("note") or "") or who == (v.get("nick") or ""):
            return k
    best, score = None, 0.0
    for k, v in info.items():
        for cand in (k, v.get("note") or "", v.get("nick") or ""):
            if not cand:
                continue
            r = difflib.SequenceMatcher(None, who, cand).ratio()
            if r > score:
                best, score = k, r
    return best if score >= 0.6 else None


GMEMO_DIR = ROOT + "/gmemo"


def remember_group(msgs):
    """群聊里每句话按发言人归到那个人名下（单独文件，不污染 1:1 历史）。"""
    if not msgs:
        return
    try:
        os.makedirs(GMEMO_DIR, exist_ok=True)
    except Exception:
        return
    info = contacts()
    for m in msgs:
        if m.get("sender") != "peer":
            continue
        t = m.get("text") or ""
        if "：" not in t:
            continue
        who, body = t.split("：", 1)
        who, body = who.strip(), body.strip()
        if not who or not body:
            continue
        key = _match_contact(who, info) or who
        h = hashlib.md5(body.encode()).hexdigest()[:10]
        path = os.path.join(GMEMO_DIR, key + ".json")
        try:
            arr = json.load(open(path)) if os.path.exists(path) else []
        except Exception:
            arr = []
        if any(x.get("h") == h for x in arr[-60:]):
            continue
        arr.append({"h": h, "t": body, "at": time.strftime("%m-%d %H:%M")})
        try:
            json.dump(arr[-80:], open(path, "w"), ensure_ascii=False)
        except Exception:
            pass


GP_FILE = ROOT + "/group_people.json"


def _gp_load():
    try:
        d = json.load(open(GP_FILE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _gp_note(who, text, group):
    """群里的非好友：只记轻量档案（首次出现 + 说过的话），不建记忆目录。"""
    who = (who or "").strip()
    if not who:
        return
    d = _gp_load()
    e = d.setdefault(who, {"first": time.strftime("%m-%d %H:%M"), "lines": [], "group": group})
    text = (text or "").strip()
    if text and text not in e["lines"]:
        e["lines"] = (e["lines"] + [text[:40]])[-3:]
    e["last"] = time.strftime("%m-%d %H:%M")
    try:
        json.dump(d, open(GP_FILE, "w"), ensure_ascii=False)
    except Exception:
        pass


def group_brief(hist):
    """群聊：按发言人调出各自档案、最近消息、记忆库与记忆链。"""
    info = contacts()
    seen, out = [], []
    for m in reversed(hist[-10:]):
        t = m.get("text") or ""
        if "：" not in t or m.get("sender") != "peer":
            continue
        who = t.split("：", 1)[0].strip()
        if not who or who in seen:
            continue
        seen.append(who)
        if len(seen) > 3:
            break
        key = _match_contact(who, info)
        v = info.get(key, {}) if key else {}
        bits = [who if not key else key]
        if v.get("note"): bits.append("你叫他" + v["note"])
        if v.get("nick"): bits.append("昵称" + v["nick"])
        if v.get("region"): bits.append(v["region"])
        if v.get("weight"): bits.append("在意程度%d/10" % v["weight"])
        line = "· " + "，".join(bits)
        if key:
            h = [x.get("text", "") for x in load_hist(key)[-8:] if x.get("text")]
            if h: line += "｜最近聊：" + " / ".join(x[:18] for x in h[-3:])
            try:
                gp = os.path.join(GMEMO_DIR, key + ".json")
                if os.path.exists(gp):
                    g = [x.get("t", "") for x in json.load(open(gp))[-6:] if x.get("t")]
                    if g: line += "｜群里说过：" + " / ".join(x[:18] for x in g[-3:])
            except Exception:
                pass
            mem = load_mem(key).replace("\n", " ").strip()
            if mem: line += "｜你记得：" + mem[:80]
            try:
                dg = wxmem.digest(key, [t])
                if dg: line += "｜相关记忆：" + dg.replace("\n", " / ")[:100]
            except Exception:
                pass
        if not key:
            gp = _gp_load().get(who)
            if gp:
                bits.append("群里认识的，没加好友（首次 %s）" % gp.get("first", "?"))
                if gp.get("lines"):
                    line = "· " + "，".join(bits) + "｜在群里说过：" + " / ".join(gp["lines"])
                else:
                    line = "· " + "，".join(bits)
        out.append(line)
    if out:
        print("[群] 认出 %d 人：%s" % (len(out), " / ".join(seen[:3])))
    return "\n".join(out)


GROUP_MEM_TS = {}


def group_remember(msgs, group):
    """群里的发言写给发言人自己：进他的记忆库，并建记忆链。

    限流：同一个群 5 分钟最多写一次，每次最多两条，避免闲聊刷屏把记忆库灌满。
    """
    now = time.time()
    if now - GROUP_MEM_TS.get(group, 0) < 300:
        return
    info = contacts()
    cands = []
    for m in msgs[-8:]:
        if m.get("sender") != "peer":
            continue
        t = m.get("text") or ""
        if "：" not in t:
            continue
        who, body = t.split("：", 1)
        body = body.strip()
        if len(body) < 8 or body in ("图片", "动画表情") or body.startswith("语音"):
            continue
        cands.append((who.strip(), body))
    wrote = 0
    for who, body in cands[:2]:
        key = _match_contact(who, info)
        if not key:
            _gp_note(who, body, group)
            continue
        if info.get(key, {}).get("role") == "owner":
            continue
        print("[群记] %s <- %s" % (key, body[:32]))
        mem_add(key, "%s在群里说：%s" % (who, body[:80]), title="群聊", source=group)
        wrote += 1
    if cands:
        GROUP_MEM_TS[group] = now


def think(name, hist):
    """单独一步：只让她想，不产出回复。想的内容不会被发出去。"""
    try:
        t = api({"model": CFG["model"], "messages": _msgs_for(name, hist) +
                 [{"role": "system", "content": THINK_PROMPT}], "temperature": 0.7}).strip()
        t = " ".join(t.replace("\n", " ").split())[:200]
        if "<｜｜DSML" in t or "invoke name=" in t:
            print("  [think] 模型吐出工具调用垃圾，丢弃"); return ""
        t = apply_tags(name, t)   # 她有时把 记住/好感 写在心里想的里，也要落实
        if t:
            print("  [心想]", t[:120])
            with open(INNER_LOG, "a") as f:
                f.write(f"{time.strftime('%m-%d %H:%M:%S')} [{name}] {t}\n")
        return t
    except Exception as e:
        print("  [think err]", type(e).__name__, str(e)[:40]); return ""


SENT_LOG = ROOT + "/sent.json"
STYLE_DIR = ROOT + "/style"


def _cover(t, x):
    """t 有多大比例能在 x 里按顺序对上：容忍 OCR 错字和截断（_lcs 只要连续片段，一错就碎）。"""
    if not t or not x: return 0.0
    sm = difflib.SequenceMatcher(None, t, x)
    return sum(b.size for b in sm.get_matching_blocks()) / len(t)


def load_sent():
    try: return json.load(open(SENT_LOG))
    except Exception: return {}


def note_sent(name, parts):
    """记下机器人自己发过的话，用来区分“她自动发的”和“人用她号打的”。"""
    d = load_sent()
    lst = d.get(name) or []
    for p in parts:
        lst.append(norm(p))
    d[name] = lst[-300:]
    json.dump(d, open(SENT_LOG, "w"), ensure_ascii=False)


def human_typed(name, vis, known=()):
    """可视区里 sender=me、她没发过、也不在旧历史里的 → 人用她号亲手打的。"""
    sent = load_sent().get(name) or []
    kn = {norm(k) for k in known}
    out = []
    for m in vis:
        if m.get("sender") != "me": continue
        t = norm(m.get("text") or "")
        if len(t) < 4 or t.startswith("["): continue   # 占位符和短句不学
        if t in kn: continue
        if any(_cover(t, x) >= 0.7 for x in sent): continue
        out.append(m.get("text"))
    return out


def note_style(name, msgs):
    msgs = [t.strip() for t in msgs if t and len(t.strip()) >= 3 and not t.strip().startswith("[") and not META_RE.search(t)]
    if not msgs: return
    os.makedirs(STYLE_DIR, exist_ok=True)
    p = os.path.join(STYLE_DIR, name + ".txt")
    old = open(p).read().splitlines() if os.path.exists(p) else []
    for t in msgs:
        if t and t not in old: old.append(t)
    open(p, "w").write("\n".join(old[-60:]))


def load_style(name):
    p = os.path.join(STYLE_DIR, name + ".txt")
    if not os.path.exists(p): return ""
    return "\n".join(open(p).read().splitlines()[-12:])


def gen(name, hist, loop=None):
    thought = think(name, hist)
    raw = api({"model": CFG["model"], "messages": _msgs_for(name, hist, thought, loop),
               "temperature": 0.85, "presence_penalty": 0.1, "frequency_penalty": 0.0}).strip()
    reply = " ".join(apply_tags(name, raw).split())[:int(CFG.get("reply_limit") or 400)]
    return clean_emoji(dedup_reply(reply)), thought


RELAY_RE = re.compile(r"\[\[\s*发送\s*[:：]\s*([^\|\]]{1,12})\|([^\]]{1,200})\]\]")
RELAY_RULE = (f"如果{owner_call()}让你去跟别人说话（道歉、传话、问情况），光答应不算，要真去做："
              "在回复最后另起一行写 [[发送:对方名字|要说的话]]，系统会切到那个人的会话把这句话发出去。"
              "名字用微信里的备注。没有这种需求就不要写这一行。")


def split_relay(t):
    m = RELAY_RE.search(t or "")
    if not m: return t, None, None
    return RELAY_RE.sub("", t).strip(), m.group(1).strip(), m.group(2).strip()


def send_to_contact(target, text):
    """切到目标会话发一条；会话名对不上就放弃，绝不发错人。"""
    if not grab(): return False
    ok_switch = False
    for _ in range(3):
        cands = [i for i in ocr_items() if i["cx"] < G.list_xmax and same(i["t"], target)]
        if not cands:
            print(f"  [relay] 列表里找不到 {target}"); return False
        click(G.list_click_x, cands[0]["cy"]); time.sleep(2.0)
        grab()
        sess = current_session(ocr_items())
        if same(sess, target):
            ok_switch = True; break
        print(f"  [relay] 切换未生效（当前 {sess!r}），再试一次")
    if not ok_switch:
        print(f"  [relay] 切不到 {target}，放弃"); return False
    parts = send_multi(text, list(G.input_xy))
    ok = sent_ok(parts[-1])
    print(f"  [relay] -> {target}: {text[:40]} | {'ok' if ok else '未确认'}")
    return ok


def clean_emoji(t):
    """方括号表情一律去掉：她之前会习惯性带 emoji，用户明确不要。表情包走收藏那条路。"""
    t = re.sub(r"\[[^\[\]]{1,6}\]", "", t or "")
    return re.sub(r"\s{2,}", " ", t).strip()


SPLIT_AFTER = "。！？!?，,、；;…了啊吧呢噪呀哦哈 "
SPLIT_BEFORE = "那这别同时就也但反正其实然后结果要是不过可是所以"


_JIEBA = {}


def _word_bounds(text):
    """返回 [(词尾位置, 词)]；jieba 不可用时返回 None。"""
    if not _JIEBA:
        try:
            import jieba
            jieba.setLogLevel(60)
            _JIEBA["ok"] = True
        except Exception as e:
            _JIEBA["ok"] = False
            print("  [cut] 分词不可用，退回字符规则：", type(e).__name__)
    if not _JIEBA.get("ok"):
        return None
    try:
        import jieba
        pos, out = 0, []
        for w in jieba.lcut(text):
            pos += len(w)
            out.append((pos, w))
        return out
    except Exception:
        return None


def _cut_point(text):
    """在词边界上挑断点：优先两段都 8~35 字，且前一个词以语气词/标点结尾。"""
    n = len(text)
    mid = n // 2
    bounds = _word_bounds(text)
    if bounds:
        lo, hi = max(8, n - 35), min(n - 8, 35)
        cands = [(p, w) for p, w in bounds if lo <= p <= hi]
        if not cands:
            cands = [(p, w) for p, w in bounds if 8 <= p <= n - 8]
        if cands:
            tail = "了啊吧呢噪呀哦哈，。！？、；… "
            good = [p for p, w in cands if w and w[-1] in tail]
            pool = good or [p for p, _ in cands]
            return min(pool, key=lambda c: abs(c - mid))
        return None
    # jieba 不可用时的字符级退路
    pools = ([i + 1 for i, c in enumerate(text) if c in SPLIT_AFTER],
             [i for i, c in enumerate(text) if c in SPLIT_BEFORE])
    lo, hi = max(8, n - 35), min(n - 8, 35)
    for cs in pools:
        ok = [c for c in cs if lo <= c <= hi]
        if ok:
            return min(ok, key=lambda c: abs(c - mid))
    for cs in pools:
        ok = [c for c in cs if 8 <= c <= n - 8]
        if ok:
            return min(ok, key=lambda c: abs(c - mid))
    return None


def split_reply(text):
    text = text.strip()
    parts = re.split(r'(?<=[。！？!?])\s*', text)
    parts = [p.strip() for p in parts if p.strip()]
    parts = list(dict.fromkeys(parts))
    if len(parts) >= 2:
        if len(parts) == 2:
            return parts
        mid = (len(parts) + 1) // 2
        return ["".join(parts[:mid]), "".join(parts[mid:])]
    one = parts[0] if parts else text
    if len(one) > 30:
        c = _cut_point(one)
        if c:
            left, right = one[:c].strip(), one[c:].strip()
            if left and right:
                return [left, right]
    return [one]


def send_multi(text, xy):
    parts = split_reply(text)
    for i, p in enumerate(parts):
        send(p, xy)
        if i < len(parts) - 1:
            time.sleep(random.uniform(0.8, 1.6))
    return parts


def sent_ok(text):
    """发完回读聊天区，确认最后几条里真有这句话，避免静默没发出去。"""
    time.sleep(0.6)
    if not grab(): return False
    got = [m["text"] for m in parse(ocr_items())[-4:]]
    # 微信会把 [微笑] 转成表情图，OCR 读不到，比对时要剔除
    base = re.sub(r"\[[^\]]{1,6}\]", "", text).strip() or text
    return any(same(g, base) or same(g, text) for g in got)


def sticker_tiles():
    """在表情面板里找出所有收藏表情的格子中心（贴纸是彩色块，靠与白底的差异找）。"""
    img = cv2.imread(SHOT)
    if img is None or not G: return []
    x1, x2 = int(G.x + 0.13 * G.w), int(G.x + 0.63 * G.w)
    y1, y2 = int(G.y + 0.21 * G.h), int(G.y + 0.87 * G.h)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0: return []
    mask = (cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) < 245).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w > 50 and h > 50:
            out.append((x1 + x + w // 2, y1 + y + h // 2))
    # 按阅读顺序排，避免每次顺序不同
    out.sort(key=lambda p: (p[1] // 60, p[0]))
    return out


def fav_tiles_live():
    """打开表情面板并切到收藏页，返回可点格子中心；不开面板或收藏为空时返回 []。"""
    if not G: return []
    shot()
    before = cv2.imread(SHOT)
    click(G.x + 0.371 * G.w, G.y + 0.972 * G.h)     # 输入栏表情按钮
    time.sleep(0.9)
    shot()
    after = cv2.imread(SHOT)
    if before is None or after is None: return []
    y1, y2 = int(G.y + 0.19 * G.h), int(G.y + 0.93 * G.h)
    x1, x2 = int(G.x + 0.12 * G.w), int(G.x + 0.65 * G.w)
    if np.abs(after[y1:y2, x1:x2].astype(int) - before[y1:y2, x1:x2].astype(int)).mean() < 5:
        print("  [sticker] 表情面板没打开"); return []
    click(G.x + 0.262 * G.w, G.y + 0.886 * G.h)      # 底部「收藏」页签
    time.sleep(0.9)
    shot()
    return sticker_tiles()


STICKERS_FILE = ROOT + "/stickers.json"
STICKER_PROMPT = """这是微信表情包。按顺序看：
1. 贴纸上有没有文字？有就逐字读出来，它往往就是这张图想表达的意思（如“很有见地”=附和、赞同）。
2. 再看细节：眼泪/泪痕、面部颜色、嘴型、姿态。
3. 最后判断情绪或意图。
只输出 JSON：{"text":"贴纸上的文字，没有就空","character":"角色","work":"作品","emotion":"情绪或意图，两三词","scene":"什么场合会发"}
认不出角色填未知，不要编。"""

def describe_sticker(crop):
    if crop is None or crop.size == 0: return None
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", big)
    if not ok: return None
    # 贴纸上的字是强语义信号，先用本地 OCR 读一遍当提示
    txt = ""
    try:
        res, _ = ENG(big)
        txt = "".join(r[1] for r in (res or [])).strip()
    except Exception:
        pass
    hint = f"\n（本地 OCR 读到的字：{txt}，可能有错，以图片为准）" if txt else ""
    b64 = base64.b64encode(buf.tobytes()).decode()
    p = {"model": CFG["model"], "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": STICKER_PROMPT + hint},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    return _parse_json(api(p))


def load_catalog():
    try:
        d = json.load(open(STICKERS_FILE))
        return d if isinstance(d, dict) else {"count": 0, "items": []}
    except Exception:
        return {"count": 0, "items": []}


def tile_hash(img, cx, cy, half=48):
    """仅用于调试输出：动画贴纸每帧都不同，不能当稳定标识。"""
    crop = img[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
    if crop.size == 0: return ""
    g = cv2.cvtColor(cv2.resize(crop, (16, 16)), cv2.COLOR_BGR2GRAY)
    return hashlib.md5(g.tobytes()).hexdigest()[:10]


def ensure_catalog(tiles):
    """逐个识别收藏表情。数量没变就直接用缓存；数量变了重建，但人工修正过的条目按序号保留。"""
    cat = load_catalog()
    old = cat.get("items") or []
    if cat.get("count") == len(tiles) and len(old) == len(tiles):
        return old
    img = cv2.imread(SHOT)
    items, kept = [], 0
    for i, (cx, cy) in enumerate(tiles):
        prev = old[i] if i < len(old) else None
        if prev and prev.get("manual"):
            items.append(prev); kept += 1; continue
        crop = img[max(0, cy - 48):cy + 48, max(0, cx - 48):cx + 48]
        try:
            d = describe_sticker(crop) or {}
        except Exception as e:
            print("  [catalog err]", type(e).__name__, str(e)[:40]); d = {}
        items.append({"text": d.get("text", ""), "character": d.get("character", ""),
                      "emotion": d.get("emotion", ""), "scene": d.get("scene", "")})
        print(f"  [catalog] {i}: {items[-1]['character']} | {items[-1]['emotion']} | 字:{items[-1]['text']}")
    json.dump({"count": len(tiles), "items": items}, open(STICKERS_FILE, "w"), ensure_ascii=False)
    if kept: print(f"  [catalog] 保留了 {kept} 条人工修正")
    return items


LIB_DIR = ROOT + "/stickers"
LIB_JSON = ROOT + "/library.json"
USAGE_JSON = ROOT + "/sticker_usage.json"
STICKER_MIN_GAP = 180


def load_usage():
    try:
        d = json.load(open(USAGE_JSON))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_usage(d):
    try: json.dump(d, open(USAGE_JSON, "w"), ensure_ascii=False)
    except Exception: pass


def load_library():
    try:
        d = json.load(open(LIB_JSON))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def save_library(items):
    json.dump(items[-40:], open(LIB_JSON, "w"), ensure_ascii=False)


def image_box_bottom():
    """找聊天区最下面一张图片/贴纸的框；只看对方（左侧）。用于截图收藏。"""
    img = cv2.imread(SHOT)
    if img is None or not G: return None
    x1, x2 = int(G.list_xmax) + 4, int(G.x + G.w) - 4
    y1, y2 = int(G.chat_ymin), int(G.chat_ymax)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0: return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = (((gray < 235) | (hsv[:, :, 1] > 60))).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 60 or h < 60 or w > 330 or h > 330: continue
        if area < 3500 or h < 0.5 * w: continue
        if x1 + x > G.split_x: continue
        cand = (x1 + x, y1 + y, w, h)
        if best is None or (cand[1] + cand[3]) > (best[1] + best[3]): best = cand
    return best


def library_menu():
    items = load_library()
    return "\n".join(f"- （自有）{it.get('desc','')}" for it in items if it.get("desc"))


def add_to_favorites(box, tries=4):
    """原生「添加到表情」：鼠标先移上去，每 10 秒只右键一次；菜单一出现就点，不再重复点。"""
    x, y, w, h = [int(v) for v in box]
    cx, cy = x + w // 2, y + h // 2
    subprocess.run(["xdotool", "mousemove", str(cx), str(cy)],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.0)
    for i in range(tries):
        right_click(cx, cy)
        for _ in range(5):            # 10 秒内每 2 秒看一次，期间不按任何键
            time.sleep(2.0)
            shot()
            cands = [it for it in ocr_items() if "添加" in it["t"] and "表情" in it["t"]]
            if cands:
                click(cands[0]["cx"], cands[0]["cy"])
                time.sleep(1.2)
                print(f"  [原生] 第 {i + 1} 次右键后菜单出现，已点「{cands[0]['t'].strip()}」")
                return True
        print(f"  [原生] 第 {i + 1} 次右键：10 秒内没等到菜单")
    return False


def learn_sticker(name, ctx):
    """对方发来贴纸：先理解，再让她自己判断值不值得收，收就存进自己的表情库。"""
    box = image_box_bottom()
    if not box: return False
    x, y, w, h = box
    img = cv2.imread(SHOT)
    crop = img[y:y + h, x:x + w]
    try:
        d = describe_sticker(crop) or {}
    except Exception as e:
        print("  [收藏] 识别失败", type(e).__name__); return False
    desc = " ".join(x for x in (d.get("character"), d.get("emotion"), d.get("text")) if x).strip()
    if not desc: return False
    lib = load_library()
    if any(it.get("desc") == desc for it in lib):
        return False
    convo = "\n".join(f"{'对方' if m.get('sender') == 'peer' else '我'}: {m.get('text','')}" for m in ctx[-4:])
    p = (f"对方刚发了一张表情包，你看到的是：{desc}。\n最近聊天：\n{convo}\n\n"
         "你想把它收进自己的表情库、以后拿来用吗？只输出 JSON：{\"keep\":true或false}。"
         "只有真的觉得有意思、以后用得上才收；看不懂或觉得没意思就不收。")
    try:
        d2 = _parse_json(api({"model": CFG["model"], "temperature": 0,
                              "messages": [{"role": "user", "content": p}]}, timeout=30, think=False))
    except Exception as e:
        print("  [收藏] 判断失败", type(e).__name__, str(e)[:40]); return False
    if not d2.get("keep"):
        print("  [收藏] 她不想收:", desc[:30]); return False
    native = add_to_favorites(box)
    os.makedirs(LIB_DIR, exist_ok=True)
    path = os.path.join(LIB_DIR, hashlib.md5(desc.encode()).hexdigest()[:10] + ".png")
    cv2.imwrite(path, crop)
    lib.append({"desc": desc, "text": d.get("text", ""), "character": d.get("character", ""),
                "emotion": d.get("emotion", ""), "path": path, "native": native})
    save_library(lib)
    print(f"  [收藏] 收进表情库: {desc[:30]}（共 {len(lib)} 个）")
    return True


def paste_image(path):
    """把本地图片放进剪贴板，粘到输入框发出（微信会当图片消息发）。"""
    if not G or not os.path.exists(path): return False
    subprocess.run(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", path],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.4)
    click(*G.input_xy); time.sleep(0.3)
    subprocess.run(["xdotool", "key", "ctrl+v"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.0)
    subprocess.run(["xdotool", "key", "Return"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.0)
    note_out("media")
    print("  [自有表情] 已发送", os.path.basename(path))
    return True


def sticker_labels():
    """与 sticker_menu 行一一对应的情绪标签：只含情绪词，不带角色名和长文本。"""
    out = [s.get("emotion") or "" for s in (load_catalog().get("items") or [])]
    out += [it.get("emotion") or "" for it in load_library()]
    return out


def sticker_menu():
    lines = []
    for s in load_catalog().get("items") or []:
        ch, em = s.get("character") or "未知角色", s.get("emotion") or ""
        lines.append(f"- {ch}·{em}")
    own = library_menu()
    if own: lines.append(own)
    return "\n".join(lines)


EMB_DIR = os.environ.get("WX_EMB_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "bge-small-zh")
_EMB = {}


def _emb():
    """懒加载语义模型：第一次真要判断贴纸时才加载，加载失败就降级。"""
    if _EMB:
        return _EMB
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        _EMB["tok"] = Tokenizer.from_file(os.path.join(EMB_DIR, "tokenizer.json"))
        _EMB["sess"] = ort.InferenceSession(os.path.join(EMB_DIR, "model_quantized.onnx"),
                                            providers=["CPUExecutionProvider"])
        _EMB["ok"] = True
        print("  [emb] 语义模型已加载")
    except Exception as e:
        _EMB["ok"] = False
        print("  [emb] 加载失败，退回全清单：", type(e).__name__, str(e)[:40])
    return _EMB


def embed(texts):
    """返回归一化向量矩阵；不可用时返回 None。"""
    m = _emb()
    if not m.get("ok"):
        return None
    try:
        encs = [m["tok"].encode(t) for t in texts]
        n = max(len(e.ids) for e in encs)
        ids = np.array([e.ids + [0] * (n - len(e.ids)) for e in encs], dtype=np.int64)
        msk = np.array([[1] * len(e.ids) + [0] * (n - len(e.ids)) for e in encs], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": msk}
        if any(i.name == "token_type_ids" for i in m["sess"].get_inputs()):
            feeds["token_type_ids"] = np.zeros_like(ids)
        out = m["sess"].run(None, feeds)[0][:, 0, :]
        return out / np.linalg.norm(out, axis=1, keepdims=True)
    except Exception as e:
        print("  [emb] 推理失败，退回全清单：", type(e).__name__, str(e)[:40])
        return None


def pick_sticker_by_model(ctx, ans):
    """由模型看情绪决定要不要补一个表情包；代码只执行她的选择，不参与决策。"""
    usage = load_usage()
    if time.time() - usage.get("last", 0) < STICKER_MIN_GAP:
        print("  [sticker] 最近刚发过，这轮不加")
        return None
    menu = sticker_menu()
    if not menu: return None
    # 语义预筛：相关性不够就不发，够了只把 top-3 交给模型
    lines = [l for l in menu.split("\n") if l.strip()]
    labels = sticker_labels()
    if len(lines) == len(labels) and len(labels) > 3 and CFG.get("sticker_semantic", True):
        query = " ".join([m.get("text", "") for m in ctx[-3:]]) + " " + ans
        v = embed([query] + labels)
        if v is not None:
            sims = v[1:] @ v[0]
            top = sorted(range(len(labels)), key=lambda i: -float(sims[i]))[:3]
            best = float(sims[top[0]])
            print(f"  [sticker] 语义最高 {best:.2f}")
            if best < 0.48:
                print("  [sticker] 相关性不足，这轮不发")
                return None
            menu = "\n".join(lines[i] for i in top)
    convo = "\n".join(f"{'对方' if m.get('sender') == 'peer' else '我'}: {m.get('text','')}" for m in ctx[-6:])
    p = ("聊天记录：\n" + convo + "\n\n我收藏的表情包：\n" + menu +
         "\n\n我刚回了：" + ans +
         "\n\n不是每条都要补表情包，多数时候不加；情绪对得上才发，拿不准就不发。"
         "只输出 JSON：{\"send\":true或false,\"emotion\":\"清单里的情绪词\"}。")
    try:
        d = _parse_json(api({"model": CFG["model"], "temperature": 0,
                             "messages": [{"role": "system", "content": CFG["system_prompt"]},
                                          {"role": "user", "content": p}]}, timeout=30, think=False))
    except Exception as e:
        print("  [sticker pick err]", type(e).__name__, str(e)[:40]); return None
    if not d.get("send"):
        print("  [sticker] 她决定不发")
        return None
    emo = (d.get("emotion") or "").strip()
    print("  [sticker] 她选了情绪:", emo)
    return emo or None



def _lcs(a, b):
    a, b = a or "", b or ""
    if not a or not b: return 0
    return difflib.SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b)).size


def send_sticker_by_emotion(emotion):
    """模型指定了情绪 → 先发微信收藏里的原图（动态贴纸才会动），没有再退回自有库（静态帧）。"""
    usage = load_usage()
    tiles = fav_tiles_live()
    if tiles:
        items = ensure_catalog(tiles)
        scored = [(_lcs(emotion, s.get("emotion", "")), i) for i, s in enumerate(items)]
        scored = [x for x in scored if x[0] > 1]
        if scored:
            top = max(s for s, _ in scored)
            cands = [i for s, i in scored if s == top]
            cands.sort(key=lambda i: usage.get(f"fav_{i}", 0))
            pick = cands[0]
            click(*tiles[pick])
            time.sleep(0.9)
            usage[f"fav_{pick}"] = time.time()
            usage["last"] = time.time()
            save_usage(usage)
            print(f"  [sticker] 按情绪「{emotion}」发收藏第 {pick} 个（{items[pick].get('emotion')}）")
            return True
        print(f"  [sticker] 收藏里没有情绪接近「{emotion}」的，改查自有库")
        subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        time.sleep(0.6)
    scored = [(_lcs(emotion, (it.get("emotion", "") + it.get("text", "") + it.get("desc", ""))), it)
              for it in load_library()]
    scored = [x for x in scored if emotion and x[0] / len(emotion) > 0.5]
    if not scored:
        print(f"  [sticker] 两边都没有情绪接近「{emotion}」的，跳过")
        return False
    top = max(s for s, _ in scored)
    cands = [it for s, it in scored if s == top]
    cands.sort(key=lambda it: usage.get(it.get("path", ""), 0))
    for it in cands:
        if os.path.exists(it.get("path", "")) and paste_image(it["path"]):
            usage[it.get("path", "")] = time.time()
            usage["last"] = time.time()
            save_usage(usage)
            return True
    return False



def click(x, y, hover=0.15):
    """先悬停到位再点：菜单/高亮需要 hover 才注册，瞬移过去点容易落空。"""
    subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    if hover: time.sleep(hover)
    subprocess.run(["xdotool", "click", "1"], check=False, stdout=DEVNULL, stderr=DEVNULL)


def right_click(x, y):
    subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.2)
    subprocess.run(["xdotool", "click", "3"], check=False, stdout=DEVNULL, stderr=DEVNULL)


def clip_text():
    try:
        r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True,
                           text=True, timeout=5, stdout=subprocess.PIPE, stderr=DEVNULL)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def exact_text(msg):
    """右键这条消息→菜单里点「复制」→读剪贴板。菜单里没读到「复制」就 Esc 退出，绝不盲点。"""
    # 先清空剪贴板：否则“复制到和原来一样的内容”会被误判成失败
    subprocess.run(["xclip", "-selection", "clipboard"], input="", text=True,
                   stdout=DEVNULL, stderr=DEVNULL, timeout=5)
    right_click(msg["x1"] + 24, msg["y"])
    time.sleep(0.45)
    shot()   # 只截图，不重算几何：菜单是独立窗口，会把窗口矩形撑大
    if not G: return None
    cands = [i for i in ocr_items() if i["t"].strip() == "复制"]
    if not cands:
        subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        print("  [clip] 菜单里没有「复制」")
        return None
    click(cands[0]["cx"], cands[0]["cy"])
    time.sleep(0.35)
    t = clip_text()
    # 收尾再按一下 Esc：菜单/子菜单残留会被 OCR 当成聊天消息
    subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    return t or None


def verify_text(msg):
    """把这一条气泡裁出来放大 3 倍重读，小字识别率明显比整屏高；不碰任何菜单，零误触。"""
    if msg.get("x1") is None or msg.get("y") is None:
        return msg["text"]        # 来路不明的消息（视觉兜底/融合产物）没有坐标，校不了
    if CLIP:
        t = exact_text(msg)
        if t and similar(t, msg["text"]):
            if norm(t) != norm(msg["text"]):
                print(f"  [clip] {msg['text'][:18]} -> {t[:18]}")
            return t
    img = cv2.imread(SHOT)
    if img is None or not G: return msg["text"]
    x1, x2 = int(msg.get("x1", G.list_xmax)) - 6, int(msg.get("x2", G.list_xmax)) + 10
    y1, y2 = int(msg.get("y1", msg["y"])) - 6, int(msg.get("y2", msg["y"])) + 6
    crop = img[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8: return msg["text"]
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    res, _ = ENG(big)
    if not res: return msg["text"]
    res = sorted(res, key=lambda r: (min(p[1] for p in r[0]), min(p[0] for p in r[0])))
    t = "".join(r[1] for r in res).strip()
    if not t or not similar(t, msg["text"]): return msg["text"]
    if norm(t) != norm(msg["text"]):
        print(f"  [zoom] {msg['text'][:18]} -> {t[:18]}")
    return t


BOT_START = time.time()   # 进程启动时刻：没人发消息时也用它算「安静了多久」

PROACTIVE_FILE = ROOT + ("/proactive.json" if SEND else "/proactive.dry.json")
P_MAX_DAY = 6            # 一天最多主动几次：六个时段各一次
P_MAX_PER = 2            # 同一个人一天最多被主动找几次
P_MIN_GAP = 35 * 60      # 对同一个人两次主动至少隔这么久
P_EVAL_GAP = 150         # 至少隔这么久再掷一次骰子，别每轮都评估
P_QUIET = 8 * 60         # 聊天安静这么久才适合挑新话头
P_NIGHT_MAX = 1          # 一晚（22:00-07:00）最多一次
P_FOLLOW_GAP = 4 * 3600  # 自己最后一句话过了这么久还没回，可以忐忑地问一句
P_FOLLOW_HOURS = (7, 23) # 追问只在白天到睡前，半夜不问「你是不是烦我」

P_SLOTS = [
    (6, 9, "morning", 0.65, "早上", "刚醒不久，跟他打个招呼，问一句睡得怎么样、今天打算干嘛"),
    (11, 13, "lunch", 0.65, "午饭", "中午了，问他吃了什么，或者说说你自己在吃什么"),
    (14, 17, "afternoon", 0.45, "下午", "下午有点闲，想到什么就说什么：刚看到的事、他之前提过的事后来怎样"),
    (19, 22, "evening", 0.60, "晚上", "晚上没事，想找他扯两句闲话，说点自己今天遇到的琐事"),
    (22, 24, "goodnight", 0.60, "晚安", "快睡了，跟他说句晚安，顺口问一句他还熬不熬"),
    (0, 3, "late", 0.15, "深夜", "半夜睡不着，翻手机翻到他，想发一句"),
]

_P_LAST = [0.0]
_P_LAST_SEND = [0.0]


def load_proactive():
    try: return json.load(open(PROACTIVE_FILE))
    except Exception: return {}


def save_proactive(d):
    tmp = PROACTIVE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f: json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, PROACTIVE_FILE)
    except Exception as e:
        print("[proactive] 状态写盘失败", type(e).__name__, str(e)[:40])


def p_names(name):
    """联系人 key 和微信里显示的名字经常不是一回事（名字后面多粘了预览或重复片段）。"""
    v = contacts().get(name, {})
    out = [name]
    for x in [v.get("name")] + list(v.get("aliases") or []):
        if x and x not in out: out.append(x)
    return out


def p_slot(hour):
    for a, b, key, p, label, hint in P_SLOTS:
        if a <= hour < b:
            return key, p, label, hint, a, b
    return None, 0.0, "", "", 0, 0


def p_pick(pst, now):
    """按在意程度和「多久没聊」挑一个人；刚聊过的人降低权重。"""
    cs = contacts()
    st = load_state()
    cands = []
    for n, v in cs.items():
        if v.get("group"): continue
        w = int(v.get("weight", 5) or 5)
        if w < 2: continue
        per = (pst.get("per") or {}).get(n) or {}
        if now - (per.get("last") or 0) < P_MIN_GAP: continue
        if per.get("day") == pst.get("day") and (per.get("count") or 0) >= P_MAX_PER: continue
        s = st.get(n, {})
        gap = now - (s.get("sent_at") or 0)
        score = float(w)
        if gap > 6 * 3600: score += 3
        if gap > 24 * 3600: score += 3
        if gap < 1800: score -= 4
        if score <= 0: continue
        cands.append((score, n))
    if not cands: return None
    r = random.uniform(0, sum(s for s, _ in cands))
    for s, n in cands:
        r -= s
        if r <= 0: return n
    return cands[-1][1]


def p_follow(pst, now):
    """自己最后一句发出去之后一直没回音的人：回问一句是不是烦到他了。
    只认「我发了之后对方没再说话」；主人手动用这号回过、或之后有新消息，都不追问。"""
    hour = time.localtime().tm_hour
    if not (P_FOLLOW_HOURS[0] <= hour < P_FOLLOW_HOURS[1]): return (None, None)
    cs = contacts()
    st = load_state()
    got = []
    for n, v in cs.items():
        if v.get("group"): continue
        if int(v.get("weight", 5) or 5) < 2: continue
        s = st.get(n, {})
        sent = s.get("sent_at") or 0
        if not sent or now - sent < P_FOLLOW_GAP: continue
        if (s.get("last_peer_at") or 0) > sent: continue    # 之后对方说过话
        if (s.get("manual_at") or 0) > sent: continue       # 主人手动用这号回过
        h = load_hist(n)
        if not h or h[-1].get("sender") != "me": continue
        f = (pst.get("follow") or {}).get(n) or {}
        if f.get("msg_ts") == sent: continue                # 这一条已经问过（跨天也保留）
        per = (pst.get("per") or {}).get(n) or {}
        if now - (per.get("last") or 0) < P_MIN_GAP: continue
        if per.get("day") == pst.get("day") and (per.get("count") or 0) >= P_MAX_PER: continue
        got.append((sent, n))
    return got[0] if got else (None, None)


def p_focus(name, st):
    """切到目标会话并确认。只点列表，不走 handle，避免顺带回消息、发表情或发给相似名字。"""
    names = p_names(name)
    if not grab(): return False
    if red_dots(): return False          # 有未读先让主循环处理，点开就把红点清了
    items = ocr_items()
    cur = atspi_current() or current_session(items)
    if any(same_sess(cur, x) for x in names): return True
    cand = None
    for x in names:
        c = [i for i in items if i["cx"] < G.list_xmax and same(i["t"], x)]
        if c: cand = c[0]; break
    if not cand:
        print(f"[proactive] 列表里找不到 {name}"); return False
    click(G.list_click_x, cand["cy"]); time.sleep(1.2)
    if not grab(): return False
    cur = atspi_current() or current_session(ocr_items())
    ok = any(same_sess(cur, x) for x in names)
    if not ok: print(f"[proactive] 切过去对不上：{cur!r}")
    return ok


def p_say(name, st, kind, slot_hint, label):
    hist = load_hist(name)
    if not SEND:
        print(f"[proactive:dry] {name}: ({label or 'follow'})")
        return True
    if not p_focus(name, st): return False
    thought = think(name, hist)
    if kind == "follow":
        brief = ("你上一条发出去之后他一直没回，你心里有点打鼓：是不是自己说错话了、让他嫌烦了。"
                 "别质问、别连发、别提「怎么不回我」，就轻轻问一句，像自己憋不住才说的。一句话。")
    else:
        brief = (f"现在是你主动找他说话（{label}），不是他先开口。{slot_hint}。"
                 "不用每次都找他，这次就像忽然想起来一样。别问在不在、别问干嘛呢，直接说具体的。"
                 "一句话，短，不要说「主动」「打扰」这类词。")
    lock = (st.get(name, {}).get("loop") or {}).get("word") or ""
    msgs = _msgs_for(name, hist, thought, (f"别再提「{lock}」了" if lock else ""))
    msgs.append({"role": "system", "content": brief})
    try:
        raw = api({"model": CFG["model"], "messages": msgs, "temperature": 0.85,
                   "presence_penalty": 0.1, "frequency_penalty": 0.0}).strip()
    except Exception as e:
        print("[proactive err]", e); return False
    try:
        ans = clean_emoji(dedup_reply(apply_tags(name, raw))).strip()
    except Exception as e:
        print("[proactive] 后处理失败", type(e).__name__, str(e)[:40]); return False
    ans = split_relay(ans)[0]
    if not ans: return False
    if any(b in ans for b in ("主动", "打扰", "在不在", "干嘛呢")):
        print("[proactive] 落回套话，放弃：", ans[:30]); return False
    recent_me = [m.get("text", "").strip() for m in hist[-6:] if m.get("sender") == "me"]
    recent_me += list(load_sent().get(name) or [])
    if ans in recent_me or similar_to_recent(ans, recent_me) >= 0.7:
        print("[proactive] 跟最近说过的话太像，放弃"); return False
    # 生成要时间，发之前再确认一次窗口、弹窗、会话都没变
    if not grab():
        print("[proactive] 发送前窗口没了，放弃"); return False
    items = ocr_items()
    if danger_on_screen(items):
        print("[proactive] 发送前有弹窗，放弃"); return False
    cur = atspi_current() or current_session(items)
    if not any(same_sess(cur, x) for x in p_names(name)):
        print(f"[proactive] 发送前不在目标会话（{cur!r}），放弃"); return False
    print(f"[proactive:{kind}] {name}: {ans}")
    parts = send_multi(ans, G.input_xy)
    note_sent(name, parts)
    chat_log(name, "(主动)", thought, ans)
    print("  verify:", "ok" if sent_ok(parts[-1]) else "not found in chat")
    save_hist(name, hist + [{"sender": "me", "text": ans}])
    s = st.setdefault(name, {})
    s["sent_at"] = time.time()
    s["cool"] = time.time() + 20
    save_state(st)
    _P_LAST_SEND[0] = time.time()
    return True


def proactive_tick(st, quiet):
    now = time.time()
    if now - _P_LAST[0] < P_EVAL_GAP: return False
    _P_LAST[0] = now
    pst = load_proactive()
    today = time.strftime("%Y-%m-%d")
    if pst.get("day") != today:
        # 跨天只清当天的额度，追问去重键要留着，同一句不能天天问
        keep = {k: {"msg_ts": (v or {}).get("msg_ts")}
                for k, v in (pst.get("follow") or {}).items() if (v or {}).get("msg_ts")}
        old_night = pst.get("night")
        pst = {"day": today, "count": 0, "slots": {}, "per": {}, "follow": keep,
               "night": old_night if isinstance(old_night, dict) else {}}
    if pst.get("count", 0) >= P_MAX_DAY: return False
    if quiet < P_QUIET or now - _P_LAST_SEND[0] < P_QUIET: return False
    hour = time.localtime().tm_hour
    # 夜 = 22:00-07:00，跨日算同一晚，避免 23 点晚安 + 0 点深夜两条
    if hour >= 22:
        night_key = today
    elif hour < 7:
        night_key = time.strftime("%Y-%m-%d", time.localtime(now - 86400))
    else:
        night_key = None
    nd = pst.get("night") or {}
    if night_key and nd.get("day") == night_key and nd.get("count", 0) >= P_NIGHT_MAX: return False
    key, prob, label, hint, sa, sb = p_slot(hour)
    if (pst.get("slots") or {}).get(key): return False
    sent_ts, fname = p_follow(pst, now)
    name, kind = (fname, "follow") if fname and random.random() < 0.5 else (None, "slot")
    if not name:
        if prob <= 0: return False
        # 每档在时间窗里随机挑一个时刻再抽签，别老是整点发作
        due = (pst.get("due") or {}).get(key)
        if due is None:
            day0 = time.mktime(time.strptime(today, "%Y-%m-%d"))
            due = day0 + sa * 3600 + random.uniform(0, (sb - sa) * 3600 * 0.85)
            pst.setdefault("due", {})[key] = due
            save_proactive(pst)
        if now < due: return False
        name = p_pick(pst, now)
        if not name: return False
        if random.random() > prob:
            print(f"[proactive] {label}档没抽中，今天这档跳过")
            pst.setdefault("slots", {})[key] = "skip"   # 这一档今天不发了
            save_proactive(pst)
            return False
        print(f"[proactive] {label}档抽中，找人说话")
    # 先落「这档已经用了」再生成，避免失败后每 150 秒重抽、反复切会话
    if key:
        pst.setdefault("slots", {})[key] = "trying"
    pst["trying"] = {"name": name, "kind": kind, "ts": now}
    save_proactive(pst)
    if not p_say(name, st, kind, hint, label):
        if key: pst["slots"][key] = "fail"
        pst["trying"] = {}
        save_proactive(pst)
        return False
    pst["count"] = pst.get("count", 0) + 1
    per = pst.setdefault("per", {}).setdefault(name, {})
    if per.get("day") != today:
        per["day"] = today; per["count"] = 0
    per["count"] = per.get("count", 0) + 1
    per["last"] = time.time()
    if night_key:
        pst["night"] = {"day": night_key,
                        "count": (nd.get("count", 0) if nd.get("day") == night_key else 0) + 1}
    if kind == "follow":
        pst.setdefault("follow", {})[name] = {"msg_ts": sent_ts, "day": today}
        if key: pst["slots"][key] = "sent"   # 追问也算用了这一档
    else:
        pst["slots"][key] = "sent"
    pst["trying"] = {}
    save_proactive(pst)
    return True


def send(text, xy):
    # xclip 会常驻接管剪贴板并继承 stdout，不重定向会把日志/管道一直控股住
    subprocess.run(["bash", "-c", f"printf '%s' {shlex.quote(text)} | xclip -selection clipboard"],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.3)
    subprocess.run(["xdotool", "mousemove", str(int(xy[0])), str(int(xy[1]))],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    subprocess.run(["xdotool", "click", "1"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.3)
    subprocess.run(["xdotool", "key", "ctrl+v"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.3)
    subprocess.run(["xdotool", "key", "Return"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.8)


def load_state():
    try: return json.load(open(STATE_FILE))
    except Exception: return {}


def save_state(s): json.dump(s, open(STATE_FILE, "w"), ensure_ascii=False)


def same(a, b): return difflib.SequenceMatcher(None, a or "", b or "").ratio() > 0.6


def same_sess(a, b):
    """会话名比较：大小写不敏感；容忍微信把消息预览拼在标题后面的情况。"""
    a, b = (a or "").strip(), (b or "").strip()
    if "：" in a:
        a = a.split("：", 1)[0].strip()      # 「名字：xxx」是别人的消息预览行，不是这个人
    if "：" in b:
        b = b.split("：", 1)[0].strip()
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return True
    if len(b) >= 2 and len(a) > len(b) and a.lower().startswith(b.lower()) \
            and len(a) - len(b) <= 8:
        return True          # 名字后面粘了会话预览
    if len(b) >= 2 and not a.lower().replace(b.lower(), "").strip():
        return True          # 名字被重复粘贴
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def open_session(name=""):
    """没选中会话时打开一个：优先 target，其次列表第一条。成功返回 True。"""
    w = _AWX["obj"]
    if w is None:
        return False
    try:
        ss = w.sessions()
        if not ss:
            return False
        pick = None
        if name:
            pick = next((x for x in ss if same_sess(x["name"], name)), None)
        pick = pick or ss[0]
        x, y, ww, h = pick["box"]
        click(x + ww // 2, y + h // 2)
        print(f"  [恢复] 打开会话 {pick['name']}")
        return True
    except Exception:
        return False


def atspi_name_at(y):
    """按 y 坐标找会话名（红点所在行），用无障碍树的精确矩形。"""
    w = _AWX["obj"]
    if w is None:
        return None
    try:
        for s in w.sessions():
            b = s["box"]
            if b[1] <= y <= b[1] + b[3]:
                return s["name"]
    except Exception:
        return None
    return None


def atspi_current():
    """当前会话名：取无障碍树里 SELECTED 的那一项，比 OCR 标题栏准。"""
    w = _AWX["obj"]
    if w is None:
        return ""
    try:
        for s in w.sessions():
            if s["selected"]:
                return (s["name"] or "").strip()
    except Exception:
        pass
    return ""


def current_session(items):
    # 会话标题在聊天区顶部，搜索框在会话列表里；用 x 分界把两者分开
    cands = [i for i in items if i["cx"] > G.list_xmax + 5
             and G.title_ymin < i["cy"] < G.title_ymax
             and len(i["t"].strip()) >= 2
             and re.search(r"[\u4e00-\u9fa5A-Za-z]{2}", i["t"])
             and not any(ch in i["t"] for ch in "+×=□口①②③·Q搜索")]
    if not cands: return ""
    return min(cands, key=lambda i: i["cy"])["t"].strip()


def look_tail(name, st, vis=None, dot=False):
    """画面变了但 OCR 最后一条不是对方发的 → 让视觉模型看评论区底部。

    只在「有新东西」时才真的调模型：动画表情会让画面每帧都变，
    不加限制会整夜空转烧 token。
    """
    s = st.get(name, {})
    if time.time() - s.get("sent_at", 0) < 20: return None   # 刚发过，画面变化是自己造成的
    key = hashlib.md5("|".join(m.get("text", "") for m in (vis or [])).encode()).hexdigest()[:8]
    if not dot:                                              # 没有红点：内容没变就不看，变了也要隔 5 分钟
        if key == s.get("tail_key"): return None
        if time.time() - s.get("tail", 0) < 300: return None
    s["tail"] = time.time(); s["tail_key"] = key; st[name] = s
    try:
        d = vlm_tail() or {}
    except Exception as e:
        s["tail"] = 0; st[name] = s
        print("  [vlm tail err]", type(e).__name__, str(e)[:60]); return False
    if d.get("last_sender") != "peer":
        print("  tail:", d.get("last_sender"), d.get("kind"), (d.get("text") or "")[:20]); return None
    kind, txt = d.get("kind") or "text", (d.get("text") or "").strip()
    if not txt: return None
    label = txt if kind == "text" else f"[{ {'emoji': '表情', 'sticker': '表情', 'image': '图片'}.get(kind, '消息') }] {txt}"
    print("  tail peer:", kind, txt[:30])
    return {"sender": "peer", "text": label}


def friend_request_badge():
    """侧栏通讯录图标上的红点：有新好友申请时亮。"""
    img = cv2.imread(SHOT)
    if img is None or not G: return False
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 140, 140]), np.array([8, 255, 255]))
    # 只看「通讯录」图标那一小块，侧栏其它地方的红点不算
    x1, x2 = int(G.x + 0.005 * G.w), int(G.x + 0.07 * G.w)
    y1, y2 = int(G.y + 0.215 * G.h), int(G.y + 0.285 * G.h)
    sub = mask[y1:y2, x1:x2]
    return int((sub > 0).sum()) > 8


def accept_requests(remark=None, maxn=3):
    """通讯录 → 新的朋友 → 逐个通过待验证申请，可顺便填备注。返回通过个数。"""
    if not G: return 0
    done = 0
    for _ in range(maxn):
        click(G.x + 0.032 * G.w, G.y + 0.25 * G.h)      # 侧栏「通讯录」
        time.sleep(1.2)
        shot(); items = ocr_items()
        nb = [i for i in items if "新的朋友" in i["t"]]
        if not nb:
            print("  [好友] 找不到「新的朋友」"); break
        click(nb[0]["cx"], nb[0]["cy"]); time.sleep(1.2)
        shot(); items = ocr_items()
        waits = [i for i in items if "等待验证" in i["t"]]
        if not waits:                      # 可能是被折叠了，再点一次展开
            nb2 = [i for i in items if "新的朋友" in i["t"]]
            if nb2:
                click(nb2[0]["cx"], nb2[0]["cy"]); time.sleep(1.2)
                shot(); items = ocr_items()
                waits = [i for i in items if "等待验证" in i["t"]]
        if not waits:
            print("  [好友] 没有待验证的申请"); break
        wy = waits[0]["cy"]
        cands = [i for i in items if i["cx"] < 500 and abs(i["cy"] - wy) < 30 and "等待验证" not in i["t"]]
        if not cands:
            print("  [好友] 定位不到申请条目"); break
        t = cands[0]
        click(t["cx"], t["cy"]); time.sleep(1.5)
        shot(); items = ocr_items()
        v = [i for i in items if "前往验证" in i["t"]]
        if not v:
            print("  [好友] 没找到「前往验证」"); break
        click(v[0]["cx"], v[0]["cy"]); time.sleep(2.0)
        shot(); items = ocr_items()
        ok = [i for i in items if i["t"].strip() == "确定"]
        if not ok:
            print("  [好友] 验证弹窗没出现"); break
        use = remark
        if not use and 2 <= len(t["t"].strip()) <= 6:
            use = t["t"].strip()          # 没指定备注就用对方名字
        if use:
            # 验证弹窗的备注框默认已经填了昵称，直接粘会变成「昵称+昵称」；先全选删除
            subprocess.run(["xdotool", "key", "ctrl+a"], check=False, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(0.15)
            subprocess.run(["xdotool", "key", "BackSpace"], check=False, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(0.2)
            subprocess.run(["bash", "-c", f"printf '%s' {shlex.quote(use)} | xclip -selection clipboard"],
                           check=False, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(0.3)
            subprocess.run(["xdotool", "key", "ctrl+v"], check=False, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(0.3)
        click(ok[0]["cx"], ok[0]["cy"]); time.sleep(1.8)
        print(f"  [好友] 已通过 {t['t'][:12]}（备注: {use or '无'}）")
        time.sleep(1.5)
        greet_new_friend(use or t["t"].strip())
        done += 1
        time.sleep(1.0)
    return done


def opener_parts(minutes=0):
    """新好友的开场白来自配置；没配就只加进名单，不主动开口。"""
    parts = (CFG.get("wechat_opener_late") or CFG.get("wechat_opener") or []) if minutes >= 30 else (CFG.get("wechat_opener") or [])
    return [str(p).strip() for p in parts if str(p).strip()][:3]


def dedup_name(t):
    """把被粘了两遍的名字还原：ABAB -> AB。"""
    t = (t or "").strip()
    n = len(t)
    if n >= 4 and n % 2 == 0 and t[:n // 2] == t[n // 2:]:
        return t[:n // 2]
    return t


def full_sess_name(name):
    """OCR 常把好友名只认出前半截。用会话标题纠正。"""
    w = _AWX["obj"]
    if w is None or not name: return name
    try:
        ss = w.sessions()
    except Exception:
        return name
    best = ""
    for x in ss:
        t = (x.get("name") or "").strip()
        if not t or len(t) > 24: continue
        if t.lower() == name.lower(): return t
        if t.lower().startswith(name.lower()) or name.lower() in t.lower():
            if len(t) > len(best): best = t
    return dedup_name(best or name)


def _paste(text):
    subprocess.run(["bash", "-c", f"printf '%s' {shlex.quote(text)} | xclip -selection clipboard"],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.25)
    subprocess.run(["xdotool", "key", "ctrl+v"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.3)


def search_contact(name):
    """通讯录顶部搜索框找人：搜索结果是精确文本，不受假名 OCR 影响。"""
    w = _AWX["obj"]
    if w is None or not G: return False
    shot(); items = ocr_items()
    box = [i for i in items if "搜索" in i["t"]]
    if not box:
        print("  [备注] 找不到搜索框"); return False
    click(box[0]["cx"], box[0]["cy"]); time.sleep(1.0)
    _paste(name[:8]); time.sleep(1.8)
    hit = None
    try:
        for it in w.search_items():
            if same_sess(it["name"], name):
                hit = it; break
    except Exception as e:
        print("  [备注] 搜索解析失败", type(e).__name__)
    if hit:
        bx, by, bw, bh = hit["box"]
        click(bx + bw / 2, by + bh / 2); time.sleep(1.8)
        print("  [备注] 搜索命中:", hit["name"])
        return True
    # 没命中就把搜索框清空，别把界面留在筛选状态
    subprocess.run(["xdotool", "key", "ctrl+a"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.15)
    subprocess.run(["xdotool", "key", "BackSpace"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.4)
    print("  [备注] 搜索没命中:", name)
    return False


def open_contact(name):
    """通讯录 → 找到并点开某人资料页。"""
    if not grab() or not G: return False
    click(G.x + 0.032 * G.w, G.y + 0.25 * G.h); time.sleep(2.0)
    subprocess.run(["xdotool", "mousemove", str(int(G.x + 0.10 * G.w)), str(int(G.y + 0.32 * G.h))],
                   check=False, stdout=DEVNULL, stderr=DEVNULL)
    for _ in range(8):
        subprocess.run(["xdotool", "click", "4"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        time.sleep(0.2)
    time.sleep(1.2)
    # 先用无障碍树：通讯录项的 name 是精确文本，不会被 OCR 把假名认错。
    # 列表只暴露可见项，所以要边滚边找。
    w = _AWX["obj"]
    if w is not None:
        try:
            for c in w.contacts():
                if same_sess(c["name"], name):
                    bx, by, bw, bh = c["box"]
                    click(bx + bw / 2, by + bh / 2); time.sleep(1.8)
                    print("  [备注] 无障碍树命中:", c["name"])
                    return True
        except Exception as e:
            print("  [备注] atspi 通讯录失败", type(e).__name__)
    shot(); items = ocr_items()
    def _row_ok(t):
        t = (t or "").strip()
        if not t or "新的朋友" in t or t.startswith("联系人"): return False
        if same_sess(t, name): return True
        a, b = set(t), set(name)
        return len(a & b) >= 2 and abs(len(t) - len(name)) <= 2
    rows = [i for i in items if i["cx"] < G.list_xmax and _row_ok(i["t"])]
    if not rows:
        print("  [备注] 通讯录列表里没有，改用搜索")
        if search_contact(name):
            print("  [备注] 搜索打开的是会话窗，不一定能改备注")
            return True
        print("  [备注] 搜索也没有", name); return False
    click(rows[0]["cx"], rows[0]["cy"]); time.sleep(1.8)
    return True


def get_remark(name=""):
    """读资料页里「备注」那一行的当前值。"""
    shot(); items = ocr_items()
    lab = [i for i in items if i["t"].strip() == "备注"]
    if not lab: return None
    y = lab[0]["cy"]
    vals = [i for i in items if i["cx"] > lab[0]["cx"] + 15 and abs(i["cy"] - y) < 14]
    if not vals: return ""
    return vals[0]["t"].strip()


def set_remark(name, new=None, dry=False):
    """把某人的微信备注改成 new（默认是去掉重复的名字）。改完回聊天列表。"""
    if not grab() or not G: return False
    if not open_contact(name): return False
    cur = get_remark()
    want = (new or dedup_name(name)).strip()
    print("  [备注] %s 当前=%r 目标=%r" % (name, cur, want))
    if cur is None:
        print("  [备注] 没找到解释备注那一行，放弃"); return False
    if cur == want:
        print("  [备注] 已经正确，不改"); return True
    if dry: return True
    items = ocr_items()
    lab = [i for i in items if i["t"].strip() == "备注"]
    y = lab[0]["cy"]
    vals = [i for i in items if i["cx"] > lab[0]["cx"] + 15 and abs(i["cy"] - y) < 14]
    if not vals:
        print("  [备注] 点不到值"); return False
    click(vals[0]["cx"], vals[0]["cy"]); time.sleep(1.0)
    subprocess.run(["xdotool", "key", "ctrl+a"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.15)
    subprocess.run(["xdotool", "key", "BackSpace"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(0.2)
    _paste(want)
    subprocess.run(["xdotool", "key", "Return"], check=False, stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1.5)
    got = get_remark()
    click(G.x + 0.032 * G.w, G.y + 0.18 * G.h)      # 回到会话页，别把界面留在资料页
    time.sleep(1.2)
    print("  [备注] 改完读到=%r %s" % (got, "OK" if got == want else "未生效"))
    return got == want


def remark_fix(dry=False):
    """扫一遍联系人，把被写成「名字+名字」的备注纠正回去。"""
    fixed = 0
    for nm in list(contacts().keys()):
        if not grab() or not G: break
        if not open_contact(nm): continue
        cur = get_remark()
        if not cur:
            print("  [备注] %s 无备注，跳过" % nm); continue
        want = dedup_name(cur)
        if want == cur:
            print("  [备注] %s = %r 正常" % (nm, cur)); continue
        print("  [备注] %s 需要纠正: %r -> %r" % (nm, cur, want))
        if dry: continue
        set_remark(nm, want); fixed += 1
    click(G.x + 0.032 * G.w, G.y + 0.18 * G.h)
    print("  [备注] 收工，纠正 %d 个" % fixed)
    return fixed


def greet_new_friend(name, dry=False):
    """新好友：先加进名单（不然她不理人家），再从通讯录点进去发一句问来意。"""
    if not name: return False
    raw = name
    name = full_sess_name(name)
    if name != raw: print("  [好友] 名字纠正:", raw, "->", name)
    cs = contacts()
    if name not in cs:
        cs[name] = {"name": name, "role": "other", "weight": 3, "note": "",
                    "aliases": [raw] if raw != name else []}
        json.dump(cs, open(CONTACTS_FILE, "w"), ensure_ascii=False)
        print("  [好友] 已加入联系人:", name)
    ok = False
    for _ in range(3):
        grab()
        # 先从聊天列表找（已经聊过的）
        cands = [i for i in ocr_items() if i["cx"] < G.list_xmax and same(i["t"], name)]
        if cands:
            click(G.list_click_x, cands[0]["cy"]); time.sleep(1.8)
            grab()
            if same(current_session(ocr_items()), name):
                ok = True; break
        # 聊天列表里没有 → 去通讯录找
        click(G.x + 0.032 * G.w, G.y + 0.25 * G.h); time.sleep(1.2)
        shot(); items = ocr_items()
        cc = [i for i in items if i["cx"] < 500 and same(i["t"], name)]
        if not cc:
            subprocess.run(["xdotool", "mousemove", str(int(G.x + 0.3 * G.w)), str(int(G.y + 0.6 * G.h))],
                           check=False, stdout=DEVNULL, stderr=DEVNULL)
            for _ in range(6):
                subprocess.run(["xdotool", "click", "5"], check=False, stdout=DEVNULL, stderr=DEVNULL)
                time.sleep(0.2)
            time.sleep(0.8); shot(); items = ocr_items()
            cc = [i for i in items if i["cx"] < 500 and same(i["t"], name)]
        if cc:
            click(cc[0]["cx"], cc[0]["cy"]); time.sleep(1.5); shot()
            msg_btn = [i for i in ocr_items() if i["t"].strip() == "发消息"]
            if msg_btn:
                click(msg_btn[0]["cx"], msg_btn[0]["cy"]); time.sleep(1.8)
                grab()
                if same(current_session(ocr_items()), name):
                    ok = True; break
        time.sleep(1.5)
    if not ok:
        print("  [好友] 没找到/没进去会话:", name); return False
    if dry:
        print("  [好友] dry-run：会话已就位，未发送"); return True
    parts = opener_parts(0)
    if not parts: print("  [好友] 没配置 wechat_opener，先不主动开口"); return True
    for i, t in enumerate(parts):
        send(t, list(G.input_xy))
        if i < len(parts) - 1: time.sleep(random.uniform(1.0, 2.0))
    print("  [好友] 已问来意:", " / ".join(parts))
    return True


LOG_FILE = ROOT + "/bot_log.md"


def chat_log(name, peer_text, thought, reply):
    """每轮回话的想法与发出去的话，单独归档一份。"""
    try:
        new = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            if new:
                f.write("# 对话日志\n")
            f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')} · {name}\n\n")
            f.write(f"**对方**：{(peer_text or '').strip()}\n\n")
            f.write(f"**心想**：{(thought or '').strip()}\n\n")
            f.write(f"**回复**：{(reply or '').strip()}\n")
    except Exception as e:
        print("  [日志] 写入失败:", type(e).__name__, str(e)[:60])


# ---- AT-SPI 影子读取（只读对照，不参与决策）----
_AWX = {"obj": None, "tried": False}


def atspi_init():
    if _AWX["tried"]:
        return _AWX["obj"]
    _AWX["tried"] = True
    try:
        import wxatspi
        w = wxatspi.Wx()
        if w.app is None:
            print("[atspi] 没找到微信无障碍树")
            return None
        w.warm()
        _AWX["obj"] = w
        print("[atspi] 就绪", w.rect())
    except Exception as e:
        print("[atspi] 初始化失败", type(e).__name__, str(e)[:80])
    return _AWX["obj"]


SYS_SKIP = ("撤回了一条消息", "以下为新消息", "你已添加了", "现在可以开始聊天",
            "对方正在输入", "以上是打招呼的内容", "开启了朋友验证",
            "邀请你加入了群聊", "你已退出该群聊")


def content_box(gray, mbox):
    """气泡内容的外接框 [x1,x2,y1,y2]；无墨迹返回 None。"""
    if gray is None:
        return None
    x, y, w, h = mbox
    x0, x2 = x + 10, x + w - 10
    y0, y2 = y + 4, y + h - 4
    if x2 - x0 < 20 or y2 - y0 < 8:
        return None
    roi = gray[y0:y2, x0:x2]
    vals, cnts = np.unique(roi, return_counts=True)
    bg = int(vals[np.argmax(cnts)])
    mask = np.abs(roi.astype(np.int16) - bg) > 12
    cols = np.where(mask.sum(axis=0) > 1)[0]
    rows = np.where(mask.sum(axis=1) > 1)[0]
    if len(cols) == 0 or len(rows) == 0:
        return None
    return [x0 + int(cols[0]), x0 + int(cols[-1]), y0 + int(rows[0]), y0 + int(rows[-1])]


def _map_person(who, pool):
    """OCR 会把名字读错几个字，模糊映射回通讯录/会话里的真名。"""
    who = (who or "").strip()
    if not who or who in pool:
        return who
    best, score = who, 0.0
    for n in pool:
        r = difflib.SequenceMatcher(None, who, n).ratio()
        if r > score:
            best, score = n, r
    return best if score >= 0.6 else who


def group_trigger(msgs):
    """群里只在被点名时才回：@ 或直呼配置里的名字；名字为空则关闭。"""
    nm = (CFG.get("name") or "").strip()
    if not nm: return False
    for m in msgs[-6:]:
        if m.get("sender") != "peer":
            continue
        body = (m.get("text") or "").split("：", 1)[-1].strip()
        if nm in body or ("@" + nm[-1:]) in body:
            return True
    return False


def atspi_read(items=None, ocr_msgs=None):
    """用无障碍树解出消息列表；任一环节不确定就返回 None，让调用方回退 OCR。"""
    w = _AWX["obj"]
    if w is None:
        return None
    try:
        am = w.messages()
        if not am:
            return None
        img = cv2.imread(SHOT)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img is not None else None
        names = set(contacts()) | {"我", "你"}
        top = 0
        pool = []
        try:
            top = (w.list_box() or [0, 0, 0, 0])[1]
            pool = [s["name"] for s in w.sessions()] + list(contacts().keys())
        except Exception:
            pool = list(contacts().keys())
        out = []
        for m in am:
            t = (m["text"] or "").strip()
            if not t or TIME_RE.match(t):
                continue
            if any(k in t for k in SYS_SKIP):
                continue
            # 左右归属优先用 OCR 的结果（几何准），文本仍用 atspi 的精确值
            side = None
            if ocr_msgs:
                best, bs = None, 0.0
                for o in ocr_msgs:
                    sc = _cover(norm(t), norm(o.get("text") or ""))
                    if sc > bs: bs, best = sc, o
                if best is not None and bs >= 0.7:
                    side = best.get("sender")
            if side is None and ocr_msgs:
                # 文本对不上（比如贴纸读成「动画表情」）：取纵向最近的那条 OCR 消息的归属
                y0 = m["box"][1] + m["box"][3] / 2
                near = min(ocr_msgs, key=lambda o: abs((o.get("y") or 0) - y0))
                if abs((near.get("y") or 0) - y0) < 40:
                    side = near.get("sender")
            if side is None:
                bb = content_box(gray, m["box"])
                side = ("peer" if bb[0] < G.split_x else "me") if bb else None
            if side is None:
                print("  [atspi] 方位不确定，回退 OCR", repr(t[:16]))
                return None
            if m.get("kind") in ("sticker", "image") and _recent_self_media():
                side = "me"      # 自己刚发的表情/图片，读回时别认成对方的
            if t in ("图片", "[图片]"):
                t = "[图片]"
            elif t in ("动画表情", "表情", "[动画表情]", "[表情]"):
                t = "[表情]"
            else:
                mref = re.match(r"^([^\s：:]{1,8})[：:]", t)
                if mref and mref.group(1) in names:
                    t = "[引用] " + t
            if items and m["box"][3] >= 66:
                # 群聊：昵称不在无障碍树里，用本轮 OCR 结果按 y 挂上去
                x, y, ww, h = m["box"]
                cands = [i for i in items if y + 15 <= i["cy"] <= y + 50
                         and x + 30 < i["cx"] < x + 320 and i["cy"] >= top + 8]
                if cands:
                    who = min(cands, key=lambda i: abs(i["cy"] - (y + 34)))["t"].strip()
                    if 1 <= len(who) <= 12:
                        t = "%s：%s" % (_map_person(who, pool), t)
            out.append({"sender": side, "text": t,
                        "x1": bb[0], "x2": bb[1], "y1": bb[2], "y2": bb[3],
                        "y": (bb[2] + bb[3]) / 2})
        if not out:
            return None
        return out
    except Exception as e:
        print("[atspi] 解析失败", type(e).__name__, str(e)[:60])
        return None


def _rows_overlap(older, newer):
    """把两次滚动读到的消息按重叠部分拼起来（older 在前）。"""
    for k in range(min(len(older), len(newer)), 0, -1):
        if [m["text"] for m in older[-k:]] == [m["text"] for m in newer[:k]]:
            return older + newer[k:]
    return older + newer


def expand_group(pages=1):
    """被点名时向上翻一屏，把上面的对话也读进来；读完滚回最新。失败返回 None。"""
    w = _AWX["obj"]
    if w is None:
        return None
    r = w.rect()
    if not r:
        return None
    base = atspi_read(ocr_items())
    if not base:
        return None
    cx, cy = r[0] + r[2] // 2, r[1] + int(r[3] * 0.5)
    subprocess.run(["xdotool", "mousemove", str(cx), str(cy)], check=False, stdout=DEVNULL, stderr=DEVNULL)
    out = list(base)
    for _ in range(pages):
        for _ in range(4):
            subprocess.run(["xdotool", "click", "4"], check=False, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(0.15)
        time.sleep(0.5)
        shot()
        older = atspi_read(ocr_items())
        if not older:
            break
        out = _rows_overlap(older, out)
        if len(out) >= 24:
            break
    for _ in range(pages * 4):
        subprocess.run(["xdotool", "click", "5"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        time.sleep(0.1)
    time.sleep(0.5)
    print("[群] 补上下文：%d 条" % len(out[-24:]))
    return out[-24:]


SHADOW_FILE = ROOT + "/atspi_shadow.jsonl"


def _shadow_rotate():
    try:
        if os.path.getsize(SHADOW_FILE) > 2 * 1024 * 1024:
            os.replace(SHADOW_FILE, SHADOW_FILE + ".1")
    except Exception:
        pass


def atspi_shadow(msgs, name=""):
    w = _AWX["obj"]
    if w is None or not msgs:
        return
    try:
        t = time.time()
        am = w.messages()
        sess = w.sessions()
        img = cv2.imread(SHOT)
        got = [(norm(m.get("text", "")), m.get("sender")) for m in msgs]
        used, hit, side_ok, diff = set(), 0, 0, []
        items, unmatched_a = [], []
        for m in am:
            key = norm(m["text"])
            sd = w.side(img, m["box"]) if img is not None else None
            items.append({"t": m["text"][:120], "len": len(m["text"]), "side": sd,
                          "kind": m["kind"], "h": m["box"][3],
                          "tail": m["text"][-1:] in ("…", ".")})
            ok = False
            for j, (g, s) in enumerate(got):
                if j in used or not key or g != key:
                    continue
                used.add(j)
                ok = True
                hit += 1
                if sd:
                    if sd == s:
                        side_ok += 1
                    else:
                        diff.append("%s:%s/%s" % (m["text"][:12], sd, s))
                break
            if not ok:
                unmatched_a.append(m["text"][:40] or "<empty>")
        unmatched_o = [got[j][0][:40] or "<empty>" for j in range(len(got)) if j not in used]
        sel = next((s for s in sess if s["selected"]), None)
        rec = {"t": time.strftime("%m-%d %H:%M:%S"), "target": name,
               "sess": sel["name"] if sel else None,
               "sess_all": [s["name"] for s in sess],
               "n": [len(am), len(got)], "hit": hit, "side_ok": side_ok,
               "ms": round((time.time() - t) * 1000), "items": items,
               "unmatched_atspi": unmatched_a, "unmatched_ocr": unmatched_o,
               "diff": diff[:5]}
        _shadow_rotate()
        with open(SHADOW_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("[atspi] %d行/%d条 对上%d 方位%d %.0fms %s" % (
            len(am), len(got), hit, side_ok, (time.time() - t) * 1000, " ".join(diff[:3])))
    except Exception as e:
        print("[atspi] 对照失败", type(e).__name__, str(e)[:60])


def handle(name, st, last_hash, dot=False):
    t0 = time.time()
    if not grab():
        print("[skip] no window"); return last_hash, True
    h = frame_hash()
    if h == last_hash:
        return last_hash, True
    items = ocr_items()
    danger = danger_on_screen(items)
    if danger:
        if any(("退出登录后" in d or "退出登录？" in d or "退出登录?" in d) for d in danger):
            print("  [guard] 退出登录确认框，点取消")
            if not dismiss_logout():
                print("  [guard] 取消没关掉，跳过本轮")
        else:
            print("  [guard] 屏幕上有危险弹窗，Esc 后跳过本轮")
            subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        return last_hash, False
    sess = atspi_current() or current_session(items)
    if not same_sess(sess, name):
        cands = [i for i in items if i["cx"] < G.list_xmax and same(i["t"], name)]
        if cands:
            t = cands[0]
            click(G.list_click_x, t["cy"])
            time.sleep(1.2)
            print(f"[{name}] switch from {sess!r}")
        else:
            print(f"[{name}] front={sess!r}, not in list")
        return h, True
    ocr_msgs = parse(items)
    msgs = atspi_read(items, ocr_msgs=ocr_msgs) or ocr_msgs
    _src = "atspi" if msgs is not ocr_msgs else "ocr"
    if _src == "atspi":
        print("[atspi] 树解析 %d 条（替代 OCR 文本）" % len(msgs))
    atspi_shadow(ocr_msgs, name)
    if contacts().get(name, {}).get("group"):
        remember_group(msgs)
    if contacts().get(name, {}).get("group"):
        try:
            group_remember(msgs, name)
        except Exception as e:
            print("[群记] 失败", type(e).__name__, str(e)[:50])
    _is_group = bool(contacts().get(name, {}).get("group"))
    if _is_group and not group_trigger(msgs):
        print(f"[{name}] 群里没点名，跳过本轮")
        return last_hash, True
    if _is_group:
        try:
            msgs = expand_group(1) or msgs
        except Exception as e:
            print("[群] 扩上下文失败", type(e).__name__, str(e)[:40])
    if msgs and msgs[-1]["sender"] == "peer" and msgs[-1]["text"][:4] in ("[图片]", "[表情]"):
        try:
            learn_sticker(name, msgs[-6:])
        except Exception as e:
            print("  [收藏] 出错", type(e).__name__, str(e)[:40])
    t1 = time.time()
    need_vlm = not msgs
    if need_vlm:
        try:
            d = vlm_look()
            vis = [{"sender": m["sender"], "text": m["text"]} for m in (d.get("messages") or [])]
            ib = d.get("input_box") or list(G.input_xy)
            src = "vlm"
        except Exception as e:
            print("[vlm err]", str(e)[:80]); return last_hash, False
    else:
        vis = msgs[-(16 if _is_group else 8):]   # 保留坐标，后面放大重读要用
        ib = list(G.input_xy); src = _src
    print(f"[{name}] {src} {t1 - t0:.1f}s n={len(vis)}")
    for m in vis[-4:]: print("    ", m["sender"], "|", m["text"][:36])
    hist = load_hist(name)
    human = human_typed(name, vis, [m.get("text", "") for m in hist])
    if human:
        note_style(name, human)
        print("  [风格] 学到人打的:", " / ".join(h[:12] for h in human[-3:]))
        st.setdefault(name, {})["manual_at"] = time.time()   # 人用这号亲手回的，别再替她追问
        save_state(st)
    merged = merge(hist, vis)
    if merged != hist: save_hist(name, merged)
    vis_start = max(0, len(merged) - len(vis)) if vis else len(merged)
    ctx = merged
    if vis and vis[-1]["sender"] == "peer":
        try:
            fused = fuse(vis)
        except Exception as e:
            # 融合是增强项，挂了也要能回，不能拖住整轮
            print("  [fuse skip]", type(e).__name__, str(e)[:60]); fused = vis
        if len(fused) != len(vis):
            print("  fused:", [(m["sender"], m["text"][:14]) for m in fused[-4:]])
        ctx = (merged[:-len(vis)] + fused) if len(merged) >= len(vis) else fused
        if ctx and ctx[-1]["sender"] == "peer" and not ctx[-1]["text"].startswith("["):
            try:
                fixed = verify_text(vis[-1])
            except Exception as e:
                print("  [zoom skip]", type(e).__name__, str(e)[:60]); fixed = ctx[-1]["text"]
            if fixed != ctx[-1]["text"]:
                ctx[-1] = {"sender": "peer", "text": fixed}
    else:
        extra = look_tail(name, st, vis, dot)
        if extra is False:
            print("  tail 失败，下轮重试"); return last_hash, False
        if extra: ctx = merged + [extra]
    # 按“这条对方消息回过没”判断，而不是只看最后一条是谁：
    # 对方连发两条时，我们的回复可能落在中间，最后一条就变成自己的
    idx = max((i for i, m in enumerate(ctx) if m.get("sender") == "peer"), default=-1)
    if idx < vis_start:
        print("  mine / 无新内容"); return h, False
    done = set(st.get(name, {}).get("handled") or [])
    if st.get(name, {}).get("last"): done.add(st[name]["last"])
    # 末尾那条可能只是「[图片]」这种占位文本，跟以前发过的图撞哈希；退回最后一条没回过的，
    # 否则一张图就能把前面真说的话一起吞掉
    idx = max((i for i, m in enumerate(ctx) if m.get("sender") == "peer"
               and hashlib.md5(m["text"].encode()).hexdigest()[:12] not in done), default=-1)
    if idx < vis_start:
        print("  dup"); return h, False
    last = ctx[idx]
    hh = hashlib.md5(last["text"].encode()).hexdigest()[:12]
    left = st.get(name, {}).get("cool", 0) - time.time()
    if left > 0:
        # 不能直接返回：画面哈希会被消费掉，同一条消息以后再也不会被读到
        print(f"  cool {left:.0f}s，等完再回")
        time.sleep(left + 0.5)
    LAST_NEW[0] = time.time()
    st.setdefault(name, {})["last_peer_at"] = time.time()
    print("  NEW:", last["text"][:40])
    before_inner = inner_count()
    loop = loop_guard(name, st, ctx)
    ans, thought = gen(name, ctx, loop)
    ans, relay_to, relay_text = split_relay(ans)
    print("  reply:", ans, ("| 转达->" + relay_to + ": " + relay_text) if relay_to else "")
    recent_me = [m.get("text", "").strip() for m in ctx[-6:] if m.get("sender") == "me"]
    if ans.strip() in recent_me:
        print("  skip: duplicated my recent message")
        inner_truncate(before_inner)
        _mark_handled(st, name, hh, ctx)
        return h, False
    sim = similar_to_recent(ans, recent_me)
    if sim >= 0.6:
        ok, why = review_reply(name, ctx, ans)
        if not ok:
            print(f"  [review] 相似度 {sim:.2f}，审核不通过（{why}）：这句不发，标记已处理不再重试")
            inner_truncate(before_inner)
            _mark_handled(st, name, hh, ctx)
            return h, False
        print(f"  [review] 相似度 {sim:.2f}，审核通过（{why}）")
    if SEND:
        parts = send_multi(ans, ib); print("  sent", len(parts), "part(s)")
        chat_log(name, last.get("text", ""), thought, ans)
        note_sent(name, parts)
        s = st.setdefault(name, {})
        s["cool"] = time.time() + 20
        s["sent_at"] = time.time()
        print("  verify:", "ok" if sent_ok(parts[-1]) else "not found in chat")
        emo = pick_sticker_by_model(ctx, ans)
        if emo: send_sticker_by_emotion(emo)
        if contacts().get(name, {}).get("role") == "owner" and re.search(r"(同意|通过).{0,4}(好友|验证|申请)", last.get("text", "")):
            accept_requests()
        if relay_to and relay_text and contacts().get(name, {}).get("role") == "owner":
            send_to_contact(relay_to, relay_text)
        hs = list(s.get("handled") or [])
        for m in ctx:
            if m.get("sender") != "peer": continue
            x = hashlib.md5(m["text"].encode()).hexdigest()[:12]
            if x not in hs: hs.append(x)
        s["handled"] = hs[-40:]
        s["last"] = hh
        save_state(st)
    else:
        print("  [dry] 未发送，不写去重状态")
    return h, False


def selfcheck():
    ok = fail = 0

    def chk(label, cond, detail=""):
        nonlocal ok, fail
        if cond: ok += 1; print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
        else: fail += 1; print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))
        return cond

    print("== 1. 依赖与配置 ==")
    chk("DISPLAY", bool(os.environ.get("DISPLAY")), os.environ.get("DISPLAY", ""))
    for b in ("ffmpeg", "xdotool", "xclip"):
        chk(b, shutil.which(b) is not None, shutil.which(b) or "not found")
    keys = ("base_url", "model", "api_key", "system_prompt")
    chk("config 字段", all(CFG.get(k) for k in keys), "缺: " + ", ".join(k for k in keys if not CFG.get(k)))
    chk("owner_prompt/other_prompt", bool(CFG.get("owner_prompt") or CFG.get("other_prompt")))
    print(f"  model={CFG.get('model')}  api_key={'已配置' if CFG.get('api_key') else '缺失'}")

    print("== 2. 窗口与截图 ==")
    t = time.time(); ok_grab = grab(); shot_ms = (time.time() - t) * 1000
    chk("截屏+窗口定位", ok_grab, f"{shot_ms:.0f}ms")
    if not ok_grab:
        print("\n== 结果: FAIL =="); return 1
    chk("窗口面积", G.w > 700 and G.h > 500, f"{G.w}x{G.h} @ {G.x},{G.y}")
    ids = subprocess.run(["xdotool", "search", "--name", "^wechat$"],
                         capture_output=True, text=True).stdout.split()
    chk("wechat 窗口", len(ids) > 0, ",".join(ids) or "未找到")

    print("== 3. OCR ==")
    t = time.time(); items = ocr_items(); ocr_ms = (time.time() - t) * 1000
    chk("OCR 出字", len(items) >= 5, f"{len(items)} 条, {ocr_ms:.0f}ms")

    print("== 4. 会话与消息 ==")
    sess = current_session(items)
    chk("识别当前会话", bool(sess), sess or "空")
    msgs = parse(items)
    # 可见区可能只到表情和自己的回复（表情无 OCR 文字），1 条也算正常
    chk("解析消息", len(msgs) >= 1, f"{len(msgs)} 条")
    for m in msgs[-4:]:
        print(f"    {m['sender']:4s} | {m['text'][:40]}")
    chk("左右判断", all(m["sender"] in ("peer", "me") for m in msgs))
    if msgs:
        pw = [m for m in msgs if m["sender"] == "me"]
        chk("自己的消息在右侧", all(m["x1"] >= G.split_x for m in pw), f"{len(pw)} 条")

    print("== 5. 未读红点 ==")
    dots = red_dots()
    print("    dots:", dots)
    names = [name_at(items, y + h / 2) for (x, y, w, h) in dots]
    print("    对应会话:", names)
    # 当前可能本来就没未读，用合成角标验证检测器本身
    probe = cv2.imread(SHOT)
    if probe is not None:
        px, py = int(G.list_click_x + 0.02 * G.w), int(G.y + 0.20 * G.h)
        cv2.circle(probe, (px, py), 7, (81, 81, 250), -1)
        cv2.imwrite("/tmp/dot_test.png", probe)
        hit = [d for d in red_dots("/tmp/dot_test.png")
               if abs(d[0] + d[2] / 2 - px) < 5 and abs(d[1] + d[3] / 2 - py) < 5]
        chk("红点检测器（合成角标）", bool(hit), f"{len(hit)} 命中")

    print("== 6. 数据文件 ==")
    cs = contacts()
    chk("contacts.json", bool(cs), " / ".join(cs.keys()))
    chk("history 目录", os.path.isdir(HIST_DIR), f"{len(os.listdir(HIST_DIR))} 个")
    chk("memory 目录", os.path.isdir(MEM_DIR), f"{len(os.listdir(MEM_DIR))} 个")
    for n in cs:
        h = load_hist(n)
        print(f"    {n}: 历史 {len(h)} 条 / 记忆 {len(mem_load(n))} 条, 最后 {h[-1]['text'][:20] if h else '无'}")
    chk("记忆可读", all(isinstance(mem_load(n), list) for n in cs), f"{len(cs)} 人")
    chk("长期记忆有内容", any(mem_load(n) for n in cs), f"{sum(len(mem_load(n)) for n in cs)} 条")
    chk("state.json", os.path.exists(STATE_FILE))
    try:
        me = os.getpid()
        others = 0
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == me: continue
            try:
                cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
            except Exception:
                continue
            if "wxbot3.py" in cmd and "python" in cmd and "--selfcheck" not in cmd:
                others += 1
        chk("无多余实例", others <= 1, f"{others} 个实例（常驻 1 个为正常）")
    except Exception as e:
        print("    进程检查跳过:", type(e).__name__)

    print("== 7. 模型接口 ==")
    try:
        t = time.time()
        ping = api({"model": CFG["model"], "messages": [{"role": "user", "content": "只回复：OK"}],
                    "temperature": 0, "max_tokens": 64}, timeout=60, think=False).strip()
        chk("chat/completions", bool(ping), f"{ping[:20]!r} {(time.time() - t):.1f}s")
    except Exception as e:
        chk("chat/completions", False, f"{type(e).__name__}: {str(e)[:100]}")

    print("== 8. 回复生成（不发送）==")
    try:
        t = time.time()
        h = load_hist(sess) if sess in cs else []
        ans, _th = gen(sess if sess in cs else list(cs)[0], h)
        chk("gen()", bool(ans), f"{time.time() - t:.1f}s")
        print("    示例:", ans[:60])
    except Exception as e:
        chk("gen()", False, f"{type(e).__name__}: {str(e)[:100]}")

    print("== 9. 视觉兜底（表情/图片）==")
    try:
        t = time.time()
        d = vlm_tail()
        ok_tail = isinstance(d, dict) and d.get("last_sender") in ("peer", "me") and bool(d.get("text"))
        chk("vlm_tail()", ok_tail,
            f"{d.get('last_sender')}/{d.get('kind')} {str(d.get('text'))[:24]} {(time.time() - t):.1f}s")
    except Exception as e:
        chk("vlm_tail()", False, f"{type(e).__name__}: {str(e)[:80]}")

    print("== 10. 单条精读（气泡放大重读）==")
    if msgs:
        m0 = msgs[-1]
        z = verify_text(m0)
        chk("放大重读", bool(z), "不变" if norm(z) == norm(m0["text"]) else "有纠正")
        if CLIP:
            t = exact_text(m0)
            chk("剪贴板复制(--clip)", bool(t), (t or "未取到")[:30])
    else:
        print("    SKIP 画面里没有消息")
    chk("无危险弹窗", not danger_on_screen(items), ",".join(danger_on_screen(items)[:2]))
    chk("精读容错（无坐标）", verify_text({"sender": "peer", "text": "测试"}) == "测试")

    print("== 11. 视觉结构化融合 ==")
    try:
        t = time.time()
        vm = vlm_read()
        chk("vlm_read()", len(vm) >= 1, f"{len(vm)} 条 {(time.time() - t):.1f}s")
        fused = fuse(msgs)
        print("    融合后:", [(x["sender"], x["text"][:14]) for x in fused[-5:]])
        chk("fuse()", len(fused) >= len(msgs), f"OCR {len(msgs)} 条 → 融合 {len(fused)} 条")
    except Exception as e:
        chk("vlm_read()", False, f"{type(e).__name__}: {str(e)[:80]}")

    print("== 12. 收藏表情包 ==")
    try:
        tiles = fav_tiles_live()
        subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
        chk("读取收藏表情", len(tiles) > 0, f"{len(tiles)} 个格子 {tiles[:3]}")
        if tiles:
            items = ensure_catalog(tiles)
            chk("表情语义目录", any(i.get("emotion") for i in items), str(items[0])[:70] if items else "空")
    except Exception as e:
        chk("读取收藏表情", False, f"{type(e).__name__}: {str(e)[:60]}")

    print("== 13. 长期记忆 ==")
    try:
        wxmem.ensure_repo()
        tn = "__memtest__"
        d = wxmem.person_dir(tn)
        if os.path.isdir(d): shutil.rmtree(d)
        a = wxmem.add(tn, "周末要去修电脑，顺便买猫粮")
        b = wxmem.add(tn, "周末要去修电脑，顺便买猫粮")
        wxmem.add(tn, "周末要去修电脑，顺便买猫粮和猫砂")
        vis = wxmem.visible(tn)
        chk("写入与去重", a is not None and b is None, f"存活 {len(vis)} 条")
        chk("新说法覆盖旧条目", len(vis) == 1 and "猫砂" in vis[0]["text"],
            vis[0]["text"][:24] if vis else "空")
        dg = wxmem.digest(tn, ["猫粮买了吗"])
        chk("按内容检索", "猫砂" in dg, dg.replace("\n", " ")[:40])
        chk("字节预算", len(wxmem.digest(tn, ["猫粮"], budget=60).encode()) <= 100)
        chk("git 自动提交", (not wxmem.git_available()) or os.path.isdir(os.path.join(wxmem.MEM_ROOT, ".git")),
            "git 未安装（跳过）" if not wxmem.git_available() else "仓库存在")
        shutil.rmtree(d)
        wxmem._sync_index()
    except Exception as e:
        chk("长期记忆", False, f"{type(e).__name__}: {str(e)[:60]}")

    print("== 14. 跨人联动 ==")
    if len(contacts()) < 2:
        print("    SKIP 需要至少两个联系人")
    else:
        try:
            who, other = list(contacts())[:2]
            chk("称呼别名", all(aliases(n) for n in contacts()), str(aliases(other)))
            msg = f"{other}昨天说他要去外地"
            chk("提到别人能认出来", other in mentioned([msg], who), str(mentioned([msg], who)))
            blk = cross_brief(who, [{"sender": "peer", "text": msg}])
            chk("联动块有内容", bool(blk) and other in blk, blk.replace("\n", " ")[:50])
            ms = _msgs_for(who, [{"sender": "peer", "text": msg}])
            chk("进了生成上下文", any("刚才提到了" in m.get("content", "") for m in ms))
            chk("没提人就不注入", not cross_brief(who, [{"sender": "peer", "text": "今天天真热"}]))
        except Exception as e:
            chk("跨人联动", False, f"{type(e).__name__}: {str(e)[:60]}")

    print("== 15. 朋友圈入口 ==")
    if not G:
        print("    SKIP 没有窗口")
    else:
        try:
            img = cv2.imread(SHOT)
            if img is not None:
                probe = img.copy(); px, py = int(G.x + 0.035 * G.w), int(G.y + 0.396 * G.h)
                cv2.circle(probe, (px, py), 8, (40, 40, 240), -1); cv2.imwrite("/tmp/badge_test.png", probe)
                chk("朋友圈红点（合成）", moments_badge("/tmp/badge_test.png"))
            if not moments_badge():
                chk("无红点时不打开朋友圈", moments_notice() == [])
            else:
                print("    当前朋友圈有红点，跳过无红点检查")
        except Exception as e:
            chk("朋友圈入口", False, f"{type(e).__name__}: {str(e)[:50]}")

    print(f"\n== 结果: {ok} 通过 / {fail} 失败 ==")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    if SELFCHECK:
        sys.exit(selfcheck())
    if "--moments-reply" in sys.argv:
        print("红点:", moments_badge())
        for it in moment_reply_scan():
            print(" ", it)
        sys.exit(0)
    if "--moments" in sys.argv:
        got = moments_scan(rounds=3)
        for g in got:
            print(f"  {g['author'] or '?'} | {g['text'][:50]} | {'→ ' + g['who'] if g['who'] else '（不认识，未记）'}")
        sys.exit(0)
    if "--mem-extract" in sys.argv:
        i = sys.argv.index("--mem-extract")
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
            names = [sys.argv[i + 1]]
        else:
            names = list(contacts())
        for nm in names:
            got = mem_extract(nm)
            print(f"{nm}: 新增 {len(got)} 条")
        sys.exit(0)
    if "--remark" in sys.argv:
        i = sys.argv.index("--remark")
        nm = sys.argv[i + 1]
        want = sys.argv[i + 2] if len(sys.argv) > i + 2 and not sys.argv[i + 2].startswith("-") else None
        ok = set_remark(nm, want, dry=("--dry" in sys.argv))
        sys.exit(0 if ok else 1)
    if "--remark-fix" in sys.argv:
        remark_fix(dry=("--dry" in sys.argv))
        sys.exit(0)
    if "--mem-add" in sys.argv:
        i = sys.argv.index("--mem-add")
        nm, body = sys.argv[i + 1], " ".join(sys.argv[i + 2:])
        e = mem_add(nm, body, title="手记")
        print("已记住" if e else "重复或太短，没记")
        sys.exit(0)
    if "--mem-relink" in sys.argv:
        i = sys.argv.index("--mem-relink")
        nm = sys.argv[i + 1]
        es = wxmem.entries(nm)
        got = 0
        for e in es:
            got += mem_link(nm, e["text"])
        print(f"{nm}: 补了 {got} 条语义连线")
        sys.exit(0)
    if "--mem-graph" in sys.argv:
        i = sys.argv.index("--mem-graph")
        nm = sys.argv[i + 1]
        print(wxmem.chain(nm))
        out = wxmem.svg(nm, os.path.join(ROOT, "graphs", nm + ".svg"))
        print("图:", out or "(没有记忆，没法画)")
        sys.exit(0)
    if "--mem-rebuild" in sys.argv:
        i = sys.argv.index("--mem-rebuild")
        nm = sys.argv[i + 1]
        print(f"重建 {nm} 的链：{wxmem.rebuild(nm)} 条边")
        sys.exit(0)
    if "--mem" in sys.argv:
        i = sys.argv.index("--mem")
        nm = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        if not nm:
            print("用法: --mem 名字 | --mem-del 名字 序号 | --mem-extract 名字")
            sys.exit(2)
        es = wxmem.entries(nm)
        vis = wxmem.visible(nm)
        print(f"{nm}: 共 {len(es)} 条（有效 {len(vis)}）")
        for i2, e in enumerate(es, 1):
            flag = "" if e in vis else "  [已被更新说法覆盖]"
            print(f"  {i2}. {e['title']} {e['text']}{flag}")
        sys.exit(0)
    if "--mem-del" in sys.argv:
        i = sys.argv.index("--mem-del")
        nm, idx = sys.argv[i + 1], int(sys.argv[i + 2])
        print("已删除" if wxmem.delete(nm, idx) else "没有这个序号")
        sys.exit(0)
    if "--mem-extract" in sys.argv:
        i = sys.argv.index("--mem-extract")
        nm = sys.argv[i + 1]
        got = mem_extract(nm)
        print(f"新增 {len(got)} 条")
        sys.exit(0)
    if "--ctx" in sys.argv:
        i = sys.argv.index("--ctx")
        nm = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") \
            else (list(contacts().keys()) or [""])[0]
        hist = load_hist(nm)
        ms = _msgs_for(nm, hist)
        total = sum(len(m["content"]) for m in ms)
        print(f"# {CFG.get('name') or '人格'}的上下文 · {nm} · {time.strftime('%Y-%m-%d %H:%M')}")
        print(f"消息 {len(ms)} 条，共 {total} 字符，约 {total / 1.6:.0f} tokens（粗估）")
        for k, m in enumerate(ms, 1):
            c = m["content"]
            print(f"\n## [{k}] {m['role']} · {len(c)} 字\n")
            print(c)
        sys.exit(0)
    if "--usage" in sys.argv:
        try: cur = json.load(open(USAGE_FILE))
        except Exception: cur = {}
        for day in sorted(cur):
            d = cur[day]
            print(f"{day}  调用 {d['calls']:4d} 次 | 输入 {d['prompt']:7d} | 输出 {d['completion']:6d} | 合计 {d['prompt']+d['completion']:7d} | 命中缓存 {d['cached']}")
        sys.exit(0)
    st = load_state(); targets = list(contacts().keys())
    mirror_memory(force=True)
    wxmem.ensure_repo()
    print("targets:", targets)
    last_hash = ""
    if LOOP and not load_catalog().get("items"):
        # 首次启动建一次收藏表情目录，之后只在数量变化时重建
        try:
            if grab():
                tiles = fav_tiles_live()
                subprocess.run(["xdotool", "key", "Escape"], check=False, stdout=DEVNULL, stderr=DEVNULL)
                if tiles: ensure_catalog(tiles)
        except Exception as e:
            print("[catalog init]", type(e).__name__, str(e)[:60])
    atspi_init()
    if LOOP:
        print("unread-driven loop", "send" if SEND else "dry")
        busy_until = 0.0
        while True:
            try:
                now = time.time()
                targets = list(contacts().keys())      # 每轮重读：刚通过的好友立刻能回
                mirror_memory()                        # 记忆改动 120 秒内补一次镜像
                if now < busy_until:
                    time.sleep(1); continue
                if not targets:
                    time.sleep(5); continue
                if now - LAST_FR[0] > 120 and friend_request_badge():
                    print("[好友] 侧栏有红点，去处理好友申请")
                    n = accept_requests()
                    LAST_FR[0] = time.time() + (600 if n == 0 else 0)   # 没申请就冷却 10 分钟，别来回跑
                    print("[好友] 本次通过", n, "个")
                    continue
                quiet = time.time() - (LAST_NEW[0] or BOT_START)
                if not grab():
                    print("[skip] no window"); time.sleep(3); continue
                items = ocr_items()
                danger = danger_on_screen(items)
                if danger:
                    print("[guard] 屏幕上有危险弹窗:", danger[:2])
                    if any(("退出登录后" in d or "退出登录？" in d or "退出登录?" in d) for d in danger):
                        if not dismiss_logout():
                            print("[guard] 取消没关掉，暂停本轮")
                    else:
                        subprocess.run(["xdotool", "key", "Escape"], check=False,
                                       stdout=DEVNULL, stderr=DEVNULL)
                    time.sleep(2); continue
                if not (atspi_current() or current_session(items)):
                    empty_rounds[0] += 1
                    if empty_rounds[0] >= 2:
                        print("[恢复] 聊天区是空的，打开一个会话")
                        if not open_session(targets[0] if targets else ""):
                            click(G.x + 0.032 * G.w, G.y + 0.18 * G.h)
                        empty_rounds[0] = 0
                        time.sleep(1.5)
                        continue
                else:
                    empty_rounds[0] = 0
                dots = red_dots()
                x, y, w, h = dots[0] if dots else (0, 0, 0, 0)
                nm = (atspi_name_at(y + h / 2) or name_at(items, y + h / 2)) if dots else None
                name = next((t for t in targets if nm and same_sess(nm, t)), None)
                if dots:
                    click(G.list_click_x, y + h / 2); time.sleep(1.4)
                    if not name:
                        grab(); items2 = ocr_items()
                        sess = atspi_current() or current_session(items2)
                        name = next((t for t in targets if same_sess(sess, t)), None)
                    if name:
                        print(f"[sched] unread -> {name}")
                        last_hash, _ = handle(name, st, last_hash, dot=True)
                        busy_until = time.time() + 5
                    else:
                        print("[sched] unread but name unknown")
                        time.sleep(2)
                else:
                    sess = atspi_current() or current_session(items)
                    name = next((t for t in targets if same_sess(sess, t)), None)
                    if name:
                        last_hash, _ = handle(name, st, last_hash)
                        busy_until = time.time() + 5
                    else:
                        if time.time() - LAST_MOMENT[0] > 1800 and random.random() < 0.5:
                            LAST_MOMENT[0] = time.time()
                            try:
                                moment_reply_scan()
                                moments_scan(rounds=2)
                            except Exception as e:
                                print("[moment err]", type(e).__name__, str(e)[:80])
                        time.sleep(5 if quiet < 300 else 15)   # 长时间没新消息就别每 5 秒空转 OCR
                proactive_tick(st, quiet)
            except Exception as e:
                print("[err]", type(e).__name__, str(e)[:160])
                time.sleep(2)
    else:
        for t in targets:
            last_hash, _ = handle(t, st, last_hash)
