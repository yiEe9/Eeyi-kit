import importlib.util, os, time, sys
PREFIX = os.environ.get("PREFIX") or "/root"
spec = importlib.util.spec_from_file_location("wxbot3", os.path.join(PREFIX, "wxbot3.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

TARGET = "文件传输助手"
m.grab()
items = m.ocr_items()
c = [i for i in items if i["cx"] < m.G.list_xmax and TARGET in i["t"]]
if not c:
    print("FAIL 列表里找不到", TARGET); sys.exit(1)
m.click(m.G.list_click_x, c[0]["cy"])
time.sleep(1.5)
m.grab(); items = m.ocr_items()
sess = m.current_session(items)
print("session:", sess)
if not m.same(sess, TARGET):
    print("FAIL 会话未切换"); sys.exit(1)
msgs = m.parse(items)
print("before:", [(x["sender"], x["text"][:16]) for x in msgs[-3:]])

text = "自检 ping " + time.strftime("%H:%M:%S")
m.send_multi(text, list(m.G.input_xy))
time.sleep(1.2)
ok = m.sent_ok(text)
print("sent:", text, "-> verify", "PASS" if ok else "FAIL")
m.grab(); after = m.parse(m.ocr_items())
print("after:", [(x["sender"], x["text"][:16]) for x in after[-3:]])
sys.exit(0 if ok else 1)
