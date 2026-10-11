"""เทสต์ screen: โซน kill switch และขอบ virtual screen (ไม่ต้อง stub tkinter/pynput)"""

import sys
import unittest

import support  # noqa: F401  (import เพื่อตั้ง sys.path ให้ import autoclicker ได้)
from autoclicker import screen


class CornerTests(unittest.TestCase):
    def test_default_origin(self):
        self.assertTrue(screen.in_corner(0, 0))
        self.assertTrue(screen.in_corner(3, 3))
        self.assertFalse(screen.in_corner(4, 3))
        self.assertFalse(screen.in_corner(3, 4))

    def test_negative_origin(self):
        o = (-1920, 0)
        self.assertFalse(screen.in_corner(0, 0, o))
        self.assertTrue(screen.in_corner(-1920, 0, o))
        self.assertTrue(screen.in_corner(-1917, 3, o))
        self.assertFalse(screen.in_corner(-1916, 0, o))


class ScreenRectTests(unittest.TestCase):
    def test_none_rect_skips_check(self):
        self.assertFalse(screen.out_of_screen(-99999, 99999, None))

    def test_bounds(self):
        rect = (-1920, 0, 3840, 1080)  # จอเสริมอยู่ทางซ้ายจอหลัก
        for xy in [(-1920, 0), (1919, 1079), (0, 0)]:
            self.assertFalse(screen.out_of_screen(*xy, rect), xy)
        for xy in [(-1921, 0), (1920, 0), (0, -1), (0, 1080)]:
            self.assertTrue(screen.out_of_screen(*xy, rect), xy)


class ForegroundWindowTests(unittest.TestCase):
    def test_non_windows_disables_feature(self):
        orig = sys.platform
        sys.platform = "linux"
        try:
            self.assertIsNone(screen.foreground_window())
        finally:
            sys.platform = orig

    @unittest.skipUnless(sys.platform == "win32", "ต้องใช้ user32 จริง")
    def test_real_api_on_windows(self):
        hwnd = screen.foreground_window()
        if hwnd is None:  # เครื่องล็อกอยู่ / ไม่มีหน้าต่างข้างหน้า
            self.skipTest("ไม่มีหน้าต่างข้างหน้า")
        self.assertTrue(screen.is_window(hwnd))
        self.assertIsInstance(screen.window_pid(hwnd), int)
        self.assertFalse(screen.is_window(0x7FFFFFF0))  # HWND ที่ไม่มีอยู่จริง


if __name__ == "__main__":
    unittest.main()
