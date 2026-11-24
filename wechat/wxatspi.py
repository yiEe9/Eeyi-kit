"""微信 Linux 版 AT-SPI 只读封装：窗口矩形、会话列表、消息（文本+方位）、输入框、状态标志。

不读数据库、不注入、不调用未授权接口，只遍历 Qt 暴露的无障碍树。
首次 warm() 会做一次全树解析（约 2~4 s），之后每轮只读缓存节点（约 30~60 ms）。
"""

import warnings

warnings.filterwarnings("ignore")

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

STICKER_NAMES = ("动画表情", "表情")
MAX_NODES = 4000


def _box(a):
    try:
        e = a.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
        return [int(e.x), int(e.y), int(e.width), int(e.height)]
    except Exception:
        return [0, 0, 0, 0]


def _showing(a):
    try:
        st = a.get_state_set()
        return st.contains(Atspi.StateType.SHOWING) and st.contains(Atspi.StateType.VISIBLE)
    except Exception:
        return False


def _text(a):
    try:
        return (a.get_name() or "").strip()
    except Exception:
        return ""


def _avatar_in(seg):
    """一段列区域里是否存在头像那种实心块（宽 26~50px、列覆盖率 >0.75）。"""
    try:
        if seg.size == 0 or seg.shape[1] < 20:
            return False
        col = seg.mean(axis=0)
        run = best = 0
        for v in col:
            if v >= 0.55:
                run += 1
                best = max(best, run)
            else:
                run = 0
        return 20 <= best <= 54
    except Exception:
        return False


class Wx:
    """绑定当前运行中的微信窗口。app 为 None 时调用方应回退 OCR。"""

    def __init__(self):
        self.app = None
        self._cache = {}
        self.find_app()

    # ---------- 定位 ----------

    def find_app(self):
        self.app = None
        self._cache = {}
        try:
            desk = Atspi.get_desktop(0)
            for i in range(desk.get_child_count()):
                a = desk.get_child_at_index(i)
                nm = _text(a)
                if "wechat" in nm.lower() or "微信" in nm:
                    self.app = a
                    return True
        except Exception:
            pass
        return False

    def _find(self, role, name):
        if self.app is None:
            return None
        stack, seen = [(self.app, 0)], 0
        while stack and seen < MAX_NODES:
            node, d = stack.pop()
            seen += 1
            if d > 24:
                continue
            try:
                if node.get_role_name() == role and _text(node) == name:
                    return node
                for i in range(node.get_child_count()):
                    stack.append((node.get_child_at_index(i), d + 1))
            except Exception:
                continue
        return None

    def _node(self, key, role, name):
        node = self._cache.get(key)
        if node is not None:
            try:
                node.get_child_count()
                return node
            except Exception:
                self._cache.pop(key, None)
        node = self._find(role, name)
        if node is not None:
            self._cache[key] = node
        return node

    def _frame_of(self, node):
        """从节点往上找主窗口 frame（跳过朋友圈/弹出窗口这类小 frame）。"""
        cur = node
        for _ in range(40):
            if cur is None:
                return None
            try:
                if cur.get_role_name() == "frame":
                    b = _box(cur)
                    return cur if b[2] > 600 and b[3] > 400 else None
                cur = cur.get_parent()
            except Exception:
                return None
        return None

    def warm(self):
        """单次遍历预解析常驻节点（消息/会话列表、输入框、锁屏/网络/导航），返回是否可用。"""
        if self.app is None:
            return False
        want = {("list", "消息"): "msgs", ("list", "会话"): "sess",
                ("label", "Linux 微信已被锁定"): "lock",
                ("label", "当前网络不可用"): "net",
                ("tool bar", "导航"): "nav"}
        named_roles = {"list", "label", "tool bar"}
        best_input, best_area, frame = None, 0, None
        stack, seen = [(self.app, 0)], 0
        while stack and seen < MAX_NODES:
            node, d = stack.pop()
            seen += 1
            if d > 24:
                continue
            try:
                role = node.get_role_name()
                if role == "frame" and frame is None:
                    frame = node
                elif role in named_roles:
                    key = want.get((role, _text(node)))
                    if key and key not in self._cache:
                        self._cache[key] = node
                elif role == "text" and node.get_state_set().contains(Atspi.StateType.EDITABLE):
                    b = _box(node)
                    if b[3] > 20 and b[2] * b[3] > best_area:
                        best_input, best_area = b, b[2] * b[3]
                for i in range(node.get_child_count()):
                    stack.append((node.get_child_at_index(i), d + 1))
            except Exception:
                continue
        if frame is not None:
            self._cache["frame"] = frame
        self._cache["input"] = best_input
        return "msgs" in self._cache and "sess" in self._cache
    # ---------- 读取 ----------

    def rect(self):
        """主窗口渲染矩形。优先按「消息列表→父链→frame」定位，避开朋友圈等独立窗口。"""
        if self.app is None:
            return None
        anchor = self._cache.get("nav") or self._cache.get("msgs") or self._cache.get("sess")
        fr = self._frame_of(anchor) if anchor is not None else None
        if fr is None:
            fr = self._cache.get("frame")
        if fr is None:
            return None
        b = _box(fr)
        return b if b[2] > 0 and b[3] > 0 else None

    def sessions(self):
        node = self._node("sess", "list", "会话")
        if node is None:
            return []
        out = []
        try:
            n = node.get_child_count()
        except Exception:
            self._cache.pop("sess", None)
            return []
        for i in range(n):
            try:
                it = node.get_child_at_index(i)
            except Exception:
                continue
            parts = [p.strip() for p in _text(it).split("\n")]
            while len(parts) < 3:
                parts.append("")
            try:
                sel = it.get_state_set().contains(Atspi.StateType.SELECTED)
            except Exception:
                sel = False
            out.append({"name": parts[0], "last": parts[1], "time": parts[2],
                        "box": _box(it), "selected": bool(sel)})
        return out

    def search_items(self):
        """搜索结果里的条目（name + box）；分组标题也一起返回，调用方自己筛。"""
        out = []
        for node in self._find_all("list", ""):
            try:
                if node.get_child_count() < 2: continue
                for i in range(node.get_child_count()):
                    it = node.get_child_at_index(i)
                    nm = _text(it).strip()
                    if nm: out.append({"name": nm, "box": _box(it)})
            except Exception:
                continue
        return out

    def contacts(self):
        """通讯录列表（只含当前可见项）：[{"name": 备注, "box": [x,y,w,h]}]。

        列表里夹着字母分组头（name 为空）和「联系人 10」这种计数行，一并过滤。
        """
        node = None
        for cand in self._find_all("list", "通讯录"):
            try:
                if cand.get_child_count() > 0:
                    node = cand; break
            except Exception:
                continue
        if node is None: return []
        out = []
        try:
            n = node.get_child_count()
        except Exception:
            return []
        for i in range(n):
            try:
                it = node.get_child_at_index(i)
                nm = _text(it).strip()
                if not nm or nm.startswith("联系人"): continue
                out.append({"name": nm, "box": _box(it)})
            except Exception:
                continue
        return out

    def _find_all(self, role, name):
        res = []
        stack = [(self.app, 0)]
        seen = 0
        while stack and seen < MAX_NODES:
            node, d = stack.pop(); seen += 1
            if d > 24: continue
            try:
                if node.get_role_name() == role and _text(node) == name:
                    res.append(node)
                for i in range(node.get_child_count()):
                    stack.append((node.get_child_at_index(i), d + 1))
            except Exception:
                continue
        return res

    def messages(self):
        node = self._node("msgs", "list", "消息")
        if node is None:
            return []
        out = []
        try:
            n = node.get_child_count()
        except Exception:
            self._cache.pop("msgs", None)
            return []
        for i in range(n):
            try:
                it = node.get_child_at_index(i)
            except Exception:
                continue
            t = _text(it).replace("\n", " ")
            kind = "sticker" if t in STICKER_NAMES else ("text" if t else "empty")
            out.append({"text": t, "box": _box(it), "kind": kind})
        return out

    def _scan_input(self):
        if self.app is None:
            return None
        best, best_area = None, 0
        stack, seen = [(self.app, 0)], 0
        while stack and seen < MAX_NODES:
            node, d = stack.pop()
            seen += 1
            if d > 24:
                continue
            try:
                if node.get_role_name() == "text" and \
                        node.get_state_set().contains(Atspi.StateType.EDITABLE):
                    b = _box(node)
                    if b[3] > 20 and b[2] * b[3] > best_area:
                        best, best_area = b, b[2] * b[3]
                for i in range(node.get_child_count()):
                    stack.append((node.get_child_at_index(i), d + 1))
            except Exception:
                continue
        return best

    def input_box(self):
        b = self._cache.get("input")
        if b is None:
            b = self._scan_input()
            self._cache["input"] = b
        return b

    def list_box(self):
        """消息列表容器矩形，用来排除顶部标题栏。"""
        node = self._node("msgs", "list", "消息")
        return _box(node) if node is not None else None

    def flags(self):
        out = {"locked": False, "net_down": False, "has_nav": False}
        if self.app is None:
            return out
        lock = self._node("lock", "label", "Linux 微信已被锁定")
        net = self._node("net", "label", "当前网络不可用")
        nav = self._node("nav", "tool bar", "导航")
        out["locked"] = bool(lock is not None and _showing(lock))
        out["net_down"] = bool(net is not None and _showing(net))
        out["has_nav"] = bool(nav is not None and _showing(nav))
        return out

    # ---------- 几何 ----------

    def side(self, img, msg_box, edge=48):
        """判左右：先用绿气泡（仅自己发）做强信号，否则比左右边缘墨迹密度。

        取值 img 可以是灰度图或 BGR 彩图；彩图且检出绿气泡时直接判 me。
        边界要内缩：左侧 10px 是分隔线，右侧 16px 是滚动条，不排会把它们当内容。
        """
        r = self.rect()
        if r is None or not msg_box or msg_box[2] <= 0:
            return None
        try:
            import numpy as np
        except Exception:
            return None
        fx, fy, fw, fh = r
        x0 = max(fx + 10, msg_box[0] + 10)
        x1 = min(fx + fw - 16, msg_box[0] + msg_box[2] - 16)
        y0 = max(fy, msg_box[1] + 4)
        y1 = min(fy + fh, msg_box[1] + msg_box[3] - 4, y0 + 56)
        if x1 - x0 < 2 * edge + 10 or y1 - y0 < 12:
            return None
        roi = img[y0:y1, x0:x1]
        if roi.ndim == 3:
            b, g, r_ = roi[:, :, 0].astype(int), roi[:, :, 1].astype(int), roi[:, :, 2].astype(int)
            if ((g > r_ + 12) & (g > b + 12)).mean() > 0.08:
                return "me"
            vals, cnts = np.unique(roi.max(axis=2), return_counts=True)
            bg = int(vals[np.argmax(cnts)])
            mask = np.abs(roi.max(axis=2).astype(np.int16) - bg) > 12
        else:
            vals, cnts = np.unique(roi, return_counts=True)
            bg = int(vals[np.argmax(cnts)])
            mask = np.abs(roi.astype(np.int16) - bg) > 12
        left = float(mask[:, :edge].mean())
        right = float(mask[:, -edge:].mean())
        if max(left, right) < 0.03:
            # 墨迹太淡（超短消息/半截贴纸）时，用量像锚点兜底；两侧都有就不猜
            la = _avatar_in(mask[:, :52])
            ra = _avatar_in(mask[:, -52:])
            if la and not ra:
                return "peer"
            if ra and not la:
                return "me"
            return None
        return "peer" if left > right else "me"


def state():
    w = Wx()
    w.warm()
    return {
        "ok": w.app is not None,
        "rect": w.rect(),
        "sessions": w.sessions(),
        "messages": w.messages(),
        "input_box": w.input_box(),
        "flags": w.flags(),
    }
