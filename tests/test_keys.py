"""เทสต์ step กดปุ่มคีย์บอร์ด: Runner (FakeKeys ไม่กดปุ่มจริง), App และ StepDialog (ไม่สร้าง Tk)"""

import ctypes
import json
import time
import types
import unittest

import support  # ตั้ง sys.path ให้ import autoclicker ได้

support.install_stubs()  # ต้องมาก่อน import module ที่ใช้ tkinter/pynput

from test_runner import RunnerHarness

from autoclicker import constants, model, win32
from autoclicker import hotkeys as hotkeys_mod
from autoclicker import runner as runner_mod
from autoclicker.ui import app as app_mod
from autoclicker.ui import dialogs
from support import (
    VK_A,
    VK_F6,
    VK_F8,
    FakeKeys,
    FakeMouse,
    FakeVar,
    FakeWidget,
    FakeWindows,
    cfg,
    hk,
    key_step,
    keycode,
    step,
)
from ui_support import fake_app

VK_E, VK_CTRL, VK_SHIFT, VK_LEFT, VK_DELETE = 0x45, 0x11, 0x10, 0x25, 0x2E


class KeyInputFieldsTests(unittest.TestCase):
    """ค่า KEYBDINPUT ที่จะส่ง (ไม่แตะ Win32)"""

    def test_scancode_press_and_release(self):
        self.assertEqual(runner_mod.key_input_fields(VK_E, True, 0x12), (0, 0x12, win32._KEYEVENTF_SCANCODE))
        self.assertEqual(
            runner_mod.key_input_fields(VK_E, False, 0x12),
            (0, 0x12, win32._KEYEVENTF_SCANCODE | win32._KEYEVENTF_KEYUP),
        )

    def test_extended_keys_get_extended_flag(self):
        for vk in (VK_LEFT, VK_DELETE, 0x21, 0x22, 0x23, 0x24, 0x2D):
            with self.subTest(vk=hex(vk)):
                _, _, flags = runner_mod.key_input_fields(vk, True, 0x4B)
                self.assertTrue(flags & win32._KEYEVENTF_EXTENDEDKEY)
        _, _, flags = runner_mod.key_input_fields(VK_E, True, 0x12)
        self.assertFalse(flags & win32._KEYEVENTF_EXTENDEDKEY)

    def test_no_scancode_falls_back_to_vk(self):
        wvk, wscan, flags = runner_mod.key_input_fields(0xAD, True, 0)
        self.assertEqual((wvk, wscan), (0xAD, 0))
        self.assertFalse(flags & win32._KEYEVENTF_SCANCODE)

    def test_input_union_holds_keyboard(self):
        inp = win32._INPUT()
        inp.type = win32._INPUT_KEYBOARD
        inp.ki.wScan = 0x12
        self.assertEqual(inp.ki.wScan, 0x12)
        # KEYBDINPUT เล็กกว่า MOUSEINPUT: ใส่เพิ่มแล้วขนาด INPUT ต้องไม่เปลี่ยน
        self.assertLessEqual(ctypes.sizeof(win32._KEYBDINPUT), ctypes.sizeof(win32._MOUSEINPUT))


class KeyRunnerTests(unittest.TestCase):
    def test_press_order_mods_then_key_release_reversed(self):
        h = RunnerHarness([key_step(VK_E, "ctrl", "shift")], cfg(mode="count", rounds=1)).start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(
            h.keys.log,
            [
                (VK_CTRL, True),
                (VK_SHIFT, True),
                (VK_E, True),
                (VK_E, False),
                (VK_SHIFT, False),
                (VK_CTRL, False),
            ],
        )
        self.assertEqual(h.keys.down, set())

    def test_key_step_never_touches_mouse(self):
        h = RunnerHarness([key_step(VK_E)], cfg(mode="count", rounds=2, hover_ms=200)).start()
        h.finish()
        self.assertEqual(h.mouse.events, [])  # ไม่วาร์ป ไม่ nudge ไม่รอ hover
        self.assertEqual(h.keys.log, [(VK_E, True), (VK_E, False)] * 2)

    def test_repeat(self):
        h = RunnerHarness([key_step(VK_E, repeat=3, gap_ms=10)], cfg(mode="count", rounds=1)).start()
        h.finish()
        self.assertEqual(h.keys.log, [(VK_E, True), (VK_E, False)] * 3)
        self.assertEqual([s[2:] for s in h.statuses], [(1, 3), (2, 3), (3, 3)])

    def test_mixed_with_clicks_in_order(self):
        events = []

        class Keys(FakeKeys):
            def send(self, vk, down):
                events.append(("key", vk, down))
                super().send(vk, down)

        class Mouse(FakeMouse):
            def click(self, button, count=1):
                events.append(("click", self.position))
                super().click(button, count)

        steps = [step(100, 100), key_step(VK_E), step(200, 200)]
        RunnerHarness(steps, cfg(mode="count", rounds=1), mouse=Mouse(), keys=Keys()).start().finish()
        self.assertEqual(
            events,
            [("click", (100, 100)), ("key", VK_E, True), ("key", VK_E, False), ("click", (200, 200))],
        )

    def test_hold_uses_wait_and_stop_releases_everything(self):
        h = RunnerHarness([key_step(VK_E, "ctrl", hold_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: (VK_E, True) in h.keys.log))
        t = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")
        self.assertLess(time.monotonic() - t, 0.3)
        self.assertEqual(h.keys.down, set())
        self.assertEqual(h.keys.log[-2:], [(VK_E, False), (VK_CTRL, False)])

    def test_kill_switch_during_key_hold(self):
        h = RunnerHarness([key_step(VK_E, hold_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: VK_E in h.keys.down))
        h.mouse.position = (0, 0)
        self.assertEqual(h.finish(), constants.KILL_REASON)
        self.assertEqual(h.keys.down, set())

    def test_release_keeps_going_when_one_release_fails(self):
        # ปล่อยปุ่มหลักพัง ก็ต้องปล่อย Ctrl ต่อ ไม่งั้น Ctrl ค้างทั้งเครื่อง
        keys = FakeKeys(fail_on=(VK_E, False))
        h = RunnerHarness([key_step(VK_E, "ctrl")], cfg(mode="count", rounds=1), keys=keys).start()
        h.finish()
        self.assertIn((VK_CTRL, False), keys.log)
        self.assertNotIn(VK_CTRL, keys.down)

    def test_press_failure_stops_with_error_and_releases(self):
        keys = FakeKeys(fail_on=(VK_E, True))
        h = RunnerHarness([key_step(VK_E, "shift")], cfg(mode="count", rounds=1), keys=keys).start()
        self.assertTrue(h.finish().startswith("error:"))
        self.assertEqual(keys.log, [(VK_SHIFT, True), (VK_SHIFT, False)])

    def test_waits_for_target_window_before_pressing(self):
        win = FakeWindows()
        steps = [key_step(VK_E, delay_ms=300), key_step(VK_A)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=1, pause_on_switch=True), win=win).start()
        self.assertTrue(h.wait_for(lambda: (VK_E, False) in h.keys.log))
        win.foreground = win.OTHER  # สลับหน้าต่างระหว่างรอ 300ms ก่อนกดปุ่มถัดไป
        time.sleep(0.6)
        self.assertNotIn((VK_A, True), h.keys.log)  # หน้าต่างเกมไม่อยู่ข้างหน้า ห้ามกด
        win.foreground = win.GAME
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(h.keys.log, [(VK_E, True), (VK_E, False), (VK_A, True), (VK_A, False)])

    def test_window_lost_during_hold_releases_then_presses_again(self):
        win = FakeWindows()
        h = RunnerHarness(
            [key_step(VK_E, hold_ms=400)], cfg(mode="count", rounds=1, pause_on_switch=True), win=win
        ).start()
        self.assertTrue(h.wait_for(lambda: VK_E in h.keys.down))
        win.foreground = win.OTHER
        self.assertTrue(h.wait_for(lambda: VK_E not in h.keys.down))  # ห้ามค้างปุ่มระหว่างหยุดชั่วคราว
        win.foreground = win.GAME
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(h.keys.log, [(VK_E, True), (VK_E, False)] * 2)


class KeyAppTests(unittest.TestCase):
    def setUp(self):
        self._orig = app_mod.get_virtual_rect, app_mod.get_virtual_origin, app_mod.Runner
        app_mod.get_virtual_rect = lambda: (0, 0, 1920, 1080)
        app_mod.get_virtual_origin = lambda: (0, 0)
        self.started = []
        app_mod.Runner = lambda *a, **k: (
            self.started.append(a) or types.SimpleNamespace(start=lambda: None, is_alive=lambda: True)
        )

    def tearDown(self):
        app_mod.get_virtual_rect, app_mod.get_virtual_origin, app_mod.Runner = self._orig

    def test_key_step_skips_screen_checks(self):
        app = fake_app([key_step(VK_E), step(100, 100)])
        app.toggle()
        self.assertEqual(app.status.get(), "กำลังรัน…")
        self.assertEqual(len(self.started), 1)

    def test_toggle_refuses_key_matching_hotkey(self):
        app = fake_app([step(100, 100), key_step(VK_F6)])
        app.toggle()
        self.assertIn("จุด #2", app.status.get())
        self.assertIn("ปุ่มลัด", app.status.get())
        self.assertEqual(self.started, [])

    def test_toggle_allows_same_key_with_different_mods(self):
        app = fake_app([key_step(VK_F6, "shift")])  # Shift+F6 ไม่ใช่ F6 (matcher เทียบ mods ตรงตัว)
        app.toggle()
        self.assertEqual(len(self.started), 1)

    def test_no_marker_for_key_step_and_numbers_match_table(self):
        app = fake_app([step(100, 100), key_step(VK_E), step(300, 300)])
        app.refresh()
        self.assertEqual([m.index for m in app.markers], [0, 2])

    def test_marker_drop_finds_marker_by_index(self):
        app = fake_app([key_step(VK_E), step(100, 100)])
        app.refresh()
        app.on_marker_drop(1, 2, 2)  # kill switch -> ดีดกลับหมุดของ step #2 ไม่ใช่ markers[1]
        self.assertIn(("snap_back", 1), app.log)
        app.on_marker_drop(1, 640, 480)
        self.assertEqual((app.steps[1]["x"], app.steps[1]["y"]), (640, 480))

    def test_injected_keys_ignored(self):
        app = fake_app([])
        app._on_press(keycode(VK_F6), True)
        app._on_release(keycode(VK_F6), True)
        self.assertTrue(app.q.empty())
        self.assertEqual(app.matcher.down, set())
        app._on_press(keycode(VK_F6), False)  # ปุ่มจริงยังทำงาน
        self.assertEqual(app.q.get_nowait(), ("toggle",))

    def test_on_press_still_works_with_old_pynput_signature(self):
        app = fake_app([])
        app._on_press(keycode(VK_F8))  # pynput < 1.8 เรียกด้วย key ตัวเดียว
        self.assertEqual(app.q.get_nowait()[0], "add")

    def test_key_capture_pauses_hotkeys_and_routes_capture(self):
        app = fake_app([])
        got = []
        sink = types.SimpleNamespace(on_captured=got.append)
        app.begin_key_capture(sink)
        self.assertTrue(app.matcher.paused)
        app._on_press(keycode(VK_F6))  # ตอนจับปุ่ม F6 ต้องไม่สั่งเริ่ม
        msg = app.q.get_nowait()
        self.assertEqual(msg, ("captured", hk(VK_F6)))
        app.q.put(msg)
        app._poll()
        self.assertEqual(got, [hk(VK_F6)])
        app.end_key_capture()
        self.assertFalse(app.matcher.paused)
        self.assertIsNone(app.key_capture)

    def test_end_capture_keeps_pause_while_hotkey_dialog_open(self):
        app = fake_app([])
        app.hotkey_dialog = object()
        app.begin_key_capture(types.SimpleNamespace(on_captured=lambda hk: None))
        app.end_key_capture()
        self.assertTrue(app.matcher.paused)

    def test_save_and_load_roundtrip_with_key_step(self):
        steps = [step(100, 100), key_step(VK_E, "ctrl", hold_ms=50, repeat=2)]
        data = {"version": 1, "steps": steps}
        loaded, _, _ = model.parse_profile(json.loads(json.dumps(data)))
        self.assertEqual(loaded, steps)


class StepDialogKeyTests(unittest.TestCase):
    """logic การจับปุ่มใน StepDialog โดยข้าม __init__ (ไม่สร้าง Tk)"""

    def setUp(self):
        d = dialogs.StepDialog.__new__(dialogs.StepDialog)
        self.app = fake_app([])
        d.app = self.app
        d.capturing = False
        d.key = {"mods": [], "vk": VK_E}
        d.key_btn = FakeWidget()
        d.focus_set = lambda: None
        d.result = None
        self.destroyed = []
        d.destroy = lambda: self.destroyed.append(True)
        d.vars = {
            "x": FakeVar("100"),
            "y": FakeVar("100"),
            "type": FakeVar(constants.CLICK_LABEL["key"]),
            "repeat": FakeVar("1"),
            "delay_ms": FakeVar("500"),
            "delay_ms_unit": FakeVar("ms"),
            "hold_ms": FakeVar("50"),
            "hold_ms_unit": FakeVar("ms"),
            "gap_ms": FakeVar("100"),
            "gap_ms_unit": FakeVar("ms"),
        }
        self.errors = dialogs.messagebox.errors
        self.errors.clear()
        self.d = d

    def test_capture_sets_key(self):
        self.d._capture_key()
        self.assertTrue(self.app.matcher.paused)
        self.assertEqual(self.d.key_btn.text, dialogs.StepDialog.KEY_PROMPT)
        self.d.on_captured(hk(VK_A, "ctrl"))
        self.assertEqual(self.d.key, hk(VK_A, "ctrl"))
        self.assertEqual(self.d.key_btn.text, "Ctrl+A")
        self.assertFalse(self.app.matcher.paused)

    def test_escape_cancels_capture(self):
        self.d._capture_key()
        self.d.on_captured(hk(0x1B))
        self.assertEqual(self.d.key, {"mods": [], "vk": VK_E})
        self.assertFalse(self.d.capturing)

    def test_hotkey_rejected(self):
        self.d._capture_key()
        self.d.on_captured(hk(VK_F6))
        self.assertEqual(self.d.key, {"mods": [], "vk": VK_E})
        self.assertIn("ปุ่มลัด", self.errors[-1])

    def test_modifier_alone_rejected(self):
        self.d._capture_key()
        self.d.on_captured(hk(0xA2))  # Ctrl ซ้ายเดี่ยวๆ
        self.assertEqual(self.d.key, {"mods": [], "vk": VK_E})
        self.assertTrue(self.errors)

    def test_ok_ignored_while_capturing(self):
        self.d._capture_key()
        self.d._ok()  # Enter ระหว่างจับปุ่ม ต้องไม่ปิด dialog
        self.assertEqual(self.destroyed, [])
        self.assertIsNone(self.d.result)

    def test_ok_builds_key_step_without_coords(self):
        self.d._ok()
        self.assertEqual(self.d.result, model.make_key_step(VK_E, [], 500, 50, 1, 100))
        self.assertEqual(self.destroyed, [True])

    def test_close_while_capturing_restores_hotkeys(self):
        self.d._capture_key()
        self.d._close()
        self.assertFalse(self.app.matcher.paused)
        self.assertIsNone(self.app.key_capture)

    def test_ok_rejects_key_that_became_hotkey(self):
        self.d.key = hk(VK_F8)  # ปุ่มเดิมของ step ชนปุ่มลัดเพิ่มจุด
        self.d._ok()
        self.assertIsNone(self.d.result)
        self.assertIn("ปุ่มลัด", self.errors[-1])


class HotkeyConflictTests(unittest.TestCase):
    def test_exact_match_only(self):
        keys = {a: dict(v) for a, v in constants.DEFAULT_HOTKEYS.items()}
        self.assertEqual(hotkeys_mod.hotkey_conflict(hk(VK_F6), keys), "เริ่ม / หยุด")
        self.assertIsNone(hotkeys_mod.hotkey_conflict(hk(VK_F6, "ctrl"), keys))
        self.assertIsNone(hotkeys_mod.hotkey_conflict(hk(VK_E), keys))


if __name__ == "__main__":
    unittest.main()
