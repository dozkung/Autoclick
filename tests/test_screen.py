"""เทสต์ screen: โซน kill switch และขอบ virtual screen (ไม่ต้อง stub tkinter/pynput)"""

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


if __name__ == "__main__":
    unittest.main()
