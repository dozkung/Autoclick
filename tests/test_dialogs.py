"""เทสต์ logic ใน HotkeyDialog โดยไม่สร้าง Tk"""

import unittest

import support  # ตั้ง sys.path ให้ import autoclicker ได้

support.install_stubs()  # ต้องมาก่อน import module ที่ใช้ tkinter/pynput

from autoclicker import constants
from autoclicker.ui import dialogs
from support import VK_1, VK_A, VK_F6, VK_F7, VK_F8, FakeVar, FakeWidget, hk


class HotkeyDialogLogicTests(unittest.TestCase):
    """เทสต์ logic ใน HotkeyDialog โดยข้าม __init__ (ไม่สร้าง Tk)"""

    def setUp(self):
        d = dialogs.HotkeyDialog.__new__(dialogs.HotkeyDialog)
        d.work = {a: dict(v) for a, v in constants.DEFAULT_HOTKEYS.items()}
        d.capturing = None
        d.err = FakeVar("")
        d.buttons = {a: FakeWidget() for a in constants.HOTKEY_ACTIONS}
        d.focus_set = lambda: None
        self.d = d

    def test_capture_shows_prompt_then_assigns(self):
        self.d._capture("add")
        self.assertEqual(self.d.buttons["add"].text, dialogs.HotkeyDialog.PROMPT)
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
        self.assertEqual(self.d.work, constants.DEFAULT_HOTKEYS)

    def test_reset(self):
        self.d.work["toggle"] = hk(VK_A)
        self.d._reset()
        self.assertEqual(self.d.work, constants.DEFAULT_HOTKEYS)


if __name__ == "__main__":
    unittest.main()
