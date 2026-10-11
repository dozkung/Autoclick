"""เทสต์ปุ่มลัด: แปลง/validate, HotkeyMatcher, ไฟล์ตั้งค่า (ไม่ต้อง stub tkinter/pynput)"""

import json
import os
import sys
import tempfile
import types
import unittest

import support  # noqa: F401  (import เพื่อตั้ง sys.path ให้ import autoclicker ได้)
from autoclicker import constants
from autoclicker import hotkeys as hotkeys_mod
from support import (
    SET_ONLY,
    VK_1,
    VK_A,
    VK_F6,
    VK_F7,
    VK_F8,
    VK_LALT,
    VK_LCTRL,
    VK_LSHIFT,
    VK_RCTRL,
    VK_RSHIFT,
    hk,
    keycode,
    special_key,
)


class HotkeyTextTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(hotkeys_mod.hotkey_to_text(hk(VK_F6)), "F6")
        self.assertEqual(hotkeys_mod.hotkey_to_text(hk(VK_1, "shift", "ctrl")), "Ctrl+Shift+1")
        self.assertEqual(hotkeys_mod.hotkey_to_text(hk(VK_A, "alt")), "Alt+A")
        self.assertEqual(hotkeys_mod.hotkey_to_text(hk(0x65)), "Num 5")
        self.assertEqual(hotkeys_mod.hotkey_to_text(hk(0x87)), "F24")
        self.assertEqual(hotkeys_mod.hotkey_to_text(hk(0xFE)), "VK 0xFE")

    def test_labels_follow_hotkeys(self):
        keys = hotkeys_mod.assign_hotkey(constants.DEFAULT_HOTKEYS, "toggle", hk(VK_1, "ctrl", "shift"))
        lb = hotkeys_mod.hotkey_labels(keys)
        self.assertEqual(lb["start"], "▶ เริ่ม (Ctrl+Shift+1)")
        self.assertEqual(lb["stop"], "■ หยุด (Ctrl+Shift+1)")
        self.assertEqual(lb["markers"], "แสดงหมุด (F7)")
        self.assertIn("Ctrl+Shift+1 = เริ่ม/หยุด", lb["header"])
        self.assertIn("F8", lb["no_steps"])


class ParseHotkeyTests(unittest.TestCase):
    def test_normalizes_mod_order_and_dupes(self):
        self.assertEqual(
            hotkeys_mod.parse_hotkey({"vk": VK_1, "mods": ["shift", "ctrl", "shift"]}),
            hk(VK_1, "ctrl", "shift"),
        )
        self.assertEqual(hotkeys_mod.parse_hotkey({"vk": VK_F6}), hk(VK_F6))

    def test_rejects(self):
        bad = [
            None,
            [],
            {"mods": []},
            {"vk": "F6"},
            {"vk": True},
            {"vk": 0},
            {"vk": 300},
            {"vk": VK_F6, "mods": ["win"]},
            {"vk": VK_F6, "mods": "ctrl"},
            {"vk": 0x1B},
            {"vk": 0x1B, "mods": ["ctrl"]},  # Esc
            {"vk": 0x5B},  # Win
            {"vk": 0x10},
            {"vk": VK_LSHIFT},
            {"vk": VK_RCTRL, "mods": ["shift"]},
            {"vk": VK_LALT},
        ]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(ValueError):
                hotkeys_mod.parse_hotkey(d)

    def test_validate_defaults(self):
        self.assertEqual(hotkeys_mod.validate_hotkeys(constants.DEFAULT_HOTKEYS), constants.DEFAULT_HOTKEYS)
        self.assertEqual(constants.DEFAULT_HOTKEYS["markers"], hk(VK_F7))

    def test_validate_rejects_duplicates(self):
        d = dict(constants.DEFAULT_HOTKEYS, add=hk(VK_F6))
        with self.assertRaisesRegex(ValueError, "ซ้ำ"):
            hotkeys_mod.validate_hotkeys(d)
        # mods ลำดับต่างกันก็นับว่าซ้ำ
        d = dict(constants.DEFAULT_HOTKEYS, add=hk(VK_1, "ctrl", "shift"), markers=hk(VK_1, "shift", "ctrl"))
        with self.assertRaises(ValueError):
            hotkeys_mod.validate_hotkeys(d)

    def test_validate_requires_exact_actions(self):
        with self.assertRaises(ValueError):
            hotkeys_mod.validate_hotkeys({"toggle": hk(VK_F6), "add": hk(VK_F8)})
        with self.assertRaises(ValueError):
            hotkeys_mod.validate_hotkeys(dict(constants.DEFAULT_HOTKEYS, extra=hk(VK_A)))

    def test_assign_hotkey(self):
        base = {a: dict(v) for a, v in constants.DEFAULT_HOTKEYS.items()}
        new = hotkeys_mod.assign_hotkey(base, "add", hk(VK_A, "ctrl"))
        self.assertEqual(new["add"], hk(VK_A, "ctrl"))
        self.assertEqual(base, constants.DEFAULT_HOTKEYS)  # ไม่แก้ของเดิม
        with self.assertRaisesRegex(ValueError, "ใช้กับ"):
            hotkeys_mod.assign_hotkey(base, "add", hk(VK_F6))
        # ตั้งปุ่มเดิมให้หน้าที่เดิมได้ ไม่นับว่าซ้ำ
        self.assertEqual(hotkeys_mod.assign_hotkey(base, "toggle", hk(VK_F6)), base)

    def test_key_to_vk(self):
        self.assertEqual(hotkeys_mod.key_to_vk(keycode(VK_A)), VK_A)
        self.assertEqual(hotkeys_mod.key_to_vk(special_key(VK_F6)), VK_F6)
        self.assertIsNone(hotkeys_mod.key_to_vk(types.SimpleNamespace(vk=None)))
        self.assertIsNone(hotkeys_mod.key_to_vk(object()))


class HotkeyMatcherTests(unittest.TestCase):
    """โหมด fallback: อ่าน modifier จาก set self.down (เหมือนตอนไม่ใช่ Windows)"""

    def setUp(self):
        keys = hotkeys_mod.assign_hotkey(constants.DEFAULT_HOTKEYS, "add", hk(VK_1, "ctrl", "shift"))
        self.m = hotkeys_mod.HotkeyMatcher(keys, read_mods=SET_ONLY)

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
                    m = hotkeys_mod.HotkeyMatcher(
                        hotkeys_mod.assign_hotkey(
                            constants.DEFAULT_HOTKEYS, "add", hk(VK_1, "ctrl", "shift")
                        ),
                        read_mods=SET_ONLY,
                    )
                    m.press(ctrl)
                    m.press(shift)
                    self.assertEqual(m.press(VK_1), "add")

    def test_modifiers_must_match_exactly(self):
        self.m.press(VK_LCTRL)
        self.assertIsNone(self.m.press(VK_F6))  # Ctrl+F6 ไม่ใช่ F6
        self.m.release(VK_F6)
        self.m.release(VK_LCTRL)
        self.assertIsNone(self.m.press(VK_1))  # 1 เฉยๆ ไม่ใช่ Ctrl+Shift+1

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
        keys = hotkeys_mod.assign_hotkey(constants.DEFAULT_HOTKEYS, "add", hk(VK_1, "ctrl", "shift"))
        self.m = hotkeys_mod.HotkeyMatcher(keys, read_mods=lambda: set(self.held))

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

        m = hotkeys_mod.HotkeyMatcher(constants.DEFAULT_HOTKEYS, read_mods=broken)
        m.press(VK_LCTRL)
        self.assertIsNone(m.press(VK_F6))  # set บอกว่า Ctrl ค้าง = Ctrl+F6
        m.release(VK_F6)
        m.release(VK_LCTRL)
        self.assertEqual(m.press(VK_F6), "toggle")

    def test_default_reader_is_async(self):
        self.assertIs(
            hotkeys_mod.HotkeyMatcher(constants.DEFAULT_HOTKEYS).read_mods, hotkeys_mod.read_modifiers_async
        )

    def test_read_modifiers_async_non_windows(self):
        orig = sys.platform
        sys.platform = "linux"
        try:
            self.assertIsNone(hotkeys_mod.read_modifiers_async())
        finally:
            sys.platform = orig

    @unittest.skipUnless(sys.platform == "win32", "ต้องใช้ user32 จริง")
    def test_read_modifiers_async_windows_returns_set(self):
        mods = hotkeys_mod.read_modifiers_async()
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
        self.assertEqual(hotkeys_mod.load_hotkeys(self.path), (constants.DEFAULT_HOTKEYS, None))

    def test_round_trip_atomic(self):
        keys = hotkeys_mod.assign_hotkey(constants.DEFAULT_HOTKEYS, "toggle", hk(VK_1, "ctrl", "shift"))
        hotkeys_mod.save_hotkeys(self.path, keys)  # สร้างโฟลเดอร์ให้เอง
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["settings.json"])  # ไม่มี .tmp ค้าง
        self.assertEqual(hotkeys_mod.load_hotkeys(self.path), (keys, None))

    def test_save_rejects_invalid(self):
        with self.assertRaises(ValueError):
            hotkeys_mod.save_hotkeys(self.path, dict(constants.DEFAULT_HOTKEYS, add=hk(VK_F6)))
        self.assertFalse(os.path.exists(self.path))

    def test_broken_files_fall_back_with_warning(self):
        cases = [
            '{"hotkeys": {"toggle": ',
            "[]",
            '{"hotkeys": []}',
            json.dumps({"hotkeys": {"toggle": hk(VK_F8)}}),  # ซ้ำกับ add ที่เป็นค่าเริ่มต้น
            json.dumps({"hotkeys": {"toggle": hk(VK_LSHIFT)}}),  # modifier เดี่ยว
            json.dumps({"hotkeys": {"bogus": hk(VK_A)}}),
            "\xff\xfe",
        ]
        for text in cases:
            with self.subTest(text=text):
                self._write(text)
                keys, warn = hotkeys_mod.load_hotkeys(self.path)
                self.assertEqual(keys, constants.DEFAULT_HOTKEYS)
                self.assertTrue(warn)

    def test_partial_file_fills_defaults(self):
        self._write(json.dumps({"hotkeys": {"markers": hk(VK_A, "alt")}}))
        keys, warn = hotkeys_mod.load_hotkeys(self.path)
        self.assertIsNone(warn)
        self.assertEqual(keys["markers"], hk(VK_A, "alt"))
        self.assertEqual(keys["toggle"], constants.DEFAULT_HOTKEYS["toggle"])

    def test_settings_path_under_appdata(self):
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.tmp.name
        try:
            self.assertEqual(
                hotkeys_mod.settings_path(), os.path.join(self.tmp.name, "AutoClicker", "settings.json")
            )
        finally:
            if old is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = old


if __name__ == "__main__":
    unittest.main()
