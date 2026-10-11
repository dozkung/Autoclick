"""เทสต์ logic ของ autoclicker โดยไม่ต้องมีจอจริง

stub pynput กับ tkinter ไว้ใน sys.modules ก่อน import autoclicker
แล้วเทสต์ Runner ด้วย FakeMouse ที่บันทึก log การคลิกไว้

รัน: python -m unittest discover -s tests -v
"""
import ctypes
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ stubs
def _install_stubs():
    class _Any:
        """รับทุก argument ไม่ทำอะไร ใช้แทน class ของ tkinter/pynput ที่เทสต์ไม่ได้แตะ"""
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            return lambda *a, **k: None

    # --- tkinter
    tk = types.ModuleType("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    for name in ("Tk", "Toplevel", "StringVar", "IntVar", "DoubleVar", "BooleanVar"):
        setattr(tk, name, type(name, (_Any,), {}))
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "Combobox", "Spinbox", "Treeview",
                 "Scrollbar", "LabelFrame", "Radiobutton", "Checkbutton", "Style"):
        setattr(ttk, name, type(name, (_Any,), {}))
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askopenfilename = lambda **k: ""
    filedialog.asksaveasfilename = lambda **k: ""
    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.errors = []
    messagebox.showerror = lambda title, msg, **k: messagebox.errors.append(msg)
    messagebox.askyesno = lambda *a, **k: True
    font = types.ModuleType("tkinter.font")
    font.nametofont = lambda name: _Any()
    tk.ttk, tk.filedialog, tk.messagebox, tk.font = ttk, filedialog, messagebox, font

    # --- pynput
    pynput = types.ModuleType("pynput")
    keyboard = types.ModuleType("pynput.keyboard")
    keyboard.Key = types.SimpleNamespace(f6="f6", f8="f8", f9="f9")
    keyboard.Listener = type("Listener", (_Any,), {})
    mouse = types.ModuleType("pynput.mouse")
    mouse.Button = types.SimpleNamespace(left="left", right="right")
    mouse.Controller = type("Controller", (_Any,), {})
    pynput.keyboard, pynput.mouse = keyboard, mouse

    sys.modules.update({
        "tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": filedialog,
        "tkinter.messagebox": messagebox, "tkinter.font": font,
        "pynput": pynput, "pynput.keyboard": keyboard, "pynput.mouse": mouse,
    })


_install_stubs()
sys.path.insert(0, ROOT)
import autoclicker as ac  # noqa: E402


# ------------------------------------------------------------------ fakes
class FakeMouse:
    """แทน pynput.mouse.Controller บันทึกทุกการคลิกพร้อมพิกัดตอนนั้น"""

    def __init__(self, pos=(500, 500)):
        self._lock = threading.Lock()
        self._pos = pos
        self.log = []      # (action, button, count, (x, y)) เฉพาะปุ่มเมาส์
        self.events = []   # (kind, (x, y), เวลา) ทุกอย่างรวม move/nudge ไว้เช็กลำดับ
        self.pressed = set()

    def _event(self, kind):
        self.events.append((kind, self._pos, time.monotonic()))

    @property
    def position(self):
        with self._lock:
            return self._pos

    @position.setter
    def position(self, xy):
        with self._lock:
            self._pos = tuple(xy)
        self._event("move")

    def nudge(self):
        """แทน nudge_mouse: บันทึกว่าถูกเรียกตอนเมาส์อยู่ที่ไหน"""
        self._event("nudge")

    def click(self, button, count=1):
        self._event("click")
        self.log.append(("click", button, count, self.position))

    def press(self, button):
        self.pressed.add(button)
        self._event("press")
        self.log.append(("press", button, 1, self.position))

    def release(self, button):
        self.pressed.discard(button)
        self._event("release")
        self.log.append(("release", button, 1, self.position))

    def clicks(self):
        return [e for e in self.log if e[0] == "click"]


def cfg(**kw):
    c = {"mode": "loop", "rounds": 1, "minutes": 5.0, "jitter_px": 0, "jitter_ms": 0, "hover_ms": 0}
    c.update(kw)
    return c


def step(x, y, ctype="left", delay_ms=10, hold_ms=0, repeat=1, gap_ms=ac.DEFAULT_GAP_MS):
    return ac.make_step(x, y, ctype, delay_ms, hold_ms, repeat, gap_ms)


class RunnerHarness:
    def __init__(self, steps, config, mouse=None, origin=(0, 0), nudge=None):
        self.mouse = mouse or FakeMouse()
        self.done = threading.Event()
        self.reason = None
        self.statuses = []  # (รอบ, จุด, ครั้งที่, repeat)
        # ต้อง inject nudge เสมอ ไม่งั้นรันเทสต์บน Windows จะไปขยับเมาส์จริงของเครื่อง
        self.runner = ac.Runner(steps, config, self.mouse,
                                on_status=lambda *a: self.statuses.append(a),
                                on_done=self._on_done, origin=origin,
                                nudge=nudge or self.mouse.nudge)

    def _on_done(self, reason):
        self.reason = reason
        self.done.set()

    def start(self):
        self.runner.start()
        return self

    def wait_for(self, cond, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.005)
        return False

    def finish(self, timeout=5.0):
        self.runner.join(timeout)
        assert not self.runner.is_alive(), "runner ไม่ยอมจบ"
        return self.reason


# ------------------------------------------------------------------ tests
class RunnerTests(unittest.TestCase):
    def test_count_three_rounds_clicks_in_order(self):
        steps = [step(100, 100, "left"), step(200, 150, "right"), step(300, 250, "double")]
        h = RunnerHarness(steps, cfg(mode="count", rounds=3)).start()
        self.assertEqual(h.finish(), "ครบ 3 รอบ")
        expected = [("click", "left", 1, (100, 100)),
                    ("click", "right", 1, (200, 150)),
                    ("click", "left", 2, (300, 250))] * 3
        self.assertEqual(h.mouse.clicks(), expected)

    def test_long_delay_stops_fast(self):
        h = RunnerHarness([step(100, 100, delay_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")

    def test_hold_released_when_stopped(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.pressed))
        h.runner.stop("หยุดโดยผู้ใช้")
        h.finish(timeout=0.3)
        actions = [e[0] for e in h.mouse.log]
        self.assertEqual(actions, ["press", "release"])
        self.assertEqual(h.mouse.pressed, set())

    def test_time_mode_stops_after_deadline(self):
        t0 = time.monotonic()
        h = RunnerHarness([step(100, 100)], cfg(mode="time", minutes=0.5 / 60)).start()
        reason = h.finish()
        elapsed = time.monotonic() - t0
        self.assertEqual(reason, "ครบเวลาที่ตั้งไว้")
        self.assertGreaterEqual(elapsed, 0.45)
        self.assertLess(elapsed, 0.8)

    def test_kill_switch_stops(self):
        h = RunnerHarness([step(100, 100, delay_ms=5000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), ac.KILL_REASON)

    def test_jitter_never_lands_in_kill_zone(self):
        h = RunnerHarness([step(4, 4)], cfg(mode="count", rounds=50, jitter_px=10)).start()
        self.assertEqual(h.finish(timeout=10), "ครบ 50 รอบ")
        clicks = h.mouse.clicks()
        self.assertEqual(len(clicks), 50)
        for _, _, _, (x, y) in clicks:
            self.assertFalse(ac.in_corner(x, y), (x, y))

    def test_jitter_respects_negative_origin(self):
        origin = (-1920, 0)
        h = RunnerHarness([step(-1916, 4)], cfg(mode="count", rounds=50, jitter_px=10),
                          origin=origin).start()
        self.assertEqual(h.finish(timeout=10), "ครบ 50 รอบ")
        for _, _, _, (x, y) in h.mouse.clicks():
            self.assertFalse(ac.in_corner(x, y, origin), (x, y))

    def test_negative_origin_zero_is_not_kill_zone(self):
        # จอเสริมอยู่ทางซ้าย: (0,0) เป็นแค่มุมของจอหลัก ไม่ใช่ขอบจริง ต้องไม่หยุด
        h = RunnerHarness([step(0, 0)], cfg(mode="count", rounds=2), origin=(-1920, 0)).start()
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        self.assertEqual(len(h.mouse.clicks()), 2)

    def test_negative_origin_real_corner_stops(self):
        h = RunnerHarness([step(100, 100, delay_ms=5000)], cfg(), origin=(-1920, 0)).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        h.mouse.position = (-1920, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), ac.KILL_REASON)

    def test_exception_reported_as_error(self):
        class BrokenMouse(FakeMouse):
            def click(self, button, count=1):
                raise RuntimeError("boom")
        h = RunnerHarness([step(100, 100)], cfg(), mouse=BrokenMouse()).start()
        self.assertEqual(h.finish(), "error: boom")

    def test_empty_steps_reports_error_instead_of_spinning(self):
        h = RunnerHarness([], cfg()).start()
        self.assertTrue(h.finish(timeout=1).startswith("error:"))


class CornerTests(unittest.TestCase):
    def test_default_origin(self):
        self.assertTrue(ac.in_corner(0, 0))
        self.assertTrue(ac.in_corner(3, 3))
        self.assertFalse(ac.in_corner(4, 3))
        self.assertFalse(ac.in_corner(3, 4))

    def test_negative_origin(self):
        o = (-1920, 0)
        self.assertFalse(ac.in_corner(0, 0, o))
        self.assertTrue(ac.in_corner(-1920, 0, o))
        self.assertTrue(ac.in_corner(-1917, 3, o))
        self.assertFalse(ac.in_corner(-1916, 0, o))


class ValidateTests(unittest.TestCase):
    def test_missing_y_raises(self):
        with self.assertRaises(ValueError):
            ac.validate_step({"x": 1})

    def test_rejects_bad_values(self):
        bad = [
            "not a dict",
            {"x": 0, "y": 0},                          # อยู่ในโซน kill switch
            {"x": 10.5, "y": 10},                      # ไม่ใช่จำนวนเต็ม
            {"x": True, "y": 10},
            {"x": 10, "y": 10, "type": "middle"},
            {"x": 10, "y": 10, "delay_ms": 9},
            {"x": 10, "y": 10, "hold_ms": -1},
        ]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(ValueError):
                ac.validate_step(d)

    def test_fills_defaults(self):
        s = ac.validate_step({"x": 10, "y": 20})
        self.assertEqual(s, {"x": 10, "y": 20, "type": "left", "delay_ms": 500, "hold_ms": 500,
                             "repeat": 1, "gap_ms": 100})

    def test_corner_uses_origin(self):
        self.assertEqual(ac.validate_step({"x": 0, "y": 0}, (-1920, 0))["x"], 0)
        with self.assertRaises(ValueError):
            ac.validate_step({"x": -1920, "y": 0}, (-1920, 0))

    def test_parse_profile_skips_corner_check_by_default(self):
        steps, _, _ = ac.parse_profile({"steps": [{"x": 0, "y": 0}]})
        self.assertEqual(steps[0]["x"], 0)
        with self.assertRaises(ValueError):
            ac.parse_profile({"steps": [{"x": 0, "y": 0}]}, origin=(0, 0))

    def test_parse_profile_defaults(self):
        steps, st, dflt = ac.parse_profile({"steps": [{"x": 10, "y": 20}]})
        self.assertEqual(len(steps), 1)
        self.assertEqual(st, ac.DEFAULT_SETTINGS)
        self.assertEqual(dflt, ac.DEFAULT_DEFAULTS)

    def test_parse_profile_rejects_bad_settings(self):
        bad = [
            {"settings": []},
            {"settings": {"mode": "forever"}},
            {"settings": {"rounds": 0}},
            {"settings": {"minutes": 0}},
            {"settings": {"jitter_px": 51}},
            {"settings": {"jitter_ms": 5001}},
            {"defaults": {"delay_ms": 5}},
            {"steps": {"x": 1}},
        ]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(ValueError):
                ac.parse_profile(d)


class FakeVar:
    def __init__(self, v=None):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class FakeMarker:
    """แทน Marker (Toplevel) บันทึกการซ่อน/แสดง/ดีดกลับลง log ที่แชร์กับ test"""

    def __init__(self, index, log):
        self.index, self.log, self.visible = index, log, False

    def withdraw(self):
        self.visible = False
        self.log.append(("withdraw", self.index))

    def deiconify(self):
        self.visible = True
        self.log.append(("deiconify", self.index))

    def snap_back(self):
        self.log.append(("snap_back", self.index))

    def destroy(self):
        self.log.append(("destroy", self.index))


class FakeWidget:
    def __init__(self):
        self.text = None

    def configure(self, **k):
        self.text = k.get("text", self.text)


class FakeTree:
    def __init__(self):
        self.selected = None

    def selection_set(self, iid):
        self.selected = iid

    def see(self, iid):
        pass

    def exists(self, iid):
        return False


class FakeApp(ac.App):
    """App ที่ข้าม __init__ (ไม่สร้าง Tk) ใส่แค่ attribute ที่ method ต่างๆ ใช้"""

    def __init__(self, steps):
        self.log = []
        self.runner = None
        self.steps = list(steps)
        self.status = FakeVar()
        self.mode, self.rounds, self.minutes = FakeVar("loop"), FakeVar(10), FakeVar(5.0)
        self.jit_px, self.jit_ms = FakeVar(0), FakeVar(0)
        self.def_type, self.def_delay = FakeVar(ac.CLICK_LABEL["left"]), FakeVar(500)
        self.def_delay_unit = FakeVar("ms")
        self.def_repeat = FakeVar(1)
        self.hover = FakeVar(50)
        self.show_markers = FakeVar(True)
        self.markers_suspended = False
        self.smooth_markers, self._marker_warned, self.marker_scale = False, False, 1.0
        self.hotkeys = {a: dict(hk) for a, hk in ac.DEFAULT_HOTKEYS.items()}
        self.matcher = ac.HotkeyMatcher(self.hotkeys, read_mods=SET_ONLY)
        self.kb = None
        self.hotkey_dialog = None
        self.settings_file = None
        self.hint_lbl, self.markers_chk = FakeWidget(), FakeWidget()
        self.running_row = None
        self.markers = []
        self.q = ac.queue.Queue()
        self.mouse = FakeMouse()
        self.tree = FakeTree()
        self.root = types.SimpleNamespace(update_idletasks=lambda: self.log.append("update_idletasks"),
                                          after=lambda *a: None)
        self.run_btn = FakeWidget()

    def refresh(self, select=None):
        # แทน refresh จริง: สร้าง FakeMarker ตามจำนวน steps เหมือน _rebuild_markers
        self.log.append(("refresh", select))
        for m in self.markers:
            m.destroy()
        self.markers = [FakeMarker(i, self.log) for i in range(len(self.steps))]
        self._apply_markers()


def fake_app(steps):
    return FakeApp(steps)


class LoadTests(unittest.TestCase):
    """เรียก App.load กับ object ปลอม เพื่อเช็กว่าไฟล์พังแล้วข้อมูลเดิมไม่หาย"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = [step(100, 100), step(200, 200, "right")]
        self.app = fake_app(self.original)
        ac.messagebox.errors.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _load(self, text):
        path = os.path.join(self.tmp.name, "p.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        ac.filedialog.askopenfilename = lambda **k: path
        ac.App.load(self.app)

    def test_broken_json_keeps_steps(self):
        self._load('{"steps": [{"x": 1')
        self.assertEqual(self.app.steps, self.original)
        self.assertEqual(len(ac.messagebox.errors), 1)

    def test_one_bad_step_keeps_steps(self):
        self._load(json.dumps({"steps": [{"x": 50, "y": 50}, {"x": 60}]}))
        self.assertEqual(self.app.steps, self.original)

    def test_bad_settings_keeps_everything(self):
        self._load(json.dumps({"steps": [{"x": 50, "y": 50}], "settings": {"rounds": "abc"}}))
        self.assertEqual(self.app.steps, self.original)
        self.assertEqual(self.app.rounds.get(), 10)

    def test_good_file_replaces(self):
        self._load(json.dumps({
            "version": 1,
            "steps": [{"x": 812, "y": 455, "type": "hold", "delay_ms": 500, "hold_ms": 300}],
            "settings": {"mode": "count", "rounds": 3, "minutes": 2, "jitter_px": 5, "jitter_ms": 50},
            "defaults": {"type": "right", "delay_ms": 250}}))
        self.assertEqual(self.app.steps, [step(812, 455, "hold", 500, 300)])
        self.assertEqual(self.app.mode.get(), "count")
        self.assertEqual(self.app.rounds.get(), 3)
        self.assertEqual(self.app.jit_px.get(), 5)
        self.assertEqual(self.app.def_type.get(), ac.CLICK_LABEL["right"])
        self.assertEqual(self.app.def_delay.get(), 250)
        self.assertEqual(ac.messagebox.errors, [])

    def test_refuses_while_running(self):
        self.app.runner = types.SimpleNamespace(is_alive=lambda: True)
        self._load(json.dumps({"steps": []}))
        self.assertEqual(self.app.steps, self.original)

    def test_corner_step_loads_so_user_can_fix_it(self):
        self._load(json.dumps({"steps": [{"x": 0, "y": 0}]}))
        self.assertEqual(self.app.steps, [step(0, 0, "left", 500, 500)])
        self.assertEqual(ac.messagebox.errors, [])


class SaveTests(unittest.TestCase):
    """ไฟล์ที่ save ออกไปต้องผ่าน parse_profile เสมอ ถ้าไม่ผ่านต้องไม่เขียนไฟล์"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "out.json")
        ac.filedialog.asksaveasfilename = lambda **k: self.path
        ac.messagebox.errors.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _save_and_reparse(self, app):
        ac.App.save(app)
        self.assertEqual(ac.messagebox.errors, [])
        with open(self.path, encoding="utf-8") as f:
            return ac.parse_profile(json.load(f))

    def test_round_trip(self):
        steps = [step(812, 455, "hold", 500, 300), step(10, 20, "double", 10, 0)]
        app = fake_app(steps)
        app.mode.set("count")
        app.rounds.set(3)
        app.def_type.set(ac.CLICK_LABEL["right"])
        app.def_delay.set(250)
        got_steps, st, dflt = self._save_and_reparse(app)
        self.assertEqual(got_steps, steps)
        self.assertEqual((st["mode"], st["rounds"]), ("count", 3))
        self.assertEqual(dflt, {"type": "right", "delay_ms": 250, "repeat": 1})

    def test_always_reparses_with_extreme_ui_values(self):
        # ค่าที่พิมพ์ลง Spinbox ได้แต่อยู่นอกช่วง _cfg ต้องบีบให้ผ่านก่อนเซฟ
        cases = [
            {"rounds": 0, "minutes": 0, "jit_px": 999, "jit_ms": 99999, "hover": 99999},
            {"rounds": -5, "minutes": -1, "jit_px": -3, "jit_ms": -10, "hover": -1},
            {"rounds": "abc", "minutes": "x", "jit_px": "?", "jit_ms": "", "hover": "x"},
        ]
        for mode in ac.MODES:
            for c in cases:
                with self.subTest(mode=mode, c=c):
                    app = fake_app([step(0, 0)])  # จุดในโซน kill switch ก็เซฟได้ ไปเช็กตอนเริ่ม
                    app.mode.set(mode)
                    for key, v in c.items():
                        getattr(app, key).set(v)
                    self._save_and_reparse(app)

    def test_bad_default_delay_blocks_save(self):
        app = fake_app([step(100, 100)])
        app.def_delay.set(5)
        ac.App.save(app)
        self.assertEqual(len(ac.messagebox.errors), 1)
        self.assertFalse(os.path.exists(self.path))


class ScreenRectTests(unittest.TestCase):
    def test_none_rect_skips_check(self):
        self.assertFalse(ac.out_of_screen(-99999, 99999, None))

    def test_bounds(self):
        rect = (-1920, 0, 3840, 1080)  # จอเสริมอยู่ทางซ้ายจอหลัก
        for xy in [(-1920, 0), (1919, 1079), (0, 0)]:
            self.assertFalse(ac.out_of_screen(*xy, rect), xy)
        for xy in [(-1921, 0), (1920, 0), (0, -1), (0, 1080)]:
            self.assertTrue(ac.out_of_screen(*xy, rect), xy)


class ToggleTests(unittest.TestCase):
    """toggle() ต้องไม่เริ่มถ้ามีจุดนอกจอหรือในโซน kill switch"""

    def setUp(self):
        self._orig = ac.get_virtual_rect, ac.get_virtual_origin, ac.Runner
        ac.get_virtual_rect = lambda: (0, 0, 1920, 1080)
        ac.get_virtual_origin = lambda: (0, 0)
        self.started = []
        ac.Runner = lambda *a, **k: self.started.append(a) or types.SimpleNamespace(start=lambda: None)

    def tearDown(self):
        ac.get_virtual_rect, ac.get_virtual_origin, ac.Runner = self._orig

    def _toggle(self, steps):
        app = fake_app(steps)
        ac.App.toggle(app)
        return app.status.get()

    def test_out_of_screen_refuses(self):
        self.assertEqual(self._toggle([step(100, 100), step(2500, 100)]),
                         "จุด #2 อยู่นอกจอ (ถอดจอออก?)")
        self.assertEqual(self.started, [])

    def test_corner_refuses(self):
        self.assertIn("kill switch", self._toggle([step(0, 0)]))
        self.assertEqual(self.started, [])

    def test_skip_screen_check_when_rect_unknown(self):
        ac.get_virtual_rect = lambda: None
        self._toggle([step(5000, 5000)])
        self.assertEqual(len(self.started), 1)

    def test_valid_steps_start(self):
        self.assertEqual(self._toggle([step(100, 100)]), "กำลังรัน…")
        self.assertEqual(len(self.started), 1)


def parse_geometry(g):
    """"48x48+-1944+-24" -> (w, h, x, y)"""
    import re
    w, h, x, y = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", g).groups()
    return int(w), int(h), int(x), int(y)


class MarkerGeometryTests(unittest.TestCase):
    def test_center_on_step(self):
        self.assertEqual(ac.marker_geometry(100, 200), "30x30+85+185")
        self.assertEqual(ac.marker_geometry(100, 200, 44), "44x44+78+178")

    def test_negative_coords_use_plus_minus(self):
        # "-1934" ใน Tk แปลว่าวัดจากขอบขวา ต้องเป็น "+-1934"
        self.assertEqual(ac.marker_geometry(-1920, 0), "30x30+-1935+-15")
        self.assertEqual(ac.marker_geometry(-1900, -300), "30x30+-1915+-315")

    def test_near_zero_crosses_sign(self):
        self.assertEqual(ac.marker_geometry(5, 5), "30x30+-10+-10")

    def test_marker_size_scales_with_dpi(self):
        self.assertEqual(ac.marker_size(1.0), 30)   # วงกลม ~28px + ขอบเผื่อ
        self.assertEqual(ac.marker_size(1.5), 44)
        self.assertEqual(ac.marker_size(2.0), 60)
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0, 0.1):
            self.assertEqual(ac.marker_size(scale) % 2, 0)  # เลขคู่ ศูนย์กลางเป็น pixel เต็ม

    def test_center_pixel_is_step_at_every_scale(self):
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            size = ac.marker_size(scale)
            for x, y in [(100, 200), (-1920, 0), (-1, -1), (0, 0), (3839, 2159)]:
                with self.subTest(scale=scale, x=x, y=y):
                    w, h, wx, wy = parse_geometry(ac.marker_geometry(x, y, size))
                    self.assertEqual((w, h), (size, size))
                    self.assertEqual((wx + size // 2, wy + size // 2), (x, y))  # ศูนย์กลาง = จุดคลิก

    def test_text_layout(self):
        (t, dy, px), = ac.marker_text_layout(7, 1, 30)
        self.assertEqual((t, dy), ("7", 0.0))
        two = ac.marker_text_layout(42, 1, 30)[0][2]
        self.assertLess(two, px)                                  # 2 หลักฟอนต์เล็กลง
        num, rep = ac.marker_text_layout(42, 3, 30)
        self.assertEqual((num[0], rep[0]), ("42", "×3"))
        self.assertLess(num[1], 0)                                # เลขขยับขึ้น
        self.assertGreater(rep[1], 0)                             # ×n อยู่ใต้เลข
        self.assertLess(ac.marker_text_layout(1, 1000, 30)[1][2], rep[2])  # ×1000 เล็กกว่า ×3
        self.assertGreater(ac.marker_text_layout(42, 3, 44)[0][2], num[2])  # ขยายตาม DPI


@unittest.skipUnless(ac._load_pil() is not None, "ต้องมี Pillow (pip install -r requirements.txt)")
class RenderMarkerImageTests(unittest.TestCase):
    def test_size_and_mode(self):
        for size in (30, 44, 60):
            img = ac.render_marker_image(1, "#1e6fd9", 1, size)
            self.assertEqual((img.size, img.mode), ((size, size), "RGBA"))

    def test_corner_transparent_center_opaque(self):
        img = ac.render_marker_image(1, "#1e6fd9", 1, 30)
        for corner in [(0, 0), (29, 0), (0, 29), (29, 29)]:
            self.assertEqual(img.getpixel(corner)[3], 0, corner)
        self.assertEqual(img.getpixel((15, 15))[3], 255)
        self.assertEqual(img.getpixel((15, 5))[3], 255)  # ในวงแต่ไม่โดนตัวเลข

    def test_edge_is_antialiased(self):
        img = ac.render_marker_image(1, "#1e6fd9", 1, 30)
        alphas = set(img.getchannel("A").getdata())
        partial = [a for a in alphas if 0 < a < 255]
        self.assertGreaterEqual(len(partial), 5)  # มีค่า alpha ไล่ระดับที่ขอบ = ขอบเนียน
        # เดินจากมุมเข้าหากลางตามแนวทแยง ต้องผ่านค่า alpha กลางๆ ก่อนถึงทึบ
        diag = [img.getpixel((i, i))[3] for i in range(0, 15)]
        self.assertTrue(any(0 < a < 255 for a in diag), diag)

    def test_white_border_and_fill_color(self):
        img = ac.render_marker_image(1, "#d62828", 1, 30)
        r, g, b, a = img.getpixel((15, 2))  # บนขอบขาวด้านบน
        self.assertGreater(min(r, g, b), 200)
        self.assertEqual(img.getpixel((8, 15)), (0xd6, 0x28, 0x28, 255))  # ในวง ไม่โดนตัวเลข

    def test_digits_and_repeat_do_not_error(self):
        for n, rep in [(1, 1), (9, 1), (10, 1), (99, 1), (100, 1), (7, 3), (42, 12), (99, 1000)]:
            for size in (30, 44):
                with self.subTest(n=n, rep=rep, size=size):
                    self.assertEqual(ac.render_marker_image(n, "#7b3fe4", rep, size).size, (size, size))

    def test_text_is_drawn(self):
        img = ac.render_marker_image(1, "#1e6fd9", 1, 30)
        whites = [x for x in range(6, 24) if min(img.getpixel((x, 15))[:3]) > 200]
        self.assertTrue(whites)  # ตัวเลขสีขาวกลางวง

    def test_font_fallback_when_no_ttf(self):
        orig, ac._FONT_FILES = ac._FONT_FILES, (r"C:\nope\missing.ttf",)
        ac._font_cache.clear()
        try:
            self.assertEqual(ac.render_marker_image(42, "#1e6fd9", 3, 30).size, (30, 30))
        finally:
            ac._FONT_FILES = orig
            ac._font_cache.clear()


class PremultiplyTests(unittest.TestCase):
    class Img:
        def __init__(self, pixels):
            self.pixels = pixels

        def tobytes(self):
            return bytes(v for px in self.pixels for v in px)

    def test_premultiply_and_bgra_order(self):
        out = ac.premultiply_bgra(self.Img([(255, 128, 0, 128), (10, 20, 30, 255), (200, 100, 50, 0),
                                            (255, 255, 255, 1)]))
        self.assertEqual(list(out[0:4]), [0, 64, 128, 128])      # B G R A, r*a/255 ปัดเศษ
        self.assertEqual(list(out[4:8]), [30, 20, 10, 255])     # alpha เต็ม = สีเดิม
        self.assertEqual(list(out[8:12]), [0, 0, 0, 0])         # โปร่งหมด = ดำ (ไม่งั้นขอบสว่างผิด)
        self.assertEqual(list(out[12:16]), [1, 1, 1, 1])

    def test_never_exceeds_alpha(self):
        pixels = [(r, 255 - r, (r * 7) % 256, a) for r in range(0, 256, 17) for a in range(0, 256, 15)]
        out = ac.premultiply_bgra(self.Img(pixels))
        for i in range(0, len(out), 4):
            self.assertLessEqual(max(out[i:i + 3]), out[i + 3])


class SmoothFallbackTests(unittest.TestCase):
    def test_load_pil_none_when_import_fails(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("no PIL")
            return real_import(name, *a, **k)
        builtins.__import__ = fake_import
        try:
            self.assertIsNone(ac._load_pil())
            self.assertFalse(ac.smooth_markers_available())
            with self.assertRaises(ImportError):
                ac.render_marker_image(1, "#1e6fd9", 1, 30)
        finally:
            builtins.__import__ = real_import

    def test_not_windows_means_not_smooth(self):
        orig = ac.sys.platform
        ac.sys.platform = "linux"
        try:
            self.assertFalse(ac.smooth_markers_available())
        finally:
            ac.sys.platform = orig

    def test_app_falls_back_and_warns_once(self):
        orig = ac._load_pil
        ac._load_pil = lambda: None
        try:
            app = fake_app([])
            app._init_marker_mode()
            self.assertFalse(app.smooth_markers)
            self.assertEqual(app.status.get(), "หมุดแบบเรียบไม่พร้อม ใช้แบบธรรมดา")
            app.status.set("อย่างอื่น")
            app.marker_fallback(OSError("UpdateLayeredWindow failed"))
            self.assertEqual(app.status.get(), "อย่างอื่น")  # เตือนครั้งเดียว
        finally:
            ac._load_pil = orig

    def test_runtime_win32_failure_switches_off_smooth(self):
        app = fake_app([])
        app.smooth_markers = True
        app.marker_fallback(OSError("ULW failed"))
        self.assertFalse(app.smooth_markers)
        self.assertEqual(app.status.get(), "หมุดแบบเรียบไม่พร้อม ใช้แบบธรรมดา")
        self.assertIsInstance(app.marker_fallback_reason, OSError)

    @unittest.skipUnless(sys.platform == "win32", "ต้องใช้ user32 จริง")
    def test_win32_api_has_64bit_safe_signatures(self):
        api = ac._win32_api()
        self.assertIs(api.gdi32.CreateCompatibleDC.restype, ctypes.c_void_p)
        self.assertIs(api.user32.GetDC.restype, ctypes.c_void_p)
        self.assertIsNot(api.user32, ctypes.windll.user32)  # ห้ามไปแก้ ctypes.windll ที่ pynput ใช้ร่วม

    def test_bitmap_header_size(self):
        self.assertEqual(ctypes.sizeof(ac._BITMAPINFOHEADER), 40)
        self.assertEqual(ctypes.sizeof(ac._BLENDFUNCTION), 4)


class TryMoveStepTests(unittest.TestCase):
    RECT = (-1920, 0, 3840, 1080)
    ORIGIN = (-1920, 0)

    def setUp(self):
        self.steps = [step(100, 100, "hold", 250, 300), step(200, 200, "right")]
        self.before = [dict(s) for s in self.steps]

    def test_ok_moves_and_keeps_other_fields(self):
        ok, reason = ac.try_move_step(self.steps, 0, 640, 480, self.ORIGIN, self.RECT)
        self.assertTrue(ok, reason)
        self.assertEqual(self.steps[0], step(640, 480, "hold", 250, 300))
        self.assertEqual(self.steps[1], self.before[1])

    def test_negative_coords_on_left_monitor(self):
        ok, _ = ac.try_move_step(self.steps, 1, -1000, 500, self.ORIGIN, self.RECT)
        self.assertTrue(ok)
        self.assertEqual((self.steps[1]["x"], self.steps[1]["y"]), (-1000, 500))

    def test_primary_corner_is_fine_with_negative_origin(self):
        ok, _ = ac.try_move_step(self.steps, 0, 0, 0, self.ORIGIN, self.RECT)
        self.assertTrue(ok)

    def test_rejects_kill_zone(self):
        ok, reason = ac.try_move_step(self.steps, 0, -1919, 2, self.ORIGIN, self.RECT)
        self.assertFalse(ok)
        self.assertIn("kill switch", reason)
        self.assertEqual(self.steps, self.before)

    def test_rejects_out_of_screen(self):
        ok, reason = ac.try_move_step(self.steps, 0, 1920, 100, self.ORIGIN, self.RECT)
        self.assertFalse(ok)
        self.assertIn("นอกจอ", reason)
        self.assertEqual(self.steps, self.before)

    def test_unknown_rect_skips_screen_check(self):
        ok, _ = ac.try_move_step(self.steps, 0, 9999, 9999, (0, 0), None)
        self.assertTrue(ok)

    def test_bad_index(self):
        for i in (-1, 2):
            ok, _ = ac.try_move_step(self.steps, i, 300, 300, self.ORIGIN, self.RECT)
            self.assertFalse(ok)
        self.assertEqual(self.steps, self.before)


class MarkerAppTests(unittest.TestCase):
    def setUp(self):
        self._orig = ac.get_virtual_rect, ac.get_virtual_origin, ac.Runner
        ac.get_virtual_rect = lambda: (0, 0, 1920, 1080)
        ac.get_virtual_origin = lambda: (0, 0)
        self.app = fake_app([step(100, 100), step(200, 200)])
        self.app.refresh()
        log = self.app.log

        class StubRunner:
            def __init__(self, *a, **k):
                pass

            def start(self):
                log.append("runner.start")

            def is_alive(self):
                return True

        ac.Runner = StubRunner

    def tearDown(self):
        ac.get_virtual_rect, ac.get_virtual_origin, ac.Runner = self._orig

    def test_toggle_hides_markers_before_runner_start(self):
        self.app.log.clear()
        self.app.toggle()
        log = self.app.log
        self.assertIn("runner.start", log)
        start = log.index("runner.start")
        for m in self.app.markers:
            self.assertIn(("withdraw", m.index), log[:start])
            self.assertFalse(m.visible)
        self.assertLess(log.index("update_idletasks"), start)

    def test_markers_come_back_on_done_if_checkbox_on(self):
        self.app.toggle()
        self.app.q.put(("done", "หยุดโดยผู้ใช้"))
        self.app._poll()
        self.assertTrue(all(m.visible for m in self.app.markers))
        self.assertFalse(self.app.markers_suspended)

    def test_markers_stay_hidden_on_done_if_checkbox_off(self):
        self.app.show_markers.set(False)
        self.app.toggle()
        self.app.q.put(("done", "ครบ 1 รอบ"))
        self.app._poll()
        self.assertFalse(any(m.visible for m in self.app.markers))

    def test_refresh_during_run_keeps_markers_hidden(self):
        self.app.toggle()
        self.app.refresh()
        self.assertFalse(any(m.visible for m in self.app.markers))

    def test_refresh_destroys_old_markers(self):
        old = list(self.app.markers)
        self.app.steps.pop()
        self.app.refresh()
        for m in old:
            self.assertIn(("destroy", m.index), self.app.log)
        self.assertEqual(len(self.app.markers), 1)

    def test_markers_hotkey_goes_through_queue(self):
        self.app._on_press(keycode(0x76))  # F7
        self.assertEqual(self.app.q.get_nowait(), ("markers",))
        self.app.q.put(("markers",))
        self.app._poll()
        self.assertFalse(self.app.show_markers.get())
        self.assertFalse(any(m.visible for m in self.app.markers))

    def test_drop_ok_updates_step(self):
        self.app.on_marker_drop(0, 640, 480)
        self.assertEqual((self.app.steps[0]["x"], self.app.steps[0]["y"]), (640, 480))
        self.assertIn(("refresh", 0), self.app.log)

    def test_drop_invalid_snaps_back(self):
        self.app.on_marker_drop(1, 2, 2)  # kill switch
        self.assertEqual(self.app.steps[1], step(200, 200))
        self.assertIn(("snap_back", 1), self.app.log)
        self.assertIn("kill switch", self.app.status.get())

    def test_drop_out_of_screen_snaps_back(self):
        self.app.on_marker_drop(0, 5000, 100)
        self.assertEqual(self.app.steps[0], step(100, 100))
        self.assertIn(("snap_back", 0), self.app.log)
        self.assertIn("นอกจอ", self.app.status.get())

    def test_no_drag_while_running(self):
        self.app.toggle()
        self.assertFalse(self.app.can_drag_markers())
        self.app.on_marker_drop(0, 640, 480)
        self.assertEqual(self.app.steps[0], step(100, 100))
        self.assertIn(("snap_back", 0), self.app.log)

    def test_click_selects_row(self):
        self.app.on_marker_click(1)
        self.assertEqual(self.app.tree.selected, "1")


# ---------------------------------------------------------- repeat per step
class RepeatRunnerTests(unittest.TestCase):
    def test_three_clicks_per_step_in_order(self):
        steps = [step(100, 100, repeat=3, gap_ms=10), step(200, 200, "right", repeat=3, gap_ms=10)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=1)).start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(h.mouse.clicks(), [("click", "left", 1, (100, 100))] * 3
                         + [("click", "right", 1, (200, 200))] * 3)
        self.assertEqual(h.statuses, [(1, 1, 1, 3), (1, 1, 2, 3), (1, 1, 3, 3),
                                      (1, 2, 1, 3), (1, 2, 2, 3), (1, 2, 3, 3)])

    def test_two_steps_repeat_2_and_3_two_rounds(self):
        steps = [step(100, 100, repeat=2, gap_ms=10), step(200, 200, repeat=3, gap_ms=10)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=2)).start()
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        xs = [e[3][0] for e in h.mouse.clicks()]
        self.assertEqual(xs, [100, 100, 200, 200, 200] * 2)  # รวม 10 คลิก

    def test_stop_during_long_gap(self):
        h = RunnerHarness([step(100, 100, repeat=5, gap_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")
        self.assertEqual(len(h.mouse.clicks()), 1)  # ไม่รอให้ครบ repeat

    def test_hold_repeat_stopped_midway_releases(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=30000, repeat=2, gap_ms=10)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.pressed))
        h.runner.stop("หยุดโดยผู้ใช้")
        h.finish(timeout=0.3)
        self.assertEqual([e[0] for e in h.mouse.log], ["press", "release"])  # ไม่ไปกดครั้งที่ 2
        self.assertEqual(h.mouse.pressed, set())

    def test_hold_repeat_releases_every_time(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=10, repeat=3, gap_ms=10)],
                          cfg(mode="count", rounds=1)).start()
        h.finish()
        self.assertEqual([e[0] for e in h.mouse.log], ["press", "release"] * 3)
        self.assertEqual(h.mouse.pressed, set())

    def test_double_repeat(self):
        h = RunnerHarness([step(100, 100, "double", repeat=2, gap_ms=10)],
                          cfg(mode="count", rounds=1)).start()
        h.finish()
        self.assertEqual(h.mouse.clicks(), [("click", "left", 2, (100, 100))] * 2)

    def test_jitter_px_rerolled_every_click(self):
        h = RunnerHarness([step(500, 500, repeat=40, gap_ms=10)],
                          cfg(mode="count", rounds=1, jitter_px=10)).start()
        h.finish(timeout=10)
        pos = [e[3] for e in h.mouse.clicks()]
        self.assertEqual(len(pos), 40)
        self.assertGreater(len(set(pos)), 1)  # ถ้าสุ่มครั้งเดียวต่อจุด ทุกคลิกจะตรงกันหมด
        for x, y in pos:
            self.assertTrue(490 <= x <= 510 and 490 <= y <= 510, (x, y))

    def test_gap_respects_kill_switch(self):
        h = RunnerHarness([step(100, 100, repeat=5, gap_ms=5000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), ac.KILL_REASON)

    def test_time_deadline_inside_repeat(self):
        t0 = time.monotonic()
        h = RunnerHarness([step(100, 100, repeat=1000, gap_ms=50)], cfg(mode="time", minutes=0.3 / 60)).start()
        self.assertEqual(h.finish(), "ครบเวลาที่ตั้งไว้")
        self.assertLess(time.monotonic() - t0, 0.6)


class RepeatModelTests(unittest.TestCase):
    def test_validate_rejects_bad_repeat_and_gap(self):
        base = {"x": 10, "y": 10}
        for extra in [{"repeat": 0}, {"repeat": 1001}, {"repeat": 1.5}, {"repeat": True},
                      {"repeat": "3"}, {"gap_ms": 5}, {"gap_ms": 60001}, {"gap_ms": True},
                      {"gap_ms": 10.0}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                ac.validate_step(dict(base, **extra))

    def test_validate_bounds_ok(self):
        for r, g in [(1, 10), (1000, 60000)]:
            s = ac.validate_step({"x": 10, "y": 10, "repeat": r, "gap_ms": g})
            self.assertEqual((s["repeat"], s["gap_ms"]), (r, g))

    def test_old_profile_without_repeat_loads(self):
        old = {"version": 1,
               "steps": [{"x": 812, "y": 455, "type": "left", "delay_ms": 500, "hold_ms": 500}],
               "settings": {"mode": "count", "rounds": 10, "minutes": 5, "jitter_px": 3, "jitter_ms": 50},
               "defaults": {"type": "left", "delay_ms": 500}}
        steps, _, dflt = ac.parse_profile(old)
        self.assertEqual((steps[0]["repeat"], steps[0]["gap_ms"]), (1, 100))
        self.assertEqual(dflt["repeat"], 1)

    def test_defaults_repeat_validated(self):
        for bad in (0, 1001, 2.0, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ac.parse_profile({"defaults": {"repeat": bad}})
        self.assertEqual(ac.parse_profile({"defaults": {"repeat": 7}})[2]["repeat"], 7)

    def test_format_status(self):
        self.assertEqual(ac.format_status(4, 2, 1, 1), "รอบ 4 · จุด #2")
        self.assertEqual(ac.format_status(4, 2, 2, 3), "รอบ 4 · จุด #2 (2/3)")

    def test_step_row(self):
        self.assertEqual(ac.step_row(1, step(10, 20, "left", 500, 300)),
                         (1, 10, 20, ac.CLICK_LABEL["left"], 1, "-", "-", "500 ms"))
        self.assertEqual(ac.step_row(2, step(10, 20, "hold", 90000, 1500, repeat=3, gap_ms=250)),
                         (2, 10, 20, ac.CLICK_LABEL["hold"], 3, "250 ms", "1.5 วิ", "1 นาที 30 วิ"))


class RepeatAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "p.json")
        ac.messagebox.errors.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_then_parse_round_trip(self):
        steps = [step(812, 455, "hold", 500, 300, repeat=3, gap_ms=250),
                 step(10, 20, "double", 10, 0, repeat=1000, gap_ms=60000)]
        app = fake_app(steps)
        app.def_repeat.set(5)
        ac.filedialog.asksaveasfilename = lambda **k: self.path
        ac.App.save(app)
        self.assertEqual(ac.messagebox.errors, [])
        with open(self.path, encoding="utf-8") as f:
            got_steps, _, dflt = ac.parse_profile(json.load(f))
        self.assertEqual(got_steps, steps)
        self.assertEqual(dflt["repeat"], 5)

    def test_save_blocks_bad_default_repeat(self):
        app = fake_app([step(100, 100)])
        app.def_repeat.set(0)
        ac.filedialog.asksaveasfilename = lambda **k: self.path
        ac.App.save(app)
        self.assertEqual(len(ac.messagebox.errors), 1)
        self.assertFalse(os.path.exists(self.path))

    def test_load_old_file_and_sets_default_repeat(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"steps": [{"x": 50, "y": 60}], "defaults": {"type": "right", "delay_ms": 300}}, f)
        app = fake_app([])
        app.def_repeat.set(9)
        ac.filedialog.askopenfilename = lambda **k: self.path
        ac.App.load(app)
        self.assertEqual(app.steps, [step(50, 60, "left", 500, 500, repeat=1, gap_ms=100)])
        self.assertEqual(app.def_repeat.get(), 1)  # ไฟล์เก่าไม่มี -> 1

    def test_hotkey_add_uses_default_repeat(self):
        app = fake_app([])
        app.def_repeat.set(4)
        app.add_at(500, 500)
        self.assertEqual(app.steps[-1]["repeat"], 4)
        self.assertEqual(app.steps[-1]["gap_ms"], ac.DEFAULT_GAP_MS)

    def test_status_shows_k_of_n(self):
        app = fake_app([step(100, 100)])
        app.runner = types.SimpleNamespace(is_alive=lambda: True)
        app.q.put(("status", 2, 1, 2, 3))
        app._poll()
        self.assertEqual(app.status.get(), "รอบ 2 · จุด #1 (2/3)")


# ----------------------------------------------------------- time units
class TimeUnitTests(unittest.TestCase):
    def test_to_ms(self):
        cases = [("500", "ms", 500), ("1.5", "วินาที", 1500), ("0.5", "นาที", 30000),
                 ("0.29", "วินาที", 290),   # int() จะได้ 289
                 (" 2 ", "นาที", 120000), ("0", "ms", 0), ("1e3", "ms", 1000), (3, "วินาที", 3000),
                 ("0.0005", "วินาที", 0), ("10.4", "ms", 10), ("10.6", "ms", 11)]
        for value, unit, expect in cases:
            with self.subTest(value=value, unit=unit):
                self.assertEqual(ac.to_ms(value, unit), expect)
                self.assertIsInstance(ac.to_ms(value, unit), int)

    def test_to_ms_rejects(self):
        for value, unit in [("abc", "ms"), ("", "ms"), ("-1", "ms"), ("-0.5", "วินาที"),
                            ("nan", "ms"), ("inf", "วินาที"), ("1,5", "วินาที"), ("5", "ชม.")]:
            with self.subTest(value=value, unit=unit), self.assertRaises(ValueError):
                ac.to_ms(value, unit)

    def test_pick_unit(self):
        self.assertEqual(ac.pick_unit(120000), (2, "นาที"))
        self.assertEqual(ac.pick_unit(90000), (90, "วินาที"))
        self.assertEqual(ac.pick_unit(3000), (3, "วินาที"))
        self.assertEqual(ac.pick_unit(1500), (1500, "ms"))
        self.assertEqual(ac.pick_unit(500), (500, "ms"))
        self.assertEqual(ac.pick_unit(0), (0, "ms"))

    def test_pick_unit_round_trips(self):
        for ms in (0, 10, 500, 999, 1000, 1500, 60000, 90000, 86_400_000):
            self.assertEqual(ac.to_ms(*ac.pick_unit(ms)), ms)

    def test_format_duration(self):
        cases = [(0, "0 ms"), (500, "500 ms"), (999, "999 ms"), (1000, "1 วิ"), (1500, "1.5 วิ"),
                 (1234, "1.234 วิ"), (59999, "59.999 วิ"), (60000, "1 นาที"), (120000, "2 นาที"),
                 (90000, "1 นาที 30 วิ"), (90500, "1 นาที 30.5 วิ"), (60010, "1 นาที 0.01 วิ")]
        for ms, text in cases:
            with self.subTest(ms=ms):
                self.assertEqual(ac.format_duration(ms), text)

    def test_duration_ceiling_24h(self):
        top = ac.MAX_DURATION_MS
        self.assertEqual(top, 86_400_000)
        ok = ac.validate_step({"x": 10, "y": 10, "delay_ms": top, "hold_ms": top})
        self.assertEqual((ok["delay_ms"], ok["hold_ms"]), (top, top))
        for key in ("delay_ms", "hold_ms"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "24 ชม."):
                ac.validate_step({"x": 10, "y": 10, key: top + 1})
        with self.assertRaises(ValueError):
            ac.parse_profile({"defaults": {"delay_ms": top + 1}})

    def form(self, **kw):
        f = {"x": "100", "y": "200", "type": ac.CLICK_LABEL["left"], "repeat": "1",
             "delay_ms": "500", "delay_ms_unit": "ms", "hold_ms": "0", "hold_ms_unit": "ms",
             "gap_ms": "100", "gap_ms_unit": "ms"}
        f.update(kw)
        return f

    def test_step_from_form_converts_units(self):
        s = ac.step_from_form(self.form(delay_ms="1.5", delay_ms_unit="วินาที",
                                        gap_ms="0.29", gap_ms_unit="วินาที",
                                        hold_ms="0.5", hold_ms_unit="นาที", repeat="3"))
        self.assertEqual((s["delay_ms"], s["gap_ms"], s["hold_ms"], s["repeat"]), (1500, 290, 30000, 3))

    def test_step_from_form_errors_name_the_field(self):
        for kw, field in [({"x": "1.5"}, "X"), ({"repeat": "abc"}, "จำนวนครั้ง"),
                          ({"delay_ms": "abc"}, "รอหลังครั้งสุดท้าย"), ({"gap_ms": "-1"}, "เว้นระหว่างครั้ง")]:
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, field):
                ac.step_from_form(self.form(**kw))

    def test_rules_still_apply_after_conversion(self):
        s = ac.step_from_form(self.form(delay_ms="0.005", delay_ms_unit="วินาที"))  # = 5 ms
        with self.assertRaises(ValueError):
            ac.validate_step(s)
        s = ac.step_from_form(self.form(delay_ms="1441", delay_ms_unit="นาที"))      # > 24 ชม.
        with self.assertRaises(ValueError):
            ac.validate_step(s)

    def test_default_delay_with_units(self):
        app = fake_app([])
        app.def_delay.set("1.5")
        app.def_delay_unit.set("วินาที")
        app.add_at(500, 500)
        self.assertEqual(app.steps[-1]["delay_ms"], 1500)

    def test_default_delay_bad_input_reports_status(self):
        app = fake_app([])
        app.def_delay.set("abc")
        app.add_at(500, 500)
        self.assertEqual(app.steps, [])
        self.assertIn("เพิ่มจุดไม่ได้", app.status.get())

    def test_save_stores_ms_and_load_picks_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            ac.filedialog.asksaveasfilename = lambda **k: path
            ac.filedialog.askopenfilename = lambda **k: path
            ac.messagebox.errors.clear()
            app = fake_app([step(100, 100, delay_ms=90000)])
            app.def_delay.set("0.5")
            app.def_delay_unit.set("นาที")
            ac.App.save(app)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["defaults"]["delay_ms"], 30000)  # ไฟล์ยังเป็น ms
            self.assertEqual(data["steps"][0]["delay_ms"], 90000)
            other = fake_app([])
            ac.App.load(other)
            self.assertEqual((other.def_delay.get(), other.def_delay_unit.get()), (30, "วินาที"))

    def test_save_bad_default_delay_shows_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            ac.filedialog.asksaveasfilename = lambda **k: path
            ac.messagebox.errors.clear()
            app = fake_app([step(100, 100)])
            app.def_delay.set("x")
            ac.App.save(app)
            self.assertEqual(len(ac.messagebox.errors), 1)
            self.assertFalse(os.path.exists(path))


# ------------------------------------------------------ hover / mouse nudge
def kinds(mouse, keep=("move", "nudge", "click", "press", "release")):
    return [e[0] for e in mouse.events if e[0] in keep]


class HoverNudgeTests(unittest.TestCase):
    def test_nudge_after_move_before_click_every_time(self):
        steps = [step(100, 100, repeat=2, gap_ms=10), step(200, 200, "hold", hold_ms=10)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=1)).start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(kinds(h.mouse), ["move", "nudge", "click",
                                          "move", "nudge", "click",      # repeat ครั้งที่ 2 ก็ต้อง nudge
                                          "move", "nudge", "press", "release"])
        for kind, pos, _ in h.mouse.events:
            if kind == "nudge":
                self.assertIn(pos, [(100, 100), (200, 200)])  # nudge ตอนเมาส์อยู่ที่จุดแล้ว

    def test_hover_waited_before_click(self):
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1, hover_ms=200)).start()
        h.finish()
        t = {kind: ts for kind, _, ts in h.mouse.events}
        self.assertGreaterEqual(t["click"] - t["nudge"], 0.19)

    def test_hover_applies_to_each_repeat(self):
        h = RunnerHarness([step(100, 100, repeat=3, gap_ms=10)],
                          cfg(mode="count", rounds=1, hover_ms=100)).start()
        h.finish()
        nudges = [ts for kind, _, ts in h.mouse.events if kind == "nudge"]
        clicks = [ts for kind, _, ts in h.mouse.events if kind == "click"]
        self.assertEqual(len(clicks), 3)
        for n, c in zip(nudges, clicks):
            self.assertGreaterEqual(c - n, 0.09)

    def test_stop_during_long_hover(self):
        h = RunnerHarness([step(100, 100)], cfg(hover_ms=30000)).start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(h.mouse)))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")
        self.assertEqual(h.mouse.clicks(), [])  # ยังไม่ทันคลิก

    def test_kill_switch_during_hover(self):
        h = RunnerHarness([step(100, 100)], cfg(hover_ms=30000)).start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(h.mouse)))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), ac.KILL_REASON)
        self.assertEqual(h.mouse.clicks(), [])

    def test_hold_not_pressed_if_stopped_during_hover(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=10)], cfg(hover_ms=30000)).start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(h.mouse)))
        h.runner.stop()
        h.finish(timeout=0.3)
        self.assertEqual(h.mouse.log, [])
        self.assertEqual(h.mouse.pressed, set())

    def test_nudge_error_does_not_kill_runner(self):
        def broken():
            raise OSError("SendInput failed")
        steps = [step(100, 100), step(200, 200)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=2), nudge=broken).start()
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        self.assertEqual(len(h.mouse.clicks()), 4)

    def test_position_restored_if_nudge_drifts(self):
        mouse = FakeMouse()

        def drifting():  # จำลอง Enhance pointer precision: +1 ไป 2px แต่ -1 กลับแค่ 1px
            x, y = mouse.position
            mouse.position = (x + 1, y)
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1), mouse=mouse,
                          nudge=drifting).start()
        h.finish()
        self.assertEqual(h.mouse.clicks(), [("click", "left", 1, (100, 100))])

    def test_late_drift_during_hover_is_corrected(self):
        # SendInput เข้าคิวแบบ async: ตำแหน่งอาจเพี้ยนทีหลัง ระหว่างที่รอ hover อยู่
        mouse = FakeMouse()
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1, hover_ms=200), mouse=mouse)
        h.start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(mouse)))
        mouse.position = (101, 100)
        h.finish()
        self.assertEqual(mouse.clicks(), [("click", "left", 1, (100, 100))])

    def test_default_nudge_is_sendinput(self):
        r = ac.Runner([step(1, 1)], cfg(), FakeMouse(), lambda *a: None, lambda r: None)
        self.assertIs(r.nudge, ac.nudge_mouse)

    def test_nudge_mouse_skips_on_non_windows(self):
        orig = ac.sys.platform
        ac.sys.platform = "linux"
        try:
            self.assertIsNone(ac.nudge_mouse())  # ไม่ raise และไม่แตะ ctypes.windll
        finally:
            ac.sys.platform = orig

    def test_input_struct_size_matches_win32(self):
        # SendInput ต้องได้ cbSize ตรงกับ sizeof(INPUT) ของ Windows ไม่งั้นจะ fail เงียบๆ
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(ac._INPUT), expected)


class HoverSettingTests(unittest.TestCase):
    def test_old_profile_gets_default_hover(self):
        _, st, _ = ac.parse_profile({"settings": {"mode": "loop", "jitter_px": 0}})
        self.assertEqual(st["hover_ms"], 50)

    def test_validate_range(self):
        for bad in (-1, 1001, 1.5, True, "50", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ac.parse_profile({"settings": {"hover_ms": bad}})
        for ok in (0, 1000):
            self.assertEqual(ac.parse_profile({"settings": {"hover_ms": ok}})[1]["hover_ms"], ok)

    def test_ui_clamps(self):
        app = fake_app([])
        for v, expect in [(5000, 1000), (-5, 0), ("x", 50), (120, 120)]:
            app.hover.set(v)
            self.assertEqual(app._cfg()["hover_ms"], expect)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            ac.filedialog.asksaveasfilename = lambda **k: path
            ac.filedialog.askopenfilename = lambda **k: path
            ac.messagebox.errors.clear()
            app = fake_app([step(100, 100)])
            app.hover.set(250)
            ac.App.save(app)
            other = fake_app([])
            ac.App.load(other)
            self.assertEqual(ac.messagebox.errors, [])
            self.assertEqual(other.hover.get(), 250)


# ---------------------------------------------------------------- hotkeys
VK_F6, VK_F7, VK_F8, VK_1, VK_A = 0x75, 0x76, 0x77, 0x31, 0x41
VK_LSHIFT, VK_RSHIFT, VK_LCTRL, VK_RCTRL, VK_LALT = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4


def SET_ONLY():
    """read_mods ที่ "อ่านไม่ได้" บังคับให้ matcher ใช้ set self.down
    ต้อง inject เสมอ ไม่งั้นรันเทสต์บน Windows จะไปอ่านสถานะคีย์บอร์ดจริงของเครื่อง"""
    return None


def keycode(vk):
    """แบบ pynput KeyCode: มี .vk ตรงๆ"""
    return types.SimpleNamespace(vk=vk)


def special_key(vk):
    """แบบ pynput Key.xxx (Enum): vk อยู่ที่ .value.vk"""
    return types.SimpleNamespace(value=types.SimpleNamespace(vk=vk))


def hk(vk, *mods):
    return {"mods": list(mods), "vk": vk}


class HotkeyTextTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(ac.hotkey_to_text(hk(VK_F6)), "F6")
        self.assertEqual(ac.hotkey_to_text(hk(VK_1, "shift", "ctrl")), "Ctrl+Shift+1")
        self.assertEqual(ac.hotkey_to_text(hk(VK_A, "alt")), "Alt+A")
        self.assertEqual(ac.hotkey_to_text(hk(0x65)), "Num 5")
        self.assertEqual(ac.hotkey_to_text(hk(0x87)), "F24")
        self.assertEqual(ac.hotkey_to_text(hk(0xFE)), "VK 0xFE")

    def test_labels_follow_hotkeys(self):
        keys = ac.assign_hotkey(ac.DEFAULT_HOTKEYS, "toggle", hk(VK_1, "ctrl", "shift"))
        lb = ac.hotkey_labels(keys)
        self.assertEqual(lb["start"], "▶ เริ่ม (Ctrl+Shift+1)")
        self.assertEqual(lb["stop"], "■ หยุด (Ctrl+Shift+1)")
        self.assertEqual(lb["markers"], "แสดงหมุด (F7)")
        self.assertIn("Ctrl+Shift+1 = เริ่ม/หยุด", lb["header"])
        self.assertIn("F8", lb["no_steps"])


class ParseHotkeyTests(unittest.TestCase):
    def test_normalizes_mod_order_and_dupes(self):
        self.assertEqual(ac.parse_hotkey({"vk": VK_1, "mods": ["shift", "ctrl", "shift"]}),
                         hk(VK_1, "ctrl", "shift"))
        self.assertEqual(ac.parse_hotkey({"vk": VK_F6}), hk(VK_F6))

    def test_rejects(self):
        bad = [None, [], {"mods": []}, {"vk": "F6"}, {"vk": True}, {"vk": 0}, {"vk": 300},
               {"vk": VK_F6, "mods": ["win"]}, {"vk": VK_F6, "mods": "ctrl"},
               {"vk": 0x1B}, {"vk": 0x1B, "mods": ["ctrl"]},  # Esc
               {"vk": 0x5B},                                  # Win
               {"vk": 0x10}, {"vk": VK_LSHIFT}, {"vk": VK_RCTRL, "mods": ["shift"]}, {"vk": VK_LALT}]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(ValueError):
                ac.parse_hotkey(d)

    def test_validate_defaults(self):
        self.assertEqual(ac.validate_hotkeys(ac.DEFAULT_HOTKEYS), ac.DEFAULT_HOTKEYS)
        self.assertEqual(ac.DEFAULT_HOTKEYS["markers"], hk(VK_F7))

    def test_validate_rejects_duplicates(self):
        d = dict(ac.DEFAULT_HOTKEYS, add=hk(VK_F6))
        with self.assertRaisesRegex(ValueError, "ซ้ำ"):
            ac.validate_hotkeys(d)
        # mods ลำดับต่างกันก็นับว่าซ้ำ
        d = dict(ac.DEFAULT_HOTKEYS, add=hk(VK_1, "ctrl", "shift"), markers=hk(VK_1, "shift", "ctrl"))
        with self.assertRaises(ValueError):
            ac.validate_hotkeys(d)

    def test_validate_requires_exact_actions(self):
        with self.assertRaises(ValueError):
            ac.validate_hotkeys({"toggle": hk(VK_F6), "add": hk(VK_F8)})
        with self.assertRaises(ValueError):
            ac.validate_hotkeys(dict(ac.DEFAULT_HOTKEYS, extra=hk(VK_A)))

    def test_assign_hotkey(self):
        base = {a: dict(v) for a, v in ac.DEFAULT_HOTKEYS.items()}
        new = ac.assign_hotkey(base, "add", hk(VK_A, "ctrl"))
        self.assertEqual(new["add"], hk(VK_A, "ctrl"))
        self.assertEqual(base, ac.DEFAULT_HOTKEYS)  # ไม่แก้ของเดิม
        with self.assertRaisesRegex(ValueError, "ใช้กับ"):
            ac.assign_hotkey(base, "add", hk(VK_F6))
        # ตั้งปุ่มเดิมให้หน้าที่เดิมได้ ไม่นับว่าซ้ำ
        self.assertEqual(ac.assign_hotkey(base, "toggle", hk(VK_F6)), base)

    def test_key_to_vk(self):
        self.assertEqual(ac.key_to_vk(keycode(VK_A)), VK_A)
        self.assertEqual(ac.key_to_vk(special_key(VK_F6)), VK_F6)
        self.assertIsNone(ac.key_to_vk(types.SimpleNamespace(vk=None)))
        self.assertIsNone(ac.key_to_vk(object()))


class HotkeyMatcherTests(unittest.TestCase):
    """โหมด fallback: อ่าน modifier จาก set self.down (เหมือนตอนไม่ใช่ Windows)"""

    def setUp(self):
        keys = ac.assign_hotkey(ac.DEFAULT_HOTKEYS, "add", hk(VK_1, "ctrl", "shift"))
        self.m = ac.HotkeyMatcher(keys, read_mods=SET_ONLY)

    def test_autorepeat_triggers_once(self):
        got = [self.m.press(VK_F6) for _ in range(10)]  # กดค้าง: Windows ส่ง press ซ้ำๆ
        self.assertEqual(got, ["toggle"] + [None] * 9)
        self.m.release(VK_F6)
        self.assertEqual(self.m.press(VK_F6), "toggle")

    def test_combo_needs_modifiers_first(self):
        self.assertIsNone(self.m.press(VK_1))  # กด 1 ก่อน
        self.assertIsNone(self.m.press(VK_LCTRL))
        self.assertIsNone(self.m.press(VK_LSHIFT))
        self.m.release(VK_1)
        self.assertEqual(self.m.press(VK_1), "add")

    def test_combo_autorepeat_once(self):
        self.m.press(VK_LCTRL)
        self.m.press(VK_LSHIFT)
        self.assertEqual([self.m.press(VK_1) for _ in range(5)], ["add"] + [None] * 4)

    def test_left_and_right_modifiers(self):
        for ctrl in (VK_LCTRL, VK_RCTRL, 0x11):
            for shift in (VK_LSHIFT, VK_RSHIFT, 0x10):
                with self.subTest(ctrl=ctrl, shift=shift):
                    m = ac.HotkeyMatcher(ac.assign_hotkey(ac.DEFAULT_HOTKEYS, "add",
                                                          hk(VK_1, "ctrl", "shift")),
                                         read_mods=SET_ONLY)
                    m.press(ctrl)
                    m.press(shift)
                    self.assertEqual(m.press(VK_1), "add")

    def test_modifiers_must_match_exactly(self):
        self.m.press(VK_LCTRL)
        self.assertIsNone(self.m.press(VK_F6))  # Ctrl+F6 ไม่ใช่ F6
        self.m.release(VK_F6)
        self.m.release(VK_LCTRL)
        self.assertIsNone(self.m.press(VK_1))   # 1 เฉยๆ ไม่ใช่ Ctrl+Shift+1

    def test_paused_never_triggers(self):
        self.m.paused = True
        self.assertIsNone(self.m.press(VK_F6))
        self.assertEqual(self.m.last_combo, hk(VK_F6))  # แต่ยังจับคีย์ให้ dialog ได้
        self.m.paused = False
        self.assertIsNone(self.m.press(VK_F6))  # ยังกดค้างจากตอน pause = autorepeat ไม่ trigger
        self.m.release(VK_F6)
        self.assertEqual(self.m.press(VK_F6), "toggle")

    def test_last_combo(self):
        self.m.press(VK_RSHIFT)
        self.assertIsNone(self.m.last_combo)  # modifier เดี่ยวไม่นับเป็นคอมโบ
        self.m.press(VK_A)
        self.assertEqual(self.m.last_combo, hk(VK_A, "shift"))
        self.m.press(VK_A)
        self.assertIsNone(self.m.last_combo)  # autorepeat
        self.m.press(None)
        self.assertIsNone(self.m.last_combo)


class AsyncModifierTests(unittest.TestCase):
    """โหมดปกติบน Windows: modifier อ่านจากสถานะจริง (GetAsyncKeyState) ไม่ใช่จาก event"""

    def setUp(self):
        self.held = set()  # จำลองสถานะ modifier ที่กดอยู่จริงบนเครื่อง
        keys = ac.assign_hotkey(ac.DEFAULT_HOTKEYS, "add", hk(VK_1, "ctrl", "shift"))
        self.m = ac.HotkeyMatcher(keys, read_mods=lambda: set(self.held))

    def test_lost_shift_release_does_not_stick(self):
        self.held.add("shift")
        self.m.press(VK_LSHIFT)
        # ปล่อย Shift แต่ event release หาย (เช่น Win+L / UAC) set ยังมี LSHIFT ค้างอยู่
        self.held.discard("shift")
        self.assertIn(VK_LSHIFT, self.m.down)
        self.assertEqual(self.m.press(VK_F6), "toggle")  # ไม่ใช่ Shift+F6
        self.assertEqual(self.m.last_combo, hk(VK_F6))

    def test_real_shift_held_blocks_plain_hotkey(self):
        self.held.add("shift")
        self.assertIsNone(self.m.press(VK_F6))  # Shift+F6 ไม่ได้ตั้งไว้

    def test_combo_from_real_state_without_modifier_events(self):
        self.held.update({"ctrl", "shift"})
        self.assertEqual(self.m.press(VK_1), "add")

    def test_autorepeat_still_uses_down_set(self):
        self.assertEqual([self.m.press(VK_F6) for _ in range(5)], ["toggle"] + [None] * 4)
        self.m.release(VK_F6)
        self.assertEqual(self.m.press(VK_F6), "toggle")

    def test_paused_still_never_triggers(self):
        self.m.paused = True
        self.held.update({"ctrl", "shift"})
        self.assertIsNone(self.m.press(VK_1))
        self.assertEqual(self.m.last_combo, hk(VK_1, "ctrl", "shift"))

    def test_reader_error_falls_back_to_set(self):
        def broken():
            raise OSError("boom")
        m = ac.HotkeyMatcher(ac.DEFAULT_HOTKEYS, read_mods=broken)
        m.press(VK_LCTRL)
        self.assertIsNone(m.press(VK_F6))  # set บอกว่า Ctrl ค้าง = Ctrl+F6
        m.release(VK_F6)
        m.release(VK_LCTRL)
        self.assertEqual(m.press(VK_F6), "toggle")

    def test_default_reader_is_async(self):
        self.assertIs(ac.HotkeyMatcher(ac.DEFAULT_HOTKEYS).read_mods, ac.read_modifiers_async)

    def test_read_modifiers_async_non_windows(self):
        orig = ac.sys.platform
        ac.sys.platform = "linux"
        try:
            self.assertIsNone(ac.read_modifiers_async())
        finally:
            ac.sys.platform = orig

    @unittest.skipUnless(sys.platform == "win32", "ต้องใช้ user32 จริง")
    def test_read_modifiers_async_windows_returns_set(self):
        mods = ac.read_modifiers_async()
        self.assertIsInstance(mods, set)
        self.assertLessEqual(mods, {"ctrl", "alt", "shift"})


class HotkeySettingsFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "AutoClicker", "settings.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_missing_file_uses_defaults_silently(self):
        self.assertEqual(ac.load_hotkeys(self.path), (ac.DEFAULT_HOTKEYS, None))

    def test_round_trip_atomic(self):
        keys = ac.assign_hotkey(ac.DEFAULT_HOTKEYS, "toggle", hk(VK_1, "ctrl", "shift"))
        ac.save_hotkeys(self.path, keys)  # สร้างโฟลเดอร์ให้เอง
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["settings.json"])  # ไม่มี .tmp ค้าง
        self.assertEqual(ac.load_hotkeys(self.path), (keys, None))

    def test_save_rejects_invalid(self):
        with self.assertRaises(ValueError):
            ac.save_hotkeys(self.path, dict(ac.DEFAULT_HOTKEYS, add=hk(VK_F6)))
        self.assertFalse(os.path.exists(self.path))

    def test_broken_files_fall_back_with_warning(self):
        cases = ['{"hotkeys": {"toggle": ', "[]", '{"hotkeys": []}',
                 json.dumps({"hotkeys": {"toggle": hk(VK_F8)}}),        # ซ้ำกับ add ที่เป็นค่าเริ่มต้น
                 json.dumps({"hotkeys": {"toggle": hk(VK_LSHIFT)}}),    # modifier เดี่ยว
                 json.dumps({"hotkeys": {"bogus": hk(VK_A)}}), "\xff\xfe"]
        for text in cases:
            with self.subTest(text=text):
                self._write(text)
                keys, warn = ac.load_hotkeys(self.path)
                self.assertEqual(keys, ac.DEFAULT_HOTKEYS)
                self.assertTrue(warn)

    def test_partial_file_fills_defaults(self):
        self._write(json.dumps({"hotkeys": {"markers": hk(VK_A, "alt")}}))
        keys, warn = ac.load_hotkeys(self.path)
        self.assertIsNone(warn)
        self.assertEqual(keys["markers"], hk(VK_A, "alt"))
        self.assertEqual(keys["toggle"], ac.DEFAULT_HOTKEYS["toggle"])

    def test_settings_path_under_appdata(self):
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.tmp.name
        try:
            self.assertEqual(ac.settings_path(),
                             os.path.join(self.tmp.name, "AutoClicker", "settings.json"))
        finally:
            if old is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = old


class FakeListener:
    instances = []

    def __init__(self, on_press=None, on_release=None):
        self.on_press, self.on_release = on_press, on_release
        self.running = False
        self.daemon = False
        FakeListener.instances.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def join(self, timeout=None):
        pass


class HotkeyAppTests(unittest.TestCase):
    def setUp(self):
        self._orig_listener = ac.keyboard.Listener
        self._orig_read = ac.read_modifiers_async
        ac.keyboard.Listener = FakeListener
        ac.read_modifiers_async = SET_ONLY  # matcher ที่ App สร้างเองต้องไม่อ่านคีย์บอร์ดจริง
        FakeListener.instances = []
        self.tmp = tempfile.TemporaryDirectory()
        self.app = fake_app([step(100, 100)])
        self.app.settings_file = os.path.join(self.tmp.name, "AutoClicker", "settings.json")

    def tearDown(self):
        ac.keyboard.Listener = self._orig_listener
        ac.read_modifiers_async = self._orig_read
        self.tmp.cleanup()

    def test_press_goes_through_queue(self):
        self.app.mouse.position = (321, 654)
        self.app._on_press(special_key(VK_F6))
        self.app._on_press(keycode(VK_F8))
        self.assertEqual(self.app.q.get_nowait(), ("toggle",))
        self.assertEqual(self.app.q.get_nowait(), ("add", 321, 654))
        self.assertTrue(self.app.q.empty())

    def test_release_clears_autorepeat(self):
        self.app._on_press(keycode(VK_F6))
        self.app._on_press(keycode(VK_F6))
        self.app._on_release(keycode(VK_F6))
        self.app._on_press(keycode(VK_F6))
        self.assertEqual([self.app.q.get_nowait() for _ in range(2)], [("toggle",), ("toggle",)])
        self.assertTrue(self.app.q.empty())

    def test_paused_sends_capture_not_action(self):
        self.app.matcher.paused = True
        self.app._on_press(keycode(VK_LCTRL))
        self.app._on_press(keycode(VK_F6))
        self.assertEqual(self.app.q.get_nowait(), ("captured", hk(VK_F6, "ctrl")))
        self.assertTrue(self.app.q.empty())

    def test_captured_routed_to_dialog(self):
        got = []
        self.app.hotkey_dialog = types.SimpleNamespace(on_captured=got.append)
        self.app.q.put(("captured", hk(VK_A)))
        self.app._poll()
        self.assertEqual(got, [hk(VK_A)])

    def test_apply_restarts_single_listener_and_updates_labels(self):
        self.app._start_listener()
        keys = ac.assign_hotkey(self.app.hotkeys, "toggle", hk(VK_1, "ctrl", "shift"))
        self.app.apply_hotkeys(keys)
        self.app.apply_hotkeys(ac.assign_hotkey(keys, "markers", hk(VK_A, "alt")))
        running = [ls for ls in FakeListener.instances if ls.running]
        self.assertEqual(len(FakeListener.instances), 3)
        self.assertEqual(len(running), 1)
        self.assertIs(running[0], self.app.kb)
        self.assertEqual(self.app.run_btn.text, "▶ เริ่ม (Ctrl+Shift+1)")
        self.assertEqual(self.app.markers_chk.text, "แสดงหมุด (Alt+A)")
        self.assertIn("Ctrl+Shift+1", self.app.hint_lbl.text)
        # listener ตัวใหม่ใช้ปุ่มใหม่แล้ว
        self.app.matcher.press(VK_LCTRL)
        self.app.matcher.press(VK_LSHIFT)
        self.assertEqual(self.app.matcher.press(VK_1), "toggle")
        self.assertEqual(ac.load_hotkeys(self.app.settings_file)[0]["markers"], hk(VK_A, "alt"))

    def test_apply_rejects_duplicates_and_keeps_old(self):
        self.app._start_listener()
        old_kb = self.app.kb
        with self.assertRaises(ValueError):
            self.app.apply_hotkeys(dict(self.app.hotkeys, add=hk(VK_F6)))
        self.assertIs(self.app.kb, old_kb)
        self.assertEqual(self.app.hotkeys, ac.DEFAULT_HOTKEYS)
        self.assertFalse(os.path.exists(self.app.settings_file))

    def test_run_button_text_follows_run_state(self):
        ac.get_virtual_rect, orig_rect = (lambda: None), ac.get_virtual_rect
        ac.Runner, orig_runner = (lambda *a, **k: types.SimpleNamespace(start=lambda: None)), ac.Runner
        try:
            self.app.toggle()
            self.assertEqual(self.app.run_btn.text, "■ หยุด (F6)")
            self.app.q.put(("done", "หยุดโดยผู้ใช้"))
            self.app._poll()
            self.assertEqual(self.app.run_btn.text, "▶ เริ่ม (F6)")
        finally:
            ac.get_virtual_rect, ac.Runner = orig_rect, orig_runner


class HotkeyDialogLogicTests(unittest.TestCase):
    """เทสต์ logic ใน HotkeyDialog โดยข้าม __init__ (ไม่สร้าง Tk)"""

    def setUp(self):
        d = ac.HotkeyDialog.__new__(ac.HotkeyDialog)
        d.work = {a: dict(v) for a, v in ac.DEFAULT_HOTKEYS.items()}
        d.capturing = None
        d.err = FakeVar("")
        d.buttons = {a: FakeWidget() for a in ac.HOTKEY_ACTIONS}
        d.focus_set = lambda: None
        self.d = d

    def test_capture_shows_prompt_then_assigns(self):
        self.d._capture("add")
        self.assertEqual(self.d.buttons["add"].text, ac.HotkeyDialog.PROMPT)
        self.d.on_captured(hk(VK_1, "ctrl", "shift"))
        self.assertEqual(self.d.work["add"], hk(VK_1, "ctrl", "shift"))
        self.assertEqual(self.d.buttons["add"].text, "Ctrl+Shift+1")
        self.assertIsNone(self.d.capturing)

    def test_escape_cancels(self):
        self.d._capture("toggle")
        self.d.on_captured(hk(0x1B))
        self.assertEqual(self.d.work["toggle"], hk(VK_F6))
        self.assertEqual(self.d.buttons["toggle"].text, "F6")
        self.assertEqual(self.d.err.get(), "")

    def test_duplicate_shows_error_and_keeps_old(self):
        self.d._capture("markers")
        self.d.on_captured(hk(VK_F8))
        self.assertEqual(self.d.work["markers"], hk(VK_F7))
        self.assertIn("ใช้กับ", self.d.err.get())

    def test_ignores_keys_when_not_capturing(self):
        self.d.on_captured(hk(VK_A))
        self.assertEqual(self.d.work, ac.DEFAULT_HOTKEYS)

    def test_reset(self):
        self.d.work["toggle"] = hk(VK_A)
        self.d._reset()
        self.assertEqual(self.d.work, ac.DEFAULT_HOTKEYS)


if __name__ == "__main__":
    unittest.main()
