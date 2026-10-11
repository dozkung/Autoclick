"""เทสต์หมุดบนจอ: geometry, ภาพ Pillow, premultiply, fallback"""

import ctypes
import sys
import unittest

import support  # ตั้ง sys.path ให้ import autoclicker ได้

support.install_stubs()  # ต้องมาก่อน import module ที่ใช้ tkinter/pynput

from autoclicker import markers as markers_mod
from autoclicker import win32
from support import parse_geometry


class MarkerGeometryTests(unittest.TestCase):
    def test_center_on_step(self):
        self.assertEqual(markers_mod.marker_geometry(100, 200), "30x30+85+185")
        self.assertEqual(markers_mod.marker_geometry(100, 200, 44), "44x44+78+178")

    def test_negative_coords_use_plus_minus(self):
        # "-1934" ใน Tk แปลว่าวัดจากขอบขวา ต้องเป็น "+-1934"
        self.assertEqual(markers_mod.marker_geometry(-1920, 0), "30x30+-1935+-15")
        self.assertEqual(markers_mod.marker_geometry(-1900, -300), "30x30+-1915+-315")

    def test_near_zero_crosses_sign(self):
        self.assertEqual(markers_mod.marker_geometry(5, 5), "30x30+-10+-10")

    def test_marker_size_scales_with_dpi(self):
        self.assertEqual(markers_mod.marker_size(1.0), 30)  # วงกลม ~28px + ขอบเผื่อ
        self.assertEqual(markers_mod.marker_size(1.5), 44)
        self.assertEqual(markers_mod.marker_size(2.0), 60)
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0, 0.1):
            self.assertEqual(markers_mod.marker_size(scale) % 2, 0)  # เลขคู่ ศูนย์กลางเป็น pixel เต็ม

    def test_center_pixel_is_step_at_every_scale(self):
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            size = markers_mod.marker_size(scale)
            for x, y in [(100, 200), (-1920, 0), (-1, -1), (0, 0), (3839, 2159)]:
                with self.subTest(scale=scale, x=x, y=y):
                    w, h, wx, wy = parse_geometry(markers_mod.marker_geometry(x, y, size))
                    self.assertEqual((w, h), (size, size))
                    self.assertEqual((wx + size // 2, wy + size // 2), (x, y))  # ศูนย์กลาง = จุดคลิก

    def test_text_layout(self):
        ((t, dy, px),) = markers_mod.marker_text_layout(7, 1, 30)
        self.assertEqual((t, dy), ("7", 0.0))
        two = markers_mod.marker_text_layout(42, 1, 30)[0][2]
        self.assertLess(two, px)  # 2 หลักฟอนต์เล็กลง
        num, rep = markers_mod.marker_text_layout(42, 3, 30)
        self.assertEqual((num[0], rep[0]), ("42", "×3"))
        self.assertLess(num[1], 0)  # เลขขยับขึ้น
        self.assertGreater(rep[1], 0)  # ×n อยู่ใต้เลข
        self.assertLess(markers_mod.marker_text_layout(1, 1000, 30)[1][2], rep[2])  # ×1000 เล็กกว่า ×3
        self.assertGreater(markers_mod.marker_text_layout(42, 3, 44)[0][2], num[2])  # ขยายตาม DPI


@unittest.skipUnless(markers_mod._load_pil() is not None, "ต้องมี Pillow (pip install -r requirements.txt)")
class RenderMarkerImageTests(unittest.TestCase):
    def test_size_and_mode(self):
        for size in (30, 44, 60):
            img = markers_mod.render_marker_image(1, "#1e6fd9", 1, size)
            self.assertEqual((img.size, img.mode), ((size, size), "RGBA"))

    def test_corner_transparent_center_opaque(self):
        img = markers_mod.render_marker_image(1, "#1e6fd9", 1, 30)
        for corner in [(0, 0), (29, 0), (0, 29), (29, 29)]:
            self.assertEqual(img.getpixel(corner)[3], 0, corner)
        self.assertEqual(img.getpixel((15, 15))[3], 255)
        self.assertEqual(img.getpixel((15, 5))[3], 255)  # ในวงแต่ไม่โดนตัวเลข

    def test_edge_is_antialiased(self):
        img = markers_mod.render_marker_image(1, "#1e6fd9", 1, 30)
        alphas = set(img.getchannel("A").getdata())
        partial = [a for a in alphas if 0 < a < 255]
        self.assertGreaterEqual(len(partial), 5)  # มีค่า alpha ไล่ระดับที่ขอบ = ขอบเนียน
        # เดินจากมุมเข้าหากลางตามแนวทแยง ต้องผ่านค่า alpha กลางๆ ก่อนถึงทึบ
        diag = [img.getpixel((i, i))[3] for i in range(0, 15)]
        self.assertTrue(any(0 < a < 255 for a in diag), diag)

    def test_white_border_and_fill_color(self):
        img = markers_mod.render_marker_image(1, "#d62828", 1, 30)
        r, g, b, a = img.getpixel((15, 2))  # บนขอบขาวด้านบน
        self.assertGreater(min(r, g, b), 200)
        self.assertEqual(img.getpixel((8, 15)), (0xD6, 0x28, 0x28, 255))  # ในวง ไม่โดนตัวเลข

    def test_digits_and_repeat_do_not_error(self):
        for n, rep in [(1, 1), (9, 1), (10, 1), (99, 1), (100, 1), (7, 3), (42, 12), (99, 1000)]:
            for size in (30, 44):
                with self.subTest(n=n, rep=rep, size=size):
                    self.assertEqual(
                        markers_mod.render_marker_image(n, "#7b3fe4", rep, size).size, (size, size)
                    )

    def test_text_is_drawn(self):
        img = markers_mod.render_marker_image(1, "#1e6fd9", 1, 30)
        whites = [x for x in range(6, 24) if min(img.getpixel((x, 15))[:3]) > 200]
        self.assertTrue(whites)  # ตัวเลขสีขาวกลางวง

    def test_font_fallback_when_no_ttf(self):
        orig, markers_mod._FONT_FILES = markers_mod._FONT_FILES, (r"C:\nope\missing.ttf",)
        markers_mod._font_cache.clear()
        try:
            self.assertEqual(markers_mod.render_marker_image(42, "#1e6fd9", 3, 30).size, (30, 30))
        finally:
            markers_mod._FONT_FILES = orig
            markers_mod._font_cache.clear()


class PremultiplyTests(unittest.TestCase):
    class Img:
        def __init__(self, pixels):
            self.pixels = pixels

        def tobytes(self):
            return bytes(v for px in self.pixels for v in px)

    def test_premultiply_and_bgra_order(self):
        out = markers_mod.premultiply_bgra(
            self.Img([(255, 128, 0, 128), (10, 20, 30, 255), (200, 100, 50, 0), (255, 255, 255, 1)])
        )
        self.assertEqual(list(out[0:4]), [0, 64, 128, 128])  # B G R A, r*a/255 ปัดเศษ
        self.assertEqual(list(out[4:8]), [30, 20, 10, 255])  # alpha เต็ม = สีเดิม
        self.assertEqual(list(out[8:12]), [0, 0, 0, 0])  # โปร่งหมด = ดำ (ไม่งั้นขอบสว่างผิด)
        self.assertEqual(list(out[12:16]), [1, 1, 1, 1])

    def test_never_exceeds_alpha(self):
        pixels = [(r, 255 - r, (r * 7) % 256, a) for r in range(0, 256, 17) for a in range(0, 256, 15)]
        out = markers_mod.premultiply_bgra(self.Img(pixels))
        for i in range(0, len(out), 4):
            self.assertLessEqual(max(out[i : i + 3]), out[i + 3])


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
            self.assertIsNone(markers_mod._load_pil())
            self.assertFalse(markers_mod.smooth_markers_available())
            with self.assertRaises(ImportError):
                markers_mod.render_marker_image(1, "#1e6fd9", 1, 30)
        finally:
            builtins.__import__ = real_import

    def test_not_windows_means_not_smooth(self):
        orig = sys.platform
        sys.platform = "linux"
        try:
            self.assertFalse(markers_mod.smooth_markers_available())
        finally:
            sys.platform = orig

    @unittest.skipUnless(sys.platform == "win32", "ต้องใช้ user32 จริง")
    def test_win32_api_has_64bit_safe_signatures(self):
        api = win32._win32_api()
        self.assertIs(api.gdi32.CreateCompatibleDC.restype, ctypes.c_void_p)
        self.assertIs(api.user32.GetDC.restype, ctypes.c_void_p)
        self.assertIsNot(api.user32, ctypes.windll.user32)  # ห้ามไปแก้ ctypes.windll ที่ pynput ใช้ร่วม

    def test_bitmap_header_size(self):
        self.assertEqual(ctypes.sizeof(win32._BITMAPINFOHEADER), 40)
        self.assertEqual(ctypes.sizeof(win32._BLENDFUNCTION), 4)


if __name__ == "__main__":
    unittest.main()
