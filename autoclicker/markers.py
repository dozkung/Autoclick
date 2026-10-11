"""หมุดบนจอ: วาดภาพ (Pillow), แสดงแบบ per-pixel alpha (UpdateLayeredWindow) และหน้าต่าง Marker
แบบเรียบใช้ไม่ได้เมื่อไร ให้ fallback เป็น Canvas + -transparentcolor (หมุดต้องขึ้นเสมอ)"""

import ctypes
import sys
import tkinter as tk

from .constants import MARKER_COLOR, MARKER_DRAG_PX, MARKER_KEY, MARKER_SIZE, MARKER_SS
from .win32 import (
    _AC_SRC_ALPHA,
    _AC_SRC_OVER,
    _BITMAPINFOHEADER,
    _BLENDFUNCTION,
    _GWL_EXSTYLE,
    _POINT,
    _SIZE,
    _ULW_ALPHA,
    _WS_EX_LAYERED,
    _win32_api,
)


def marker_size(scale=1.0):
    """ขนาดหน้าต่างหมุด (px) วงกลม ~28px + ขอบเผื่อ 1px ต่อด้าน คูณ DPI scale เป็นเลขคู่เสมอ"""
    return 2 * max(8, round(MARKER_SIZE / 2 * scale))


def marker_geometry(x, y, size=MARKER_SIZE):
    """geometry ของหน้าต่างหมุด (size x size) ที่ทำให้ศูนย์กลางหมุด (pixel size//2) ตรงกับ (x, y) เป๊ะ
    ต้องเขียน "+-1934" ไม่ใช่ "-1934" เพราะใน Tk "-N" แปลว่าวัดจากขอบขวา/ล่างของจอ"""
    c = size // 2
    return f"{size}x{size}+{x - c}+{y - c}"


def marker_text_layout(n, repeat, size):
    """ข้อความในหมุด [(text, dy, font_px)] ใช้ร่วมกันทั้งแบบเรียบ (Pillow) และแบบธรรมดา (Canvas)
    dy วัดจากศูนย์กลาง เลขหลายหลักฟอนต์เล็กลงให้พอดีวง"""
    k = size / MARKER_SIZE
    digits = len(str(n))
    if repeat > 1:  # เลขขยับขึ้น แล้วเขียน ×n ตัวเล็กไว้ข้างใต้ภายในวง (ยิ่งหลายหลักยิ่งเล็ก ไม่ให้ล้นวง)
        num_px = {1: 11, 2: 10}.get(digits, 8)
        rep_px = {1: 7, 2: 7, 3: 6}.get(len(str(repeat)), 5)
        return [
            (str(n), -3.5 * k, max(6, round(num_px * k))),
            (f"×{repeat}", 6.5 * k, max(5, round(rep_px * k))),
        ]
    num_px = {1: 14, 2: 12}.get(digits, 10)
    return [(str(n), 0.0, max(6, round(num_px * k)))]


_FONT_FILES = (
    r"C:\Windows\Fonts\tahomabd.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
)


def _load_pil():
    """คืน (Image, ImageDraw, ImageFont) หรือ None ถ้าไม่มี Pillow (แยกไว้ให้เทสต์ mock ได้)"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    return Image, ImageDraw, ImageFont


_font_cache = {}


def _marker_font(ImageFont, px):
    if px not in _font_cache:
        font = None
        for path in _FONT_FILES:
            try:
                font = ImageFont.truetype(path, px)
                break
            except OSError:
                continue
        if font is None:
            try:
                font = ImageFont.load_default(size=px)  # Pillow >= 10.1
            except TypeError:
                font = ImageFont.load_default()
        _font_cache[px] = font
    return _font_cache[px]


def render_marker_image(n, color, repeat, size):
    """วาดหมุดวงกลมทึบเป็นภาพ RGBA size x size ขอบเนียน (supersampling) ไม่แตะ Win32
    ถ้าไม่มี Pillow ให้ raise ImportError"""
    pil = _load_pil()
    if pil is None:
        raise ImportError("ไม่มี Pillow")
    Image, ImageDraw, ImageFont = pil
    ss = MARKER_SS
    big = size * ss
    k = size / MARKER_SIZE * ss  # px ที่ scale 100% -> px ในภาพใหญ่
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 1 * k  # ขอบเผื่อรอบวง ให้ขอบเนียนไม่โดนตัด
    border = 2 * k  # ขอบขาว ~2px
    d.ellipse([m, m, big - m, big - m], fill="white")
    d.ellipse([m + border, m + border, big - m - border, big - m - border], fill=color)
    for text, dy, px in marker_text_layout(n, repeat, size):
        d.text(
            (big / 2, big / 2 + dy * ss),
            text,
            fill="white",
            font=_marker_font(ImageFont, px * ss),
            anchor="mm",
        )
    lanczos = getattr(Image, "Resampling", Image).LANCZOS
    return img.resize((size, size), lanczos)


def premultiply_bgra(img):
    """RGBA -> ไบต์ BGRA แบบ premultiplied alpha (UpdateLayeredWindow ต้องการแบบนี้
    ถ้าไม่คูณ alpha ก่อน ขอบโปร่งครึ่งๆ จะสว่างผิด)"""
    src = img.tobytes()  # RGBA
    out = bytearray(len(src))
    for i in range(0, len(src), 4):
        r, g, b, a = src[i], src[i + 1], src[i + 2], src[i + 3]
        out[i] = (b * a + 127) // 255
        out[i + 1] = (g * a + 127) // 255
        out[i + 2] = (r * a + 127) // 255
        out[i + 3] = a
    return bytes(out)


def smooth_markers_available():
    """หมุดแบบเรียบใช้ได้ไหม (Windows + Pillow + user32/gdi32) ถ้าไม่ได้ใช้ Canvas แบบธรรมดา"""
    if sys.platform != "win32" or _load_pil() is None:
        return False
    try:
        _win32_api()
    except (OSError, AttributeError):
        return False
    return True


def make_layered(hwnd):
    """ตั้ง WS_EX_LAYERED ใหม่ (ล้างก่อนแล้วตั้ง) เพราะถ้าเคยมี SetLayeredWindowAttributes
    (เช่น Tk -alpha) UpdateLayeredWindow จะ fail จนกว่าจะล้างบิตนี้แล้วตั้งใหม่"""
    u = _win32_api().user32
    ex = u.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    u.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex & ~_WS_EX_LAYERED)
    u.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_LAYERED)


def update_layered(hwnd, bgra, w, h, x, y):
    """วาดภาพ BGRA (premultiplied) ลง layered window ที่ตำแหน่งจอ (x, y) ด้วย UpdateLayeredWindow
    คืน resource GDI ครบทุกตัวใน finally กัน leak ตอนสร้าง/ทำลายหมุดบ่อยๆ ถ้า fail ให้ raise OSError"""
    api = _win32_api()
    u, g = api.user32, api.gdi32
    screen = mem = hbmp = old = None
    try:
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        if not screen or not mem:
            raise OSError("GetDC/CreateCompatibleDC failed")
        bih = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down
        bits = ctypes.c_void_p()
        hbmp = g.CreateDIBSection(mem, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        if not hbmp or not bits.value:
            raise OSError("CreateDIBSection failed")
        ctypes.memmove(bits, bgra, w * h * 4)
        old = g.SelectObject(mem, hbmp)
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
        ok = u.UpdateLayeredWindow(
            hwnd,
            screen,
            ctypes.byref(_POINT(x, y)),
            ctypes.byref(_SIZE(w, h)),
            mem,
            ctypes.byref(_POINT(0, 0)),
            0,
            ctypes.byref(blend),
            _ULW_ALPHA,
        )
        if not ok:
            raise OSError(f"UpdateLayeredWindow failed ({ctypes.get_last_error()})")
    finally:
        if old:
            g.SelectObject(mem, old)
        if hbmp:
            g.DeleteObject(hbmp)
        if mem:
            g.DeleteDC(mem)
        if screen:
            u.ReleaseDC(None, screen)


class Marker(tk.Toplevel):
    """หมุดวงกลมทึบลอยบนจอ 1 อัน ต่อ 1 step ศูนย์กลาง = พิกัดของ step
    ลากเพื่อย้าย, คลิกเพื่อเลือกแถว, ดับเบิลคลิกเพื่อแก้ไข (ส่งต่อให้ App ตัดสิน)

    2 โหมด:
    - แบบเรียบ (smooth): วาดด้วย Pillow (supersampling) แล้วแสดงด้วย UpdateLayeredWindow
      ขอบเนียนด้วย per-pixel alpha ห้ามใช้ -transparentcolor ร่วม (ใช้ด้วยกันไม่ได้)
    - แบบธรรมดา: Canvas + -transparentcolor (ขอบเป็นพิกเซล) ใช้เมื่อแบบเรียบไม่พร้อม
      หรือ Win32 call ไหน fail หมุดต้องขึ้นเสมอ
    event bind ที่ Toplevel: canvas ของแบบธรรมดาก็ส่ง event มาถึง Toplevel ผ่าน bindtags"""

    def __init__(self, app, index, step):
        super().__init__(app.root)
        self.withdraw()  # สร้างแบบซ่อนไว้ก่อน App จะเป็นคนสั่งแสดง กันหมุดกะพริบตอนกำลังรัน
        self.app = app
        self.index = index
        self.home = (step["x"], step["y"])
        self.pos = self.home
        self._drag = None
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.size = marker_size(getattr(app, "marker_scale", 1.0))
        self.n, self.color, self.repeat = index + 1, MARKER_COLOR[step["type"]], step["repeat"]
        self.smooth = False
        self._bgra = None
        self._painted = False
        if getattr(app, "smooth_markers", False):
            try:
                self._bgra = premultiply_bgra(render_marker_image(self.n, self.color, self.repeat, self.size))
                # โปร่ง 100% ไว้ก่อน กันเห็นสี่เหลี่ยมพื้นเทาแวบหนึ่งตอน map ครั้งแรก ก่อนวาดด้วย ULW
                self.attributes("-alpha", 0.0)
                self.smooth = True
            except Exception as e:
                app.marker_fallback(e)
        if not self.smooth:
            self._build_canvas()
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", lambda e: app.on_marker_double(self.index))
        self.geometry(marker_geometry(*self.home, self.size))

    def _build_canvas(self):
        """แบบธรรมดา: วงกลมทึบบน Canvas พื้นสี transparentcolor"""
        try:
            self.attributes("-alpha", 1.0)
            self.attributes("-transparentcolor", MARKER_KEY)  # มีเฉพาะ Windows
        except tk.TclError:
            pass
        s = self.size
        k = s / MARKER_SIZE
        self.configure(bg=MARKER_KEY)
        c = tk.Canvas(self, width=s, height=s, bg=MARKER_KEY, highlightthickness=0, bd=0)
        c.pack()
        m, b = max(1, round(k)), max(2, round(2 * k))
        c.create_oval(m, m, s - m - 1, s - m - 1, fill=self.color, outline="white", width=b)
        for text, dy, px in marker_text_layout(self.n, self.repeat, s):
            # ขนาดฟอนต์ติดลบ = pixel (scale แล้ว ถ้าใช้ point Tk จะขยายตาม DPI ซ้ำอีกรอบ)
            c.create_text(s / 2, s / 2 + dy, text=text, fill="white", font=("Tahoma", -px, "bold"))

    def deiconify(self):
        super().deiconify()
        if self.smooth and not self._painted:
            # Tk สร้าง wrapper HWND ตอน map ครั้งแรก จึงวาดด้วย ULW ได้หลังจากนี้เท่านั้น
            try:
                self.update_idletasks()
                hwnd = int(self.wm_frame(), 16)
                make_layered(hwnd)
                c = self.size // 2
                update_layered(hwnd, self._bgra, self.size, self.size, self.pos[0] - c, self.pos[1] - c)
                self._painted = True
            except Exception as e:
                self.smooth = False
                self.app.marker_fallback(e)
                self._build_canvas()

    def snap_back(self):
        self.pos = self.home
        self.geometry(marker_geometry(*self.home, self.size))

    def _press(self, e):
        self._drag = (e.x_root, e.y_root, False)
        self.app.on_marker_click(self.index)

    def _motion(self, e):
        if self._drag is None or not self.app.can_drag_markers():
            return
        sx, sy, moved = self._drag
        dx, dy = e.x_root - sx, e.y_root - sy
        if not moved and abs(dx) < MARKER_DRAG_PX and abs(dy) < MARKER_DRAG_PX:
            return
        self._drag = (sx, sy, True)
        # ระหว่างลากขยับแค่หมุด ยังไม่แตะ step/ตาราง
        self.pos = (self.home[0] + dx, self.home[1] + dy)
        self.geometry(marker_geometry(*self.pos, self.size))

    def _release(self, e):
        drag, self._drag = self._drag, None
        if drag is not None and drag[2]:
            self.app.on_marker_drop(self.index, *self.pos)
