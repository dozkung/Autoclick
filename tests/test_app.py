"""เทสต์ App ด้วย FakeApp (stub tkinter/pynput ไม่ต้องมีจอ)"""

import json
import os
import tempfile
import types
import unittest

import support  # ตั้ง sys.path ให้ import autoclicker ได้

support.install_stubs()  # ต้องมาก่อน import module ที่ใช้ tkinter/pynput

from autoclicker import (
    constants,
    model,
)
from autoclicker import hotkeys as hotkeys_mod
from autoclicker import markers as markers_mod
from autoclicker.ui import app as app_mod
from support import SET_ONLY, VK_1, VK_A, VK_F6, VK_F8, VK_LCTRL, VK_LSHIFT, hk, keycode, special_key, step
from ui_support import FakeListener, fake_app


class LoadTests(unittest.TestCase):
    """เรียก App.load กับ object ปลอม เพื่อเช็กว่าไฟล์พังแล้วข้อมูลเดิมไม่หาย"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = [step(100, 100), step(200, 200, "right")]
        self.app = fake_app(self.original)
        app_mod.messagebox.errors.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _load(self, text):
        path = os.path.join(self.tmp.name, "p.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        app_mod.filedialog.askopenfilename = lambda **k: path
        app_mod.App.load(self.app)

    def test_broken_json_keeps_steps(self):
        self._load('{"steps": [{"x": 1')
        self.assertEqual(self.app.steps, self.original)
        self.assertEqual(len(app_mod.messagebox.errors), 1)

    def test_one_bad_step_keeps_steps(self):
        self._load(json.dumps({"steps": [{"x": 50, "y": 50}, {"x": 60}]}))
        self.assertEqual(self.app.steps, self.original)

    def test_bad_settings_keeps_everything(self):
        self._load(json.dumps({"steps": [{"x": 50, "y": 50}], "settings": {"rounds": "abc"}}))
        self.assertEqual(self.app.steps, self.original)
        self.assertEqual(self.app.rounds.get(), 10)

    def test_good_file_replaces(self):
        self._load(
            json.dumps(
                {
                    "version": 1,
                    "steps": [{"x": 812, "y": 455, "type": "hold", "delay_ms": 500, "hold_ms": 300}],
                    "settings": {"mode": "count", "rounds": 3, "minutes": 2, "jitter_px": 5, "jitter_ms": 50},
                    "defaults": {"type": "right", "delay_ms": 250},
                }
            )
        )
        self.assertEqual(self.app.steps, [step(812, 455, "hold", 500, 300)])
        self.assertEqual(self.app.mode.get(), "count")
        self.assertEqual(self.app.rounds.get(), 3)
        self.assertEqual(self.app.jit_px.get(), 5)
        self.assertEqual(self.app.def_type.get(), constants.CLICK_LABEL["right"])
        self.assertEqual(self.app.def_delay.get(), 250)
        self.assertEqual(app_mod.messagebox.errors, [])

    def test_refuses_while_running(self):
        self.app.runner = types.SimpleNamespace(is_alive=lambda: True)
        self._load(json.dumps({"steps": []}))
        self.assertEqual(self.app.steps, self.original)

    def test_corner_step_loads_so_user_can_fix_it(self):
        self._load(json.dumps({"steps": [{"x": 0, "y": 0}]}))
        self.assertEqual(self.app.steps, [step(0, 0, "left", 500, 500)])
        self.assertEqual(app_mod.messagebox.errors, [])


class SaveTests(unittest.TestCase):
    """ไฟล์ที่ save ออกไปต้องผ่าน parse_profile เสมอ ถ้าไม่ผ่านต้องไม่เขียนไฟล์"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "out.json")
        app_mod.filedialog.asksaveasfilename = lambda **k: self.path
        app_mod.messagebox.errors.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def _save_and_reparse(self, app):
        app_mod.App.save(app)
        self.assertEqual(app_mod.messagebox.errors, [])
        with open(self.path, encoding="utf-8") as f:
            return model.parse_profile(json.load(f))

    def test_round_trip(self):
        steps = [step(812, 455, "hold", 500, 300), step(10, 20, "double", 10, 0)]
        app = fake_app(steps)
        app.mode.set("count")
        app.rounds.set(3)
        app.def_type.set(constants.CLICK_LABEL["right"])
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
        for mode in constants.MODES:
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
        app_mod.App.save(app)
        self.assertEqual(len(app_mod.messagebox.errors), 1)
        self.assertFalse(os.path.exists(self.path))


class ToggleTests(unittest.TestCase):
    """toggle() ต้องไม่เริ่มถ้ามีจุดนอกจอหรือในโซน kill switch"""

    def setUp(self):
        self._orig = app_mod.get_virtual_rect, app_mod.get_virtual_origin, app_mod.Runner
        app_mod.get_virtual_rect = lambda: (0, 0, 1920, 1080)
        app_mod.get_virtual_origin = lambda: (0, 0)
        self.started = []
        app_mod.Runner = lambda *a, **k: self.started.append(a) or types.SimpleNamespace(start=lambda: None)

    def tearDown(self):
        app_mod.get_virtual_rect, app_mod.get_virtual_origin, app_mod.Runner = self._orig

    def _toggle(self, steps):
        app = fake_app(steps)
        app_mod.App.toggle(app)
        return app.status.get()

    def test_out_of_screen_refuses(self):
        self.assertEqual(self._toggle([step(100, 100), step(2500, 100)]), "จุด #2 อยู่นอกจอ (ถอดจอออก?)")
        self.assertEqual(self.started, [])

    def test_corner_refuses(self):
        self.assertIn("kill switch", self._toggle([step(0, 0)]))
        self.assertEqual(self.started, [])

    def test_skip_screen_check_when_rect_unknown(self):
        app_mod.get_virtual_rect = lambda: None
        self._toggle([step(5000, 5000)])
        self.assertEqual(len(self.started), 1)

    def test_valid_steps_start(self):
        self.assertEqual(self._toggle([step(100, 100)]), "กำลังรัน…")
        self.assertEqual(len(self.started), 1)


class MarkerAppTests(unittest.TestCase):
    def setUp(self):
        self._orig = app_mod.get_virtual_rect, app_mod.get_virtual_origin, app_mod.Runner
        app_mod.get_virtual_rect = lambda: (0, 0, 1920, 1080)
        app_mod.get_virtual_origin = lambda: (0, 0)
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

        app_mod.Runner = StubRunner

    def tearDown(self):
        app_mod.get_virtual_rect, app_mod.get_virtual_origin, app_mod.Runner = self._orig

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


class RepeatAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "p.json")
        app_mod.messagebox.errors.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_then_parse_round_trip(self):
        steps = [
            step(812, 455, "hold", 500, 300, repeat=3, gap_ms=250),
            step(10, 20, "double", 10, 0, repeat=1000, gap_ms=60000),
        ]
        app = fake_app(steps)
        app.def_repeat.set(5)
        app_mod.filedialog.asksaveasfilename = lambda **k: self.path
        app_mod.App.save(app)
        self.assertEqual(app_mod.messagebox.errors, [])
        with open(self.path, encoding="utf-8") as f:
            got_steps, _, dflt = model.parse_profile(json.load(f))
        self.assertEqual(got_steps, steps)
        self.assertEqual(dflt["repeat"], 5)

    def test_save_blocks_bad_default_repeat(self):
        app = fake_app([step(100, 100)])
        app.def_repeat.set(0)
        app_mod.filedialog.asksaveasfilename = lambda **k: self.path
        app_mod.App.save(app)
        self.assertEqual(len(app_mod.messagebox.errors), 1)
        self.assertFalse(os.path.exists(self.path))

    def test_load_old_file_and_sets_default_repeat(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"steps": [{"x": 50, "y": 60}], "defaults": {"type": "right", "delay_ms": 300}}, f)
        app = fake_app([])
        app.def_repeat.set(9)
        app_mod.filedialog.askopenfilename = lambda **k: self.path
        app_mod.App.load(app)
        self.assertEqual(app.steps, [step(50, 60, "left", 500, 500, repeat=1, gap_ms=100)])
        self.assertEqual(app.def_repeat.get(), 1)  # ไฟล์เก่าไม่มี -> 1

    def test_hotkey_add_uses_default_repeat(self):
        app = fake_app([])
        app.def_repeat.set(4)
        app.add_at(500, 500)
        self.assertEqual(app.steps[-1]["repeat"], 4)
        self.assertEqual(app.steps[-1]["gap_ms"], constants.DEFAULT_GAP_MS)

    def test_status_shows_k_of_n(self):
        app = fake_app([step(100, 100)])
        app.runner = types.SimpleNamespace(is_alive=lambda: True)
        app.q.put(("status", 2, 1, 2, 3))
        app._poll()
        self.assertEqual(app.status.get(), "รอบ 2 · จุด #1 (2/3)")


class HotkeyAppTests(unittest.TestCase):
    def setUp(self):
        self._orig_listener = app_mod.keyboard.Listener
        self._orig_read = hotkeys_mod.read_modifiers_async
        app_mod.keyboard.Listener = FakeListener
        hotkeys_mod.read_modifiers_async = SET_ONLY  # matcher ที่ App สร้างเองต้องไม่อ่านคีย์บอร์ดจริง
        FakeListener.instances = []
        self.tmp = tempfile.TemporaryDirectory()
        self.app = fake_app([step(100, 100)])
        self.app.settings_file = os.path.join(self.tmp.name, "AutoClicker", "settings.json")

    def tearDown(self):
        app_mod.keyboard.Listener = self._orig_listener
        hotkeys_mod.read_modifiers_async = self._orig_read
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
        keys = hotkeys_mod.assign_hotkey(self.app.hotkeys, "toggle", hk(VK_1, "ctrl", "shift"))
        self.app.apply_hotkeys(keys)
        self.app.apply_hotkeys(hotkeys_mod.assign_hotkey(keys, "markers", hk(VK_A, "alt")))
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
        self.assertEqual(hotkeys_mod.load_hotkeys(self.app.settings_file)[0]["markers"], hk(VK_A, "alt"))

    def test_apply_rejects_duplicates_and_keeps_old(self):
        self.app._start_listener()
        old_kb = self.app.kb
        with self.assertRaises(ValueError):
            self.app.apply_hotkeys(dict(self.app.hotkeys, add=hk(VK_F6)))
        self.assertIs(self.app.kb, old_kb)
        self.assertEqual(self.app.hotkeys, constants.DEFAULT_HOTKEYS)
        self.assertFalse(os.path.exists(self.app.settings_file))

    def test_run_button_text_follows_run_state(self):
        app_mod.get_virtual_rect, orig_rect = (lambda: None), app_mod.get_virtual_rect
        app_mod.Runner, orig_runner = (
            (lambda *a, **k: types.SimpleNamespace(start=lambda: None)),
            app_mod.Runner,
        )
        try:
            self.app.toggle()
            self.assertEqual(self.app.run_btn.text, "■ หยุด (F6)")
            self.app.q.put(("done", "หยุดโดยผู้ใช้"))
            self.app._poll()
            self.assertEqual(self.app.run_btn.text, "▶ เริ่ม (F6)")
        finally:
            app_mod.get_virtual_rect, app_mod.Runner = orig_rect, orig_runner


class TimeUnitAppTests(unittest.TestCase):
    """หน่วยเวลาฝั่ง UI: ช่องรอของค่าเริ่มต้น และ save/load"""

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
            app_mod.filedialog.asksaveasfilename = lambda **k: path
            app_mod.filedialog.askopenfilename = lambda **k: path
            app_mod.messagebox.errors.clear()
            app = fake_app([step(100, 100, delay_ms=90000)])
            app.def_delay.set("0.5")
            app.def_delay_unit.set("นาที")
            app_mod.App.save(app)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["defaults"]["delay_ms"], 30000)  # ไฟล์ยังเป็น ms
            self.assertEqual(data["steps"][0]["delay_ms"], 90000)
            other = fake_app([])
            app_mod.App.load(other)
            self.assertEqual((other.def_delay.get(), other.def_delay_unit.get()), (30, "วินาที"))

    def test_save_bad_default_delay_shows_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            app_mod.filedialog.asksaveasfilename = lambda **k: path
            app_mod.messagebox.errors.clear()
            app = fake_app([step(100, 100)])
            app.def_delay.set("x")
            app_mod.App.save(app)
            self.assertEqual(len(app_mod.messagebox.errors), 1)
            self.assertFalse(os.path.exists(path))


class HoverSettingAppTests(unittest.TestCase):
    """hover_ms ฝั่ง UI: บีบค่า และ save/load"""

    def test_ui_clamps(self):
        app = fake_app([])
        for v, expect in [(5000, 1000), (-5, 0), ("x", 50), (120, 120)]:
            app.hover.set(v)
            self.assertEqual(app._cfg()["hover_ms"], expect)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            app_mod.filedialog.asksaveasfilename = lambda **k: path
            app_mod.filedialog.askopenfilename = lambda **k: path
            app_mod.messagebox.errors.clear()
            app = fake_app([step(100, 100)])
            app.hover.set(250)
            app_mod.App.save(app)
            other = fake_app([])
            app_mod.App.load(other)
            self.assertEqual(app_mod.messagebox.errors, [])
            self.assertEqual(other.hover.get(), 250)


class MarkerFallbackAppTests(unittest.TestCase):
    """App เปลี่ยนเป็นหมุดแบบธรรมดาและเตือนครั้งเดียว"""

    def test_app_falls_back_and_warns_once(self):
        orig = markers_mod._load_pil
        markers_mod._load_pil = lambda: None
        try:
            app = fake_app([])
            app._init_marker_mode()
            self.assertFalse(app.smooth_markers)
            self.assertEqual(app.status.get(), "หมุดแบบเรียบไม่พร้อม ใช้แบบธรรมดา")
            app.status.set("อย่างอื่น")
            app.marker_fallback(OSError("UpdateLayeredWindow failed"))
            self.assertEqual(app.status.get(), "อย่างอื่น")  # เตือนครั้งเดียว
        finally:
            markers_mod._load_pil = orig

    def test_runtime_win32_failure_switches_off_smooth(self):
        app = fake_app([])
        app.smooth_markers = True
        app.marker_fallback(OSError("ULW failed"))
        self.assertFalse(app.smooth_markers)
        self.assertEqual(app.status.get(), "หมุดแบบเรียบไม่พร้อม ใช้แบบธรรมดา")
        self.assertIsInstance(app.marker_fallback_reason, OSError)


class StartSettingAppTests(unittest.TestCase):
    """นับถอยหลัง / หยุดเมื่อสลับหน้าต่าง ฝั่ง UI"""

    def test_cfg_clamps_and_passes_flag(self):
        app = fake_app([])
        for v, expect in [(99, 30), (-1, 0), ("x", 3), (5, 5)]:
            app.countdown.set(v)
            self.assertEqual(app._cfg()["countdown_s"], expect)
        app.pause_switch.set(False)
        self.assertIs(app._cfg()["pause_on_switch"], False)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            app_mod.filedialog.asksaveasfilename = lambda **k: path
            app_mod.filedialog.askopenfilename = lambda **k: path
            app_mod.messagebox.errors.clear()
            app = fake_app([step(100, 100)])
            app.countdown.set(7)
            app.pause_switch.set(False)
            app_mod.App.save(app)
            other = fake_app([])
            app_mod.App.load(other)
            self.assertEqual(app_mod.messagebox.errors, [])
            self.assertEqual((other.countdown.get(), other.pause_switch.get()), (7, False))

    def test_load_old_file_sets_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"steps": [{"x": 50, "y": 60}], "settings": {"mode": "loop"}}, f)
            app_mod.filedialog.askopenfilename = lambda **k: path
            app = fake_app([])
            app.countdown.set(9)
            app.pause_switch.set(False)
            app_mod.App.load(app)
            self.assertEqual((app.countdown.get(), app.pause_switch.get()), (3, True))

    def test_notice_shown_in_status_without_row_highlight(self):
        app = fake_app([step(100, 100)])
        app.runner = types.SimpleNamespace(is_alive=lambda: True)
        app.q.put(("status", 1, 1, 1, 1))
        app.q.put(("notice", constants.PAUSED_TEXT))  # ข้อความล่าสุดของรอบ poll ชนะ
        app._poll()
        self.assertEqual(app.status.get(), constants.PAUSED_TEXT)
        app.q.put(("notice", "เริ่มใน 2…"))
        app._poll()
        self.assertEqual(app.status.get(), "เริ่มใน 2…")

    def test_toggle_passes_notice_and_hides_markers_first(self):
        orig = app_mod.Runner, app_mod.get_virtual_rect, app_mod.get_virtual_origin
        got = {}
        app = fake_app([step(100, 100)])
        app.refresh()

        def fake_runner(*a, **k):
            got.update(k, cfg=a[1], hidden=not any(m.visible for m in app.markers))
            return types.SimpleNamespace(start=lambda: None)

        app_mod.Runner, app_mod.get_virtual_rect, app_mod.get_virtual_origin = (
            fake_runner,
            lambda: None,
            lambda: (0, 0),
        )
        try:
            app.toggle()
        finally:
            app_mod.Runner, app_mod.get_virtual_rect, app_mod.get_virtual_origin = orig
        self.assertTrue(got["hidden"])  # กดเริ่มแล้วซ่อนหมุดทันที ก่อนนับถอยหลัง
        got["on_notice"]("เริ่มใน 3…")
        self.assertEqual(app.q.get_nowait(), ("notice", "เริ่มใน 3…"))
        self.assertEqual((got["cfg"]["countdown_s"], got["cfg"]["pause_on_switch"]), (3, True))


if __name__ == "__main__":
    unittest.main()
