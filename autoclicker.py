"""
AutoClicker — multi-point auto clicker สำหรับ Windows

ปุ่มลัด (ใช้ได้ทั้งตอนหน้าต่างไม่ได้ focus, ตั้งเองได้ที่ปุ่ม "ปุ่มลัด…")
  F6  = เริ่ม / หยุด                  (ค่าเริ่มต้น)
  F8  = เพิ่มจุดที่ตำแหน่งเมาส์ตอนนี้    (ค่าเริ่มต้น)
  F7  = แสดง / ซ่อนหมุดบนจอ            (ค่าเริ่มต้น)
  เอาเมาส์ชนมุมซ้ายบนสุดของจอ (virtual screen รวมทุกจอ) = หยุดฉุกเฉิน (kill switch)
"""
import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
import types
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont


def _set_dpi_aware():
    # ต้องเรียกก่อนสร้างหน้าต่างหรืออ่านพิกัดเมาส์
    # ถ้าไม่เรียก จอที่ตั้ง scaling 125/150% จะได้พิกัดคลาดจากจุดจริง
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_set_dpi_aware()

from pynput import keyboard  # noqa: E402  (ต้อง import หลังตั้ง DPI)
from pynput import mouse as pmouse  # noqa: E402
from pynput.mouse import Button  # noqa: E402

APP_NAME = "AutoClicker"
FILE_VERSION = 1
CORNER = 3            # px: เมาส์เข้ามุมซ้ายบนของ virtual screen ในระยะนี้ถือว่าสั่งหยุดฉุกเฉิน
MIN_DELAY_MS = 10     # กัน delay 0 ไม่ให้ลูปเปล่ากิน CPU 100%
MAX_JITTER_PX = 50
MAX_JITTER_MS = 5000
KILL_REASON = "หยุดฉุกเฉิน (เมาส์ชนมุมซ้ายบนสุดของจอ)"

CLICK_TYPES = ["left", "right", "double", "hold"]
CLICK_LABEL = {"left": "คลิกซ้าย", "right": "คลิกขวา", "double": "ดับเบิลคลิก", "hold": "กดค้าง"}
LABEL_TO_TYPE = {v: k for k, v in CLICK_LABEL.items()}
MODES = ("loop", "count", "time")
DEFAULT_SETTINGS = {"mode": "loop", "rounds": 10, "minutes": 5.0, "jitter_px": 0, "jitter_ms": 0,
                    "hover_ms": 50}
MAX_HOVER_MS = 1000        # รอ hover หลังย้ายเมาส์ก่อนคลิก (เกมอัปเดต hover ทีละเฟรม ~16ms)
DEFAULT_DEFAULTS = {"type": "left", "delay_ms": 500, "repeat": 1}
MAX_DURATION_MS = 86_400_000  # 24 ชม. กันพิมพ์ผิดหน่วยแล้วโปรแกรมรอเป็นปี
TIME_UNITS = {"ms": 1, "วินาที": 1000, "นาที": 60000}  # หน่วยใน UI (ข้อมูลภายในเป็น ms เสมอ)
MAX_REPEAT = 1000          # คลิกซ้ำที่จุดเดียวได้สูงสุดกี่ครั้ง
DEFAULT_GAP_MS = 100       # เว้นระหว่างคลิกแต่ละครั้งในจุดเดียวกัน
MAX_GAP_MS = 60000

MARKER_SIZE = 30           # ขนาดหน้าต่างหมุด (px ที่ scaling 100%): วงกลม ~28px + ขอบเผื่อ 1px ต่อด้าน
MARKER_DRAG_PX = 3         # ขยับน้อยกว่านี้ถือว่าเป็นคลิก ไม่ใช่ลาก
MARKER_KEY = "#ff00fe"     # สีพื้นหลังที่ใช้เป็น -transparentcolor (ห้ามซ้ำกับสีหมุด)
MARKER_COLOR = {"left": "#1e6fd9", "right": "#f08c00", "double": "#7b3fe4", "hold": "#d62828"}

# ปุ่มลัดเก็บเป็น {"mods": [...], "vk": int} ใช้ Windows virtual key code ไม่ใช้ตัวอักษร
# เพราะคีย์บอร์ดไทยตัวอักษรเปลี่ยนตามภาษา (A -> ฟ) แต่ vk เท่าเดิม
SETTINGS_VERSION = 1
HOTKEY_ACTIONS = ("toggle", "add", "markers")
HOTKEY_LABEL = {"toggle": "เริ่ม / หยุด", "add": "เพิ่มจุดที่เมาส์", "markers": "แสดง / ซ่อนหมุด"}
MOD_ORDER = ("ctrl", "alt", "shift")
MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
VK_ESCAPE = 0x1B
# modifier ซ้าย/ขวา/กลาง นับเป็นตัวเดียวกัน (pynput บน Windows ส่ง L/R มา: Key.shift = 0xA0)
VK_TO_MOD = {0x10: "shift", 0xA0: "shift", 0xA1: "shift",
             0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
             0x12: "alt", 0xA4: "alt", 0xA5: "alt"}
VK_WIN = (0x5B, 0x5C)  # ปุ่ม Windows ระบบจองไว้ ไม่รับเป็นปุ่มลัด
DEFAULT_HOTKEYS = {"toggle": {"mods": [], "vk": 0x75},   # F6
                   "add": {"mods": [], "vk": 0x77},      # F8
                   "markers": {"mods": [], "vk": 0x76}}  # F7 (F9 ชน Developer Console ของ Roblox)


# ----------------------------------------------------------------- model
def get_virtual_origin():
    """มุมซ้ายบนของ virtual screen (รวมทุกจอ) ถ้ามีจอเสริมอยู่ทางซ้าย/บน ค่าจะติดลบ
    ขอบนี้คือจุดที่เมาส์ไปต่อไม่ได้จริง เลยใช้เป็น kill switch ได้"""
    if sys.platform != "win32":
        return (0, 0)
    try:
        gsm = ctypes.windll.user32.GetSystemMetrics
        return (int(gsm(76)), int(gsm(77)))  # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN
    except Exception:
        return (0, 0)


def get_virtual_rect():
    """(vx, vy, cx, cy) ของ virtual screen (รวมทุกจอ) ถ้าไม่ใช่ Windows หรืออ่านไม่ได้คืน None"""
    if sys.platform != "win32":
        return None
    try:
        gsm = ctypes.windll.user32.GetSystemMetrics
        # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
        vx, vy, cx, cy = (int(gsm(i)) for i in (76, 77, 78, 79))
    except Exception:
        return None
    if cx <= 0 or cy <= 0:  # GetSystemMetrics คืน 0 เมื่อเรียกไม่สำเร็จ
        return None
    return (vx, vy, cx, cy)


def out_of_screen(x, y, rect):
    """จุดอยู่นอก virtual screen ไหม (เช่นถอดจอที่จุดนั้นอยู่ออกไปแล้ว) rect เป็น None = ไม่เช็ก"""
    if rect is None:
        return False
    vx, vy, cx, cy = rect
    return not (vx <= x <= vx + cx - 1 and vy <= y <= vy + cy - 1)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]  # MOUSEINPUT ใหญ่สุดใน union อยู่แล้ว ขนาด INPUT จึงถูก
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001


def nudge_mouse():
    """ส่ง mouse-move จริง (SendInput แบบ relative +1px แล้ว -1px) ให้แอปเป้าหมายรู้ว่าเมาส์ย้ายแล้ว
    pynput ย้ายเมาส์ด้วย SetCursorPos (วาร์ป) ซึ่งไม่เกิด move event เกมอย่าง Roblox ที่อัปเดต hover
    จาก move event จึงยังคิดว่าเมาส์อยู่ที่เดิม แล้วคลิกไปลงที่ตำแหน่ง hover เก่า
    ไม่ใช่ Windows หรือเรียกไม่ได้ให้ข้ามเงียบๆ"""
    if sys.platform != "win32":
        return
    try:
        inputs = (_INPUT * 2)()
        for inp, dx in zip(inputs, (1, -1)):
            inp.type = _INPUT_MOUSE
            inp.mi.dx = dx
            inp.mi.dwFlags = _MOUSEEVENTF_MOVE
        ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(_INPUT))
    except Exception:
        pass


def in_corner(x, y, origin=(0, 0)):
    vx, vy = origin
    return vx <= x <= vx + CORNER and vy <= y <= vy + CORNER


def make_step(x, y, ctype="left", delay_ms=500, hold_ms=500, repeat=1, gap_ms=DEFAULT_GAP_MS):
    return {"x": x, "y": y, "type": ctype, "delay_ms": delay_ms, "hold_ms": hold_ms,
            "repeat": repeat, "gap_ms": gap_ms}


def _int_field(d, key, default=None):
    v = d.get(key, default)
    if v is None:
        raise ValueError(f"ไม่มีค่า {key}")
    if isinstance(v, bool) or not isinstance(v, int):  # bool เป็น subclass ของ int ต้องกันเอง
        raise ValueError(f"{key} ต้องเป็นจำนวนเต็ม: {v!r}")
    return v


def validate_step(d, origin=(0, 0)):
    """ตรวจ step (จากไฟล์หรือ dialog) คืน step ที่ใช้ได้ ถ้าข้อมูลพังให้ raise ValueError
    origin=None = ข้ามการเช็กโซน kill switch (ใช้ตอนโหลดไฟล์ ให้โหลดขึ้นมาแก้ได้ ไปเช็กตอนกดเริ่มแทน)"""
    if not isinstance(d, dict):
        raise ValueError(f"ข้อมูลจุดต้องเป็น object: {d!r}")
    x, y = _int_field(d, "x"), _int_field(d, "y")
    ctype = d.get("type", "left")
    if ctype not in CLICK_TYPES:
        raise ValueError(f"ประเภทคลิกไม่รู้จัก: {ctype}")
    delay_ms = _int_field(d, "delay_ms", 500)
    hold_ms = _int_field(d, "hold_ms", 500)
    if delay_ms < MIN_DELAY_MS:
        raise ValueError(f"รอหลังกดต้องไม่น้อยกว่า {MIN_DELAY_MS} ms")
    if delay_ms > MAX_DURATION_MS:
        raise ValueError("รอหลังกดต้องไม่เกิน 24 ชม.")
    if hold_ms < 0:
        raise ValueError("กดค้างนานต้องไม่ติดลบ")
    if hold_ms > MAX_DURATION_MS:
        raise ValueError("กดค้างนานต้องไม่เกิน 24 ชม.")
    # ไฟล์โปรไฟล์เก่าไม่มี repeat/gap_ms ใช้ค่าเริ่มต้น
    repeat = _int_field(d, "repeat", 1)
    gap_ms = _int_field(d, "gap_ms", DEFAULT_GAP_MS)
    if not 1 <= repeat <= MAX_REPEAT:
        raise ValueError(f"จำนวนครั้งต้องอยู่ระหว่าง 1–{MAX_REPEAT}")
    if not MIN_DELAY_MS <= gap_ms <= MAX_GAP_MS:
        raise ValueError(f"เว้นระหว่างครั้งต้องอยู่ระหว่าง {MIN_DELAY_MS}–{MAX_GAP_MS} ms")
    if origin is not None and in_corner(x, y, origin):
        raise ValueError(f"จุด ({x}, {y}) อยู่ในมุม kill switch")
    return make_step(x, y, ctype, delay_ms, hold_ms, repeat, gap_ms)


def parse_profile(data, origin=None):
    """ตรวจไฟล์โปรไฟล์ทั้งก้อนให้ผ่านหมดก่อน คืน (steps, settings, defaults)
    ยังไม่แตะ state ของโปรแกรม ถ้ามีอะไรพังให้ raise ValueError
    ปกติไม่เช็กโซน kill switch (origin=None) เพราะ toggle() เช็กตอนกดเริ่มอยู่แล้ว"""
    if not isinstance(data, dict):
        raise ValueError("ไฟล์โปรไฟล์ต้องเป็น JSON object")
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise ValueError("steps ต้องเป็น list")
    steps = []
    for n, s in enumerate(raw_steps, 1):
        try:
            steps.append(validate_step(s, origin))
        except ValueError as e:
            raise ValueError(f"จุด #{n}: {e}") from e

    raw = data.get("settings", {})
    if not isinstance(raw, dict):
        raise ValueError("settings ต้องเป็น object")
    st = dict(DEFAULT_SETTINGS)
    st["mode"] = raw.get("mode", st["mode"])
    if st["mode"] not in MODES:
        raise ValueError(f"mode ไม่รู้จัก: {st['mode']}")
    st["rounds"] = _int_field(raw, "rounds", st["rounds"])
    if st["rounds"] < 1:
        raise ValueError("rounds ต้องไม่น้อยกว่า 1")
    minutes = raw.get("minutes", st["minutes"])
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not minutes > 0:
        raise ValueError(f"minutes ต้องเป็นตัวเลขมากกว่า 0: {minutes!r}")
    st["minutes"] = float(minutes)
    st["jitter_px"] = _int_field(raw, "jitter_px", st["jitter_px"])
    if not 0 <= st["jitter_px"] <= MAX_JITTER_PX:
        raise ValueError(f"jitter_px ต้องอยู่ระหว่าง 0–{MAX_JITTER_PX}")
    st["jitter_ms"] = _int_field(raw, "jitter_ms", st["jitter_ms"])
    if not 0 <= st["jitter_ms"] <= MAX_JITTER_MS:
        raise ValueError(f"jitter_ms ต้องอยู่ระหว่าง 0–{MAX_JITTER_MS}")
    st["hover_ms"] = _int_field(raw, "hover_ms", st["hover_ms"])  # ไฟล์เก่าไม่มี -> 50
    if not 0 <= st["hover_ms"] <= MAX_HOVER_MS:
        raise ValueError(f"hover_ms ต้องอยู่ระหว่าง 0–{MAX_HOVER_MS}")

    raw = data.get("defaults", {})
    if not isinstance(raw, dict):
        raise ValueError("defaults ต้องเป็น object")
    dflt = dict(DEFAULT_DEFAULTS)
    dflt["type"] = raw.get("type", dflt["type"])
    if dflt["type"] not in CLICK_TYPES:
        raise ValueError(f"defaults.type ไม่รู้จัก: {dflt['type']}")
    dflt["delay_ms"] = _int_field(raw, "delay_ms", dflt["delay_ms"])
    if not MIN_DELAY_MS <= dflt["delay_ms"] <= MAX_DURATION_MS:
        raise ValueError(f"defaults.delay_ms ต้องอยู่ระหว่าง {MIN_DELAY_MS}–{MAX_DURATION_MS}")
    dflt["repeat"] = _int_field(raw, "repeat", dflt["repeat"])
    if not 1 <= dflt["repeat"] <= MAX_REPEAT:
        raise ValueError(f"defaults.repeat ต้องอยู่ระหว่าง 1–{MAX_REPEAT}")
    return steps, st, dflt


def to_ms(value_str, unit):
    """แปลงค่าที่กรอกใน UI (รับทศนิยม เช่น "1.5" วินาที) เป็น ms
    ใช้ round() ไม่ใช่ int() เพราะ 0.29*1000 = 289.999... จะได้ 289"""
    if unit not in TIME_UNITS:
        raise ValueError(f"หน่วยไม่รู้จัก: {unit}")
    try:
        v = float(str(value_str).strip())
    except ValueError:
        raise ValueError(f"ต้องเป็นตัวเลข: {value_str!r}") from None
    if v != v or v in (float("inf"), float("-inf")):  # nan / inf
        raise ValueError(f"ต้องเป็นตัวเลข: {value_str!r}")
    if v < 0:
        raise ValueError("ต้องไม่ติดลบ")
    return round(v * TIME_UNITS[unit])


def pick_unit(ms):
    """เลือกหน่วยที่อ่านง่ายสุดสำหรับค่าเดิม (ใช้ตอนเปิด dialog) คืน (value, unit)"""
    if ms > 0 and ms % 60000 == 0:
        return ms // 60000, "นาที"
    if ms > 0 and ms % 1000 == 0:
        return ms // 1000, "วินาที"
    return ms, "ms"


def _fmt_sec(ms):
    return f"{ms / 1000:.3f}".rstrip("0").rstrip(".")


def format_duration(ms):
    """แสดงเวลาในตาราง: "500 ms" / "1.5 วิ" / "2 นาที" / "1 นาที 30 วิ" """
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60000:
        return f"{_fmt_sec(ms)} วิ"
    minutes, rest = divmod(ms, 60000)
    return f"{minutes} นาที" if rest == 0 else f"{minutes} นาที {_fmt_sec(rest)} วิ"


def step_row(n, s):
    """ค่าของ 1 แถวในตาราง (n = เลขลำดับที่คำนวณจากตำแหน่ง) ช่องที่ไม่ใช้กับจุดนี้แสดง "-" """
    return (n, s["x"], s["y"], CLICK_LABEL[s["type"]], s["repeat"],
            format_duration(s["gap_ms"]) if s["repeat"] > 1 else "-",
            format_duration(s["hold_ms"]) if s["type"] == "hold" else "-",
            format_duration(s["delay_ms"]))


def step_from_form(form):
    """แปลงค่าจาก StepDialog (string ทั้งหมด + หน่วย) เป็น step ยังไม่ validate กติกา
    ข้อความ error บอกชื่อช่อง ผู้ใช้จะได้รู้ว่าผิดตรงไหน"""
    def as_int(key, label):
        try:
            return int(str(form[key]).strip())
        except ValueError:
            raise ValueError(f"{label} ต้องเป็นจำนวนเต็ม") from None

    def as_ms(key, label):
        try:
            return to_ms(form[key], form[key + "_unit"])
        except ValueError as e:
            raise ValueError(f"{label}: {e}") from None

    return make_step(as_int("x", "X"), as_int("y", "Y"), LABEL_TO_TYPE[form["type"]],
                     as_ms("delay_ms", "รอหลังครั้งสุดท้าย"), as_ms("hold_ms", "กดค้างนาน"),
                     as_int("repeat", "จำนวนครั้ง"), as_ms("gap_ms", "เว้นระหว่างครั้ง"))


def format_status(rnd, i, k, n):
    """ข้อความ status ระหว่างรัน คลิกจุดเดียวหลายครั้งให้บอกครั้งที่ (k/n) ด้วย"""
    text = f"รอบ {rnd} · จุด #{i}"
    return f"{text} ({k}/{n})" if n > 1 else text


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
        return [(str(n), -3.5 * k, max(6, round(num_px * k))),
                (f"×{repeat}", 6.5 * k, max(5, round(rep_px * k)))]
    num_px = {1: 14, 2: 12}.get(digits, 10)
    return [(str(n), 0.0, max(6, round(num_px * k)))]


# ------------------------------------------------- smooth markers (Pillow)
MARKER_SS = 4  # supersampling: วาดใหญ่ 4 เท่าแล้วย่อ ได้ขอบเนียน
_FONT_FILES = (r"C:\Windows\Fonts\tahomabd.ttf", r"C:\Windows\Fonts\arialbd.ttf",
               r"C:\Windows\Fonts\segoeuib.ttf")


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
    m = 1 * k                  # ขอบเผื่อรอบวง ให้ขอบเนียนไม่โดนตัด
    border = 2 * k             # ขอบขาว ~2px
    d.ellipse([m, m, big - m, big - m], fill="white")
    d.ellipse([m + border, m + border, big - m - border, big - m - border], fill=color)
    for text, dy, px in marker_text_layout(n, repeat, size):
        d.text((big / 2, big / 2 + dy * ss), text, fill="white",
               font=_marker_font(ImageFont, px * ss), anchor="mm")
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


# ---------------------------------------------- Win32 per-pixel alpha window
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_ULW_ALPHA = 0x02
_AC_SRC_OVER, _AC_SRC_ALPHA = 0x00, 0x01
_win32 = None


def _win32_api():
    """user32/gdi32 ที่ตั้ง argtypes/restype ครบ (handle เป็น 64-bit ถ้าปล่อยเป็น int จะโดนตัด)
    ใช้ WinDLL ของตัวเอง ไม่แก้ ctypes.windll ที่ส่วนอื่น (pynput) ใช้ร่วม"""
    global _win32
    if _win32 is None:
        from ctypes import wintypes as wt
        u = ctypes.WinDLL("user32", use_last_error=True)
        g = ctypes.WinDLL("gdi32", use_last_error=True)
        H = ctypes.c_void_p
        u.GetDC.argtypes, u.GetDC.restype = [wt.HWND], H
        u.ReleaseDC.argtypes, u.ReleaseDC.restype = [wt.HWND, H], ctypes.c_int
        u.GetWindowLongPtrW.argtypes, u.GetWindowLongPtrW.restype = [wt.HWND, ctypes.c_int], ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.UpdateLayeredWindow.argtypes = [wt.HWND, H, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE), H,
                                          ctypes.POINTER(_POINT), wt.DWORD,
                                          ctypes.POINTER(_BLENDFUNCTION), wt.DWORD]
        u.UpdateLayeredWindow.restype = wt.BOOL
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [H], H
        g.CreateDIBSection.argtypes = [H, ctypes.POINTER(_BITMAPINFOHEADER), wt.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
        g.CreateDIBSection.restype = H
        g.SelectObject.argtypes, g.SelectObject.restype = [H, H], H
        g.DeleteObject.argtypes, g.DeleteObject.restype = [H], wt.BOOL
        g.DeleteDC.argtypes, g.DeleteDC.restype = [H], wt.BOOL
        try:
            u.GetDpiForWindow.argtypes, u.GetDpiForWindow.restype = [wt.HWND], wt.UINT
        except AttributeError:  # Windows เก่ากว่า 10 1607
            pass
        _win32 = types.SimpleNamespace(user32=u, gdi32=g)
    return _win32


def smooth_markers_available():
    """หมุดแบบเรียบใช้ได้ไหม (Windows + Pillow + user32/gdi32) ถ้าไม่ได้ใช้ Canvas แบบธรรมดา"""
    if sys.platform != "win32" or _load_pil() is None:
        return False
    try:
        _win32_api()
    except (OSError, AttributeError):
        return False
    return True


def window_dpi_scale(hwnd):
    """GetDpiForWindow(hwnd)/96 ถ้าเรียกไม่ได้คืน None"""
    try:
        dpi = _win32_api().user32.GetDpiForWindow(hwnd)
    except (OSError, AttributeError):
        return None
    return dpi / 96 if dpi else None


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
        ok = u.UpdateLayeredWindow(hwnd, screen, ctypes.byref(_POINT(x, y)), ctypes.byref(_SIZE(w, h)),
                                   mem, ctypes.byref(_POINT(0, 0)), 0, ctypes.byref(blend), _ULW_ALPHA)
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


def try_move_step(steps, index, x, y, origin, rect):
    """ย้ายจุดที่ index ไป (x, y) คืน (ok, reason) ถ้าไม่ผ่านจะไม่แตะ steps"""
    if not 0 <= index < len(steps):
        return False, f"ไม่มีจุด #{index + 1}"
    if out_of_screen(x, y, rect):
        return False, f"ย้ายจุด #{index + 1} ไม่ได้: ({x}, {y}) อยู่นอกจอ"
    try:
        moved = validate_step(dict(steps[index], x=x, y=y), origin)
    except ValueError as e:
        return False, f"ย้ายจุด #{index + 1} ไม่ได้: {e}"
    steps[index] = moved
    return True, f"ย้ายจุด #{index + 1} ไป ({x}, {y})"


# --------------------------------------------------------------- hotkeys
_VK_NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "CapsLock",
             0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
             0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2C: "PrintScreen",
             0x2D: "Insert", 0x2E: "Delete", 0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -",
             0x6E: "Num .", 0x6F: "Num /", 0x90: "NumLock", 0x91: "ScrollLock",
             0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
             0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}


def vk_name(vk):
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:  # 0-9, A-Z (ชื่ออังกฤษเสมอ ไม่ขึ้นกับภาษาที่เลือก)
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    return _VK_NAMES.get(vk, f"VK 0x{vk:02X}")


def hotkey_to_text(hk):
    return "+".join([MOD_LABEL[m] for m in MOD_ORDER if m in hk["mods"]] + [vk_name(hk["vk"])])


def parse_hotkey(data):
    """ตรวจ + normalize ปุ่มลัด 1 ปุ่ม คืน {"mods": [...ตามลำดับ MOD_ORDER], "vk": int}"""
    if not isinstance(data, dict):
        raise ValueError(f"ปุ่มลัดต้องเป็น object: {data!r}")
    vk = data.get("vk")
    if isinstance(vk, bool) or not isinstance(vk, int) or not 1 <= vk <= 254:
        raise ValueError(f"vk ไม่ถูกต้อง: {vk!r}")
    mods = data.get("mods", [])
    if not isinstance(mods, list) or any(m not in MOD_ORDER for m in mods):
        raise ValueError(f"mods ไม่ถูกต้อง: {mods!r}")
    if vk in VK_TO_MOD:
        raise ValueError("ใช้ Ctrl/Alt/Shift เดี่ยวๆ เป็นปุ่มลัดไม่ได้")
    if vk == VK_ESCAPE:
        raise ValueError("ใช้ Esc เป็นปุ่มลัดไม่ได้")
    if vk in VK_WIN:
        raise ValueError("ใช้ปุ่ม Windows เป็นปุ่มลัดไม่ได้")
    return {"mods": [m for m in MOD_ORDER if m in mods], "vk": vk}


def _hotkey_id(hk):
    return (frozenset(hk["mods"]), hk["vk"])


def validate_hotkeys(d):
    """ตรวจปุ่มลัดครบทุกหน้าที่ ห้ามซ้ำกัน คืน dict ที่ normalize แล้ว"""
    if not isinstance(d, dict):
        raise ValueError("hotkeys ต้องเป็น object")
    if set(d) != set(HOTKEY_ACTIONS):
        raise ValueError(f"hotkeys ต้องมีครบ {', '.join(HOTKEY_ACTIONS)} พอดี")
    out, seen = {}, {}
    for action in HOTKEY_ACTIONS:
        try:
            hk = parse_hotkey(d[action])
        except ValueError as e:
            raise ValueError(f"{HOTKEY_LABEL[action]}: {e}") from e
        key = _hotkey_id(hk)
        if key in seen:
            raise ValueError(f"{hotkey_to_text(hk)} ซ้ำกันระหว่าง "
                             f"'{HOTKEY_LABEL[seen[key]]}' กับ '{HOTKEY_LABEL[action]}'")
        seen[key] = action
        out[action] = hk
    return out


def assign_hotkey(hotkeys, action, hk):
    """ตั้งปุ่มให้หน้าที่ action คืน dict ใหม่ (ไม่แก้ของเดิม) ถ้าไม่ผ่านหรือซ้ำให้ raise ValueError"""
    hk = parse_hotkey(hk)
    for other, cur in hotkeys.items():
        if other != action and _hotkey_id(cur) == _hotkey_id(hk):
            raise ValueError(f"{hotkey_to_text(hk)} ใช้กับ '{HOTKEY_LABEL[other]}' อยู่แล้ว")
    return dict(hotkeys, **{action: hk})


def key_to_vk(key):
    """pynput key -> vk: KeyCode มี .vk ตรงๆ ส่วน Key.xxx ต้องอ่านจาก .value.vk"""
    vk = getattr(key, "vk", None)
    if vk is None:
        vk = getattr(getattr(key, "value", None), "vk", None)
    return vk


_ASYNC_MODS = ((0x11, "ctrl"), (0x12, "alt"), (0x10, "shift"))  # VK_CONTROL, VK_MENU, VK_SHIFT


def read_modifiers_async():
    """modifier ที่กดอยู่จริงตอนนี้ (GetAsyncKeyState) คืน set หรือ None ถ้าอ่านไม่ได้
    แม่นกว่านับจาก event press/release เพราะ event ตอนปล่อยอาจหาย (Win+L, UAC)"""
    if sys.platform != "win32":
        return None
    try:
        gaks = ctypes.windll.user32.GetAsyncKeyState
        return {m for vk, m in _ASYNC_MODS if gaks(vk) & 0x8000}
    except Exception:
        return None


class HotkeyMatcher:
    """รับ press/release (vk) จาก listener แล้วบอกว่าปุ่มลัดไหน trigger
    trigger เฉพาะตอนกดลงครั้งแรก (autorepeat ตอนกดค้างไม่นับ) และ modifier ต้องกดค้างไว้ก่อน
    read_mods: ฟังก์ชันคืน set ของ modifier ที่กดอยู่ (หรือ None = อ่านไม่ได้ ใช้ set self.down แทน)"""

    def __init__(self, hotkeys, read_mods=None):
        self.down = set()  # ใช้กัน autorepeat และเป็น fallback ของ modifier
        self.paused = False
        self.last_combo = None  # คอมโบล่าสุดที่กด (ไว้ให้ dialog จับคีย์ใช้)
        self.read_mods = read_mods or read_modifiers_async
        self._map = {_hotkey_id(hk): action for action, hk in hotkeys.items()}

    def _current_mods(self):
        try:
            mods = self.read_mods()
        except Exception:
            mods = None
        if mods is None:
            mods = {VK_TO_MOD[v] for v in self.down if v in VK_TO_MOD}
        return mods

    def press(self, vk):
        self.last_combo = None
        if vk is None:
            return None
        first = vk not in self.down
        self.down.add(vk)
        if not first or vk in VK_TO_MOD:
            return None
        mods = self._current_mods()
        self.last_combo = {"mods": [m for m in MOD_ORDER if m in mods], "vk": vk}
        if self.paused:  # ยังเก็บ down ไว้ ปลด pause แล้วปุ่มที่ค้างอยู่จะได้ไม่ trigger
            return None
        return self._map.get((frozenset(mods), vk))

    def release(self, vk):
        self.down.discard(vk)


def settings_path():
    """ไฟล์ค่าของเครื่อง (ไม่ใช่ของโปรไฟล์) %APPDATA%\\AutoClicker\\settings.json"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "settings.json")


def load_hotkeys(path):
    """คืน (hotkeys, warning) ไม่มีไฟล์ = ค่าเริ่มต้นเงียบๆ, ไฟล์พัง = ค่าเริ่มต้น + warning
    ห้าม raise เด็ดขาด ไม่งั้นโปรแกรมเปิดไม่ขึ้น"""
    defaults = {a: dict(hk) for a, hk in DEFAULT_HOTKEYS.items()}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return defaults, None
    except (OSError, ValueError) as e:
        return defaults, f"อ่านไฟล์ตั้งค่าปุ่มลัดไม่ได้ ใช้ค่าเริ่มต้นแทน ({e})"
    try:
        if not isinstance(data, dict):
            raise ValueError("ไฟล์ต้องเป็น JSON object")
        raw = data.get("hotkeys", {})
        if not isinstance(raw, dict):
            raise ValueError("hotkeys ต้องเป็น object")
        merged = dict(DEFAULT_HOTKEYS, **raw)  # หน้าที่ไหนไม่มีในไฟล์ใช้ค่าเริ่มต้น
        return validate_hotkeys(merged), None
    except ValueError as e:
        return defaults, f"ปุ่มลัดในไฟล์ตั้งค่าไม่ถูกต้อง ใช้ค่าเริ่มต้นแทน ({e})"


def save_hotkeys(path, hotkeys):
    """เขียนแบบ .tmp แล้ว os.replace ไฟล์จะได้ไม่พังครึ่งๆ ถ้าโปรแกรมตายกลางทาง"""
    hotkeys = validate_hotkeys(hotkeys)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": SETTINGS_VERSION, "hotkeys": hotkeys}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def hotkey_labels(hotkeys):
    """ข้อความทุกจุดบน UI ที่โชว์ชื่อปุ่มลัด รวมไว้ที่เดียว เปลี่ยนปุ่มแล้วอัปเดตตามได้ครบ"""
    t = {a: hotkey_to_text(hk) for a, hk in hotkeys.items()}
    return {
        "header": (f"{t['toggle']} = เริ่ม/หยุด    {t['add']} = เพิ่มจุดที่เมาส์    "
                   f"{t['markers']} = แสดง/ซ่อนหมุด    เมาส์ชนมุมซ้ายบนสุดของจอ = หยุดฉุกเฉิน"),
        "start": f"▶ เริ่ม ({t['toggle']})",
        "stop": f"■ หยุด ({t['toggle']})",
        "markers": f"แสดงหมุด ({t['markers']})",
        "no_steps": f"ยังไม่มีจุด กด {t['add']} ที่ตำแหน่งที่จะคลิกก่อน",
    }


# ---------------------------------------------------------------- runner
class Runner(threading.Thread):
    """เธรดที่สั่งคลิกจริง ห้ามแตะ tkinter ในนี้ ให้ส่งข้อความผ่าน callback (ซึ่งใช้ queue) แทน"""

    def __init__(self, steps, cfg, mouse_ctl, on_status, on_done, origin=(0, 0), nudge=None):
        super().__init__(daemon=True)
        self.steps = [dict(s) for s in steps]  # snapshot: ระหว่างรันแก้ตารางได้ ไม่ชนกับเธรดนี้
        self.cfg = cfg
        self.origin = origin  # มุมซ้ายบนของ virtual screen ตอนกดเริ่ม
        self.nudge = nudge or nudge_mouse  # inject ได้ เทสต์จะได้ไม่ไปขยับเมาส์จริง
        self.mouse = mouse_ctl
        self.on_status = on_status
        self.on_done = on_done
        self.stop_evt = threading.Event()
        self.reason = "หยุดแล้ว"
        self.deadline = None
        self._held = None

    def stop(self, reason="หยุดแล้ว"):
        if not self.stop_evt.is_set():
            self.reason = reason
            self.stop_evt.set()

    def _wait(self, sec):
        """รอแบบแบ่งช่วงสั้นๆ ไม่ใช้ time.sleep(sec) ตรงๆ
        เพราะถ้า delay ตั้งไว้ 30 วินาที กดหยุดแล้วต้องรอให้ครบก่อนถึงจะหยุดได้"""
        end = time.monotonic() + max(0.0, sec)
        while True:
            if self.stop_evt.is_set():
                return False
            x, y = self.mouse.position
            if in_corner(x, y, self.origin):
                self.stop(KILL_REASON)
                return False
            now = time.monotonic()
            if self.deadline is not None and now >= self.deadline:
                self.stop("ครบเวลาที่ตั้งไว้")
                return False
            left = end - now
            if left <= 0:
                return True
            self.stop_evt.wait(min(left, 0.02))

    def _click(self, s):
        """คลิก 1 ครั้งตาม type (สุ่มพิกัดใหม่ทุกครั้ง) คืน False ถ้าโดนหยุดระหว่างรอ hover หรือกดค้าง
        ลำดับ: วาร์ปเมาส์ -> ส่ง move event จริง -> รอ hover -> (ตั้งตำแหน่งซ้ำถ้าเพี้ยน) -> คลิก"""
        jp = self.cfg["jitter_px"]
        x = s["x"] + (random.randint(-jp, jp) if jp else 0)
        y = s["y"] + (random.randint(-jp, jp) if jp else 0)
        if in_corner(x, y, self.origin):  # จิตเตอร์ห้ามเหวี่ยงเมาส์เข้ามุม ไม่งั้นจะไปชน kill switch เอง
            vx, vy = self.origin
            x, y = max(x, vx + CORNER + 1), max(y, vy + CORNER + 1)
        self.mouse.position = (x, y)
        try:
            self.nudge()  # SetCursorPos ไม่มี move event เกมบางตัว (Roblox) จะไม่อัปเดต hover
        except Exception:
            pass  # nudge พังแค่เสี่ยงคลิกไม่โดนในบางเกม ไม่ใช่เหตุให้หยุดทั้งงาน
        # รอให้แอปเป้าหมายอัปเดต hover ก่อนคลิก (รอผ่าน _wait: หยุด/kill switch ได้ระหว่างรอ)
        if not self._wait(self.cfg["hover_ms"] / 1000):
            return False
        if tuple(self.mouse.position) != (x, y):
            # Enhance pointer precision อาจทำให้ +1/-1 ไม่หักล้างกันพอดี ตั้งตำแหน่งซ้ำให้เป๊ะก่อนคลิก
            # เช็กหลังรอ hover เพราะ SendInput เข้าคิวแบบ async อ่านทันทีอาจยังไม่เห็นผล
            self.mouse.position = (x, y)
        t = s["type"]
        if t == "left":
            self.mouse.click(Button.left)
        elif t == "right":
            self.mouse.click(Button.right)
        elif t == "double":
            self.mouse.click(Button.left, 2)
        elif t == "hold":
            self.mouse.press(Button.left)
            self._held = Button.left
            try:
                return self._wait(s["hold_ms"] / 1000)
            finally:
                # ต้องปล่อยเสมอ ถึงจะโดนหยุดกลางคันก็ตาม ไม่งั้นปุ่มเมาส์ค้างทั้งเครื่อง
                self.mouse.release(Button.left)
                self._held = None
        return True

    def _run_step(self, rnd, i, s):
        """คลิกจุดเดียวซ้ำ repeat ครั้ง เว้น gap_ms ระหว่างครั้ง แล้วรอ delay_ms หลังครั้งสุดท้าย
        คืน False ถ้าโดนหยุด (stop / kill switch / deadline) กลางทาง"""
        n = s["repeat"]
        jm = self.cfg["jitter_ms"]
        for k in range(1, n + 1):
            if not self._wait(0):
                return False
            self.on_status(rnd, i, k, n)
            if not self._click(s):
                return False
            wait = s["delay_ms"] if k == n else s["gap_ms"]
            wait += random.uniform(-jm, jm) if jm else 0
            if not self._wait(max(MIN_DELAY_MS, wait) / 1000):
                return False
        return True

    def run(self):
        cfg = self.cfg
        rnd = 0
        try:
            if not self.steps:  # ไม่มีจุดแล้วปล่อยวน loop จะเป็นลูปเปล่ากิน CPU 100%
                raise ValueError("ไม่มีจุดให้คลิก")
            if cfg["mode"] == "time":
                self.deadline = time.monotonic() + cfg["minutes"] * 60
            while not self.stop_evt.is_set():
                rnd += 1
                if cfg["mode"] == "count" and rnd > cfg["rounds"]:
                    self.reason = f"ครบ {cfg['rounds']} รอบ"
                    break
                for i, s in enumerate(self.steps, 1):
                    if not self._run_step(rnd, i, s):
                        break
        except Exception as e:  # เธรดตายเงียบๆ แย่สุด ต้องโชว์ให้เห็นบน UI
            self.reason = f"error: {e}"
        finally:
            if self._held is not None:
                try:
                    self.mouse.release(self._held)
                except Exception:
                    pass
            self.on_done(self.reason)


# -------------------------------------------------------------------- UI
class StepDialog(tk.Toplevel):
    def __init__(self, master, step, title):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.vars = {
            "x": tk.StringVar(value=str(step["x"])),
            "y": tk.StringVar(value=str(step["y"])),
            "type": tk.StringVar(value=CLICK_LABEL[step["type"]]),
            "repeat": tk.StringVar(value=str(step["repeat"])),
        }
        for key in ("delay_ms", "hold_ms", "gap_ms"):  # ช่องเวลา: ตัวเลข + หน่วย เลือกหน่วยจากค่าเดิม
            value, unit = pick_unit(step[key])
            self.vars[key] = tk.StringVar(value=str(value))
            self.vars[key + "_unit"] = tk.StringVar(value=unit)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        rows = [("X", "x"), ("Y", "y"), ("ประเภท", "type"),
                ("จำนวนครั้ง", "repeat"), ("เว้นระหว่างครั้ง", "gap_ms"),
                ("รอหลังครั้งสุดท้าย", "delay_ms"), ("กดค้างนาน", "hold_ms")]
        for r, (lbl, key) in enumerate(rows):
            ttk.Label(f, text=lbl).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            if key == "type":
                w = ttk.Combobox(f, textvariable=self.vars[key], state="readonly",
                                 values=[CLICK_LABEL[t] for t in CLICK_TYPES], width=14)
            else:
                w = ttk.Entry(f, textvariable=self.vars[key], width=10)
            w.grid(row=r, column=1, sticky="ew", pady=3)
            if key + "_unit" in self.vars:
                ttk.Combobox(f, textvariable=self.vars[key + "_unit"], state="readonly",
                             values=list(TIME_UNITS), width=6).grid(row=r, column=2, padx=(4, 0), pady=3)
        bf = ttk.Frame(f)
        bf.grid(row=len(rows), column=0, columnspan=3, pady=(10, 0))
        ttk.Button(bf, text="ตกลง", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="ยกเลิก", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _ok(self):
        try:
            # แปลงหน่วยเป็น ms ก่อน แล้วค่อย validate ด้วยกติกาเดิม (delay >= 10ms ฯลฯ)
            step = step_from_form({k: v.get() for k, v in self.vars.items()})
            step = validate_step(step, get_virtual_origin())
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e), parent=self)
            return
        self.result = step
        self.destroy()


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


class HotkeyDialog(tk.Toplevel):
    """ตั้งปุ่มลัด คีย์ที่กดมาจาก pynput listener (ผ่าน queue -> App._poll -> on_captured)
    ไม่ใช้ key event ของ Tk เพื่อให้ได้ vk ชุดเดียวกับที่ใช้ match ปุ่มลัดจริง"""
    PROMPT = "กดปุ่มที่ต้องการ… (Esc = ยกเลิก)"

    def __init__(self, app):
        super().__init__(app.root)
        self.title("ตั้งปุ่มลัด")
        self.resizable(False, False)
        self.transient(app.root)
        self.app = app
        self.work = dict(app.hotkeys)
        self.capturing = None  # หน้าที่ที่กำลังรอจับคีย์
        self.buttons = {}
        self.err = tk.StringVar()
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        for r, action in enumerate(HOTKEY_ACTIONS):
            ttk.Label(f, text=HOTKEY_LABEL[action]).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            b = ttk.Button(f, width=30, command=lambda a=action: self._capture(a))
            b.grid(row=r, column=1, sticky="ew", pady=3)
            self.buttons[action] = b
        ttk.Label(f, textvariable=self.err, foreground="#c00", wraplength=340).grid(
            row=len(HOTKEY_ACTIONS), column=0, columnspan=2, sticky="w", pady=(6, 0))
        bf = ttk.Frame(f)
        bf.grid(row=len(HOTKEY_ACTIONS) + 1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(bf, text="คืนค่าเริ่มต้น", command=self._reset).pack(side="left", padx=4)
        ttk.Button(bf, text="บันทึก", command=self._save).pack(side="left", padx=4)
        ttk.Button(bf, text="ยกเลิก", command=self.destroy).pack(side="left", padx=4)
        self._render()
        self.grab_set()

    def _render(self):
        for action, b in self.buttons.items():
            b.configure(text=self.PROMPT if action == self.capturing else hotkey_to_text(self.work[action]))

    def _capture(self, action):
        self.capturing = action
        self.err.set("")
        self._render()
        self.focus_set()  # ดึง focus ออกจากปุ่ม ไม่งั้นกด Space/Enter จะไปกดปุ่มใน dialog ซ้ำ

    def on_captured(self, hk):
        if self.capturing is None:
            return
        action, self.capturing = self.capturing, None
        if hk["vk"] != VK_ESCAPE:  # Esc = ยกเลิกการจับคีย์ ไม่ใช่ปุ่มลัด
            try:
                self.work = assign_hotkey(self.work, action, hk)
            except ValueError as e:
                self.err.set(str(e))
        self._render()

    def _reset(self):
        self.capturing = None
        self.work = {a: dict(hk) for a, hk in DEFAULT_HOTKEYS.items()}
        self.err.set("")
        self._render()

    def _save(self):
        try:
            self.app.apply_hotkeys(validate_hotkeys(self.work))
        except ValueError as e:
            self.err.set(str(e))
            return
        except OSError as e:
            self.err.set(f"บันทึกไฟล์ตั้งค่าไม่ได้: {e}")
            return
        self.destroy()


class App:
    def __init__(self, root):
        self.root = root
        self.mouse = pmouse.Controller()
        self.steps = []
        self.runner = None
        self.running_row = None  # index ของแถวที่ runner กำลังคลิก (ไฮไลต์ด้วย tag ไม่ใช้ selection)
        self.markers = []        # หมุดบนจอ สร้างใหม่ใน refresh() เท่านั้น
        self.markers_suspended = False  # True ระหว่างรัน: ซ่อนหมุดไม่ให้ clicker คลิกโดนหมุดเอง
        self.q = queue.Queue()  # ข้อความจากเธรดอื่น (hotkey/runner) -> UI เธรดหลัก
        self.settings_file = settings_path()
        self.hotkeys, hotkey_warning = load_hotkeys(self.settings_file)
        self.kb = None
        self.matcher = None
        self.hotkey_dialog = None

        self.marker_scale = self._marker_dpi_scale()
        self.smooth_markers = False   # ตั้งจริงใน _init_marker_mode หลังมี status bar
        self._marker_warned = False

        root.title(APP_NAME)
        root.minsize(640, 480)
        style = ttk.Style()
        style.configure("Treeview", rowheight=24)

        self._build_ui()
        self._update_hotkey_labels()
        if hotkey_warning:
            self.status.set(hotkey_warning)
        self._init_marker_mode()
        self._start_listener()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()
        self._tick_mouse()

    # ---------- layout
    def _build_ui(self):
        r = self.root
        top = ttk.Frame(r, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        self.hint_lbl = ttk.Label(top, foreground="#555")  # ข้อความตั้งใน _update_hotkey_labels
        self.hint_lbl.pack(side="left")
        self.pos_lbl = ttk.Label(top, text="เมาส์: -, -", width=18, anchor="e")
        self.pos_lbl.pack(side="right")

        mid = ttk.Frame(r, padding=10)
        mid.pack(fill="both", expand=True)
        cols = ("n", "x", "y", "type", "repeat", "gap", "hold", "delay")
        heads = ("#", "X", "Y", "ประเภท", "จำนวน", "เว้น", "ค้าง", "รอ")  # เวลาใช้ format_duration
        widths = (36, 60, 60, 96, 56, 80, 80, 96)
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("running", background="#ffe58f")
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit_step())
        self.tree.bind("<Delete>", lambda e: self.delete_step())

        side = ttk.Frame(mid, padding=(8, 0, 0, 0))
        side.pack(side="left", fill="y")
        for text, cmd in [("เพิ่มเอง", self.add_manual), ("แก้ไข", self.edit_step),
                          ("▲ ขึ้น", lambda: self.move(-1)), ("▼ ลง", lambda: self.move(1)),
                          ("ลบ", self.delete_step), ("ล้างทั้งหมด", self.clear_steps)]:
            ttk.Button(side, text=text, command=cmd, width=12).pack(pady=2)

        # ---- settings
        st = ttk.LabelFrame(r, text="ตั้งค่า", padding=10)
        st.pack(fill="x", padx=10)

        ttk.Label(st, text="ค่าเริ่มต้นจุดใหม่:").grid(row=0, column=0, sticky="w")
        self.def_type = tk.StringVar(value=CLICK_LABEL["left"])
        ttk.Combobox(st, textvariable=self.def_type, state="readonly", width=11,
                     values=[CLICK_LABEL[t] for t in CLICK_TYPES]).grid(row=0, column=1, padx=4)
        ttk.Label(st, text="รอ").grid(row=0, column=2)
        df = ttk.Frame(st)
        df.grid(row=0, column=3, padx=4)
        self.def_delay = tk.StringVar(value="500")  # ตัวเลขตามหน่วยใน def_delay_unit (รับทศนิยม)
        self.def_delay_unit = tk.StringVar(value="ms")
        ttk.Spinbox(df, from_=0, to=1_000_000, increment=1,
                    textvariable=self.def_delay, width=7).pack(side="left")
        ttk.Combobox(df, textvariable=self.def_delay_unit, state="readonly",
                     values=list(TIME_UNITS), width=6).pack(side="left", padx=(2, 0))
        rf = ttk.Frame(st)
        rf.grid(row=0, column=4, sticky="w")
        ttk.Label(rf, text="จำนวน").pack(side="left", padx=(4, 2))
        self.def_repeat = tk.IntVar(value=1)
        ttk.Spinbox(rf, from_=1, to=MAX_REPEAT, textvariable=self.def_repeat, width=5).pack(side="left")

        self.mode = tk.StringVar(value="loop")
        self.rounds = tk.IntVar(value=10)
        self.minutes = tk.DoubleVar(value=5)
        ttk.Label(st, text="การวน:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        mf = ttk.Frame(st)
        mf.grid(row=1, column=1, columnspan=4, sticky="w", pady=(8, 0))  # คอลัมน์ 5 เป็นของ checkbox
        ttk.Radiobutton(mf, text="ไม่จำกัด", variable=self.mode, value="loop").pack(side="left")
        ttk.Radiobutton(mf, text="จำนวนรอบ", variable=self.mode, value="count").pack(side="left", padx=(10, 2))
        ttk.Spinbox(mf, from_=1, to=1_000_000, textvariable=self.rounds, width=7).pack(side="left")
        ttk.Radiobutton(mf, text="จำกัดเวลา (นาที)", variable=self.mode, value="time").pack(side="left", padx=(10, 2))
        ttk.Spinbox(mf, from_=0.1, to=10_000, increment=0.5, textvariable=self.minutes, width=7).pack(side="left")

        ttk.Label(st, text="สุ่มเพี้ยน:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        jf = ttk.Frame(st)
        jf.grid(row=2, column=1, columnspan=4, sticky="w", pady=(8, 0))
        self.jit_px = tk.IntVar(value=0)
        self.jit_ms = tk.IntVar(value=0)
        ttk.Label(jf, text="± พิกัด (px)").pack(side="left")
        ttk.Spinbox(jf, from_=0, to=50, textvariable=self.jit_px, width=5).pack(side="left", padx=(2, 12))
        ttk.Label(jf, text="± เวลา (ms)").pack(side="left")
        ttk.Spinbox(jf, from_=0, to=5000, increment=10, textvariable=self.jit_ms, width=6).pack(side="left", padx=2)
        self.hover = tk.IntVar(value=DEFAULT_SETTINGS["hover_ms"])
        ttk.Label(jf, text="รอ hover (ms)").pack(side="left", padx=(12, 0))
        ttk.Spinbox(jf, from_=0, to=MAX_HOVER_MS, increment=10, textvariable=self.hover,
                    width=5).pack(side="left", padx=2)

        self.topmost = tk.BooleanVar(value=True)
        ttk.Checkbutton(st, text="หน้าต่างอยู่บนสุด", variable=self.topmost,
                        command=lambda: r.attributes("-topmost", self.topmost.get())).grid(
            row=0, column=5, sticky="e", padx=(16, 0))
        r.attributes("-topmost", True)
        self.show_markers = tk.BooleanVar(value=True)
        self.markers_chk = ttk.Checkbutton(st, variable=self.show_markers, command=self._apply_markers)
        self.markers_chk.grid(row=1, column=5, sticky="e", padx=(16, 0))

        # ---- bottom bar
        bot = ttk.Frame(r, padding=10)
        bot.pack(fill="x")
        self.run_btn = ttk.Button(bot, command=self.toggle, width=16)
        self.run_btn.pack(side="left")
        ttk.Button(bot, text="บันทึก…", command=self.save).pack(side="left", padx=(12, 4))
        ttk.Button(bot, text="เปิด…", command=self.load).pack(side="left")
        ttk.Button(bot, text="ปุ่มลัด…", command=self.open_hotkeys).pack(side="left", padx=(4, 0))
        self.status = tk.StringVar(value="พร้อม")
        ttk.Label(bot, textvariable=self.status, anchor="e").pack(side="right")

    # ---------- table helpers
    def refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.steps, 1):  # เลขลำดับคำนวณใหม่ทุกครั้ง ไม่เก็บไว้ใน data
            tags = ("running",) if self.running_row == i - 1 else ()
            self.tree.insert("", "end", iid=str(i - 1), tags=tags, values=step_row(i, s))
        if select is not None and 0 <= select < len(self.steps):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        self._rebuild_markers()

    # ---------- on-screen markers
    def _marker_dpi_scale(self):
        """หมุดขยายตาม DPI จะได้ไม่เล็กที่ 150%: GetDpiForWindow/96 -> tk scaling -> 1.0"""
        try:
            scale = window_dpi_scale(int(self.root.wm_frame(), 16))
        except (tk.TclError, ValueError, TypeError):
            scale = None
        if scale is None:
            try:
                scale = float(self.root.tk.call("tk", "scaling")) / (96 / 72)  # pixel ต่อ point
            except (tk.TclError, ValueError, TypeError):
                scale = 1.0
        return max(1.0, scale)

    def _init_marker_mode(self):
        self.smooth_markers = smooth_markers_available()
        if not self.smooth_markers:
            self.marker_fallback()

    def marker_fallback(self, err=None):
        """หมุดแบบเรียบใช้ไม่ได้ (ไม่มี Pillow / ไม่ใช่ Windows / Win32 fail) -> ใช้แบบธรรมดาตลอดที่เหลือ
        เตือนใน status ครั้งเดียว ห้ามทำให้โปรแกรมล้ม"""
        self.smooth_markers = False
        self.marker_fallback_reason = err  # เก็บไว้ดูตอน debug (status แสดงแค่ข้อความสั้น)
        if not self._marker_warned:
            self._marker_warned = True
            self.status.set("หมุดแบบเรียบไม่พร้อม ใช้แบบธรรมดา")

    def _rebuild_markers(self):
        # จุดเดียวที่สร้างหมุด: ทิ้งของเก่าให้หมดก่อน ไม่งั้นหน้าต่าง Toplevel จะรั่ว
        for m in self.markers:
            m.destroy()
        self.markers = [Marker(self, i, s) for i, s in enumerate(self.steps)]
        self._apply_markers()

    def _apply_markers(self):
        visible = self.show_markers.get() and not self.markers_suspended
        for m in self.markers:
            if visible:
                m.deiconify()
            else:
                m.withdraw()

    def _suspend_markers(self, suspended):
        self.markers_suspended = suspended
        self._apply_markers()
        if suspended:
            self.root.update_idletasks()  # ให้หมุดหายจากจอจริงก่อน runner เริ่มคลิก

    def toggle_markers(self):
        self.show_markers.set(not self.show_markers.get())
        self._apply_markers()

    def can_drag_markers(self):
        return not (self.markers_suspended or (self.runner and self.runner.is_alive()))

    def on_marker_click(self, i):
        if 0 <= i < len(self.steps):
            self.tree.selection_set(str(i))
            self.tree.see(str(i))

    def on_marker_double(self, i):
        self.edit_step(i)

    def on_marker_drop(self, i, x, y):
        if not self.can_drag_markers():
            self.markers[i].snap_back()
            self.status.set("หยุดก่อนค่อยลากหมุด")
            return
        ok, reason = try_move_step(self.steps, i, x, y, get_virtual_origin(), get_virtual_rect())
        if ok:
            self.refresh(select=i)
        else:
            self.markers[i].snap_back()
        self.status.set(reason)

    def _sel(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _safe_int(self, var, default):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    def _default_delay_ms(self):
        """ช่อง "รอ" ของค่าเริ่มต้นจุดใหม่ แปลงเป็น ms ถ้ากรอกผิดให้ raise ValueError"""
        try:
            return to_ms(self.def_delay.get(), self.def_delay_unit.get())
        except (ValueError, tk.TclError) as e:
            raise ValueError(f"ช่องรอของค่าเริ่มต้นจุดใหม่: {e}") from None

    def _new_step(self, x, y):
        """จุดใหม่ที่ใช้ค่าจากแถว "ค่าเริ่มต้นจุดใหม่" (ยังไม่ validate) ช่องรอกรอกผิด = raise ValueError"""
        return make_step(x, y, LABEL_TO_TYPE[self.def_type.get()],
                         self._default_delay_ms(), repeat=self._safe_int(self.def_repeat, 1))

    def add_at(self, x, y):
        origin = get_virtual_origin()
        if in_corner(x, y, origin):
            self.status.set("จุดนี้ชนมุม kill switch ไม่เพิ่มให้")
            return
        try:
            step = validate_step(self._new_step(x, y), origin)
        except ValueError as e:
            self.status.set(f"เพิ่มจุดไม่ได้: {e}")
            return
        self.steps.append(step)
        self.refresh(select=len(self.steps) - 1)
        self.status.set(f"เพิ่มจุด #{len(self.steps)} ที่ ({x}, {y})")

    def add_manual(self):
        try:
            init = self._new_step(100, 100)
        except ValueError:
            init = make_step(100, 100, LABEL_TO_TYPE[self.def_type.get()])  # ช่องรอผิด ใช้ค่าตั้งต้นไปก่อน
        d = StepDialog(self.root, init, "เพิ่มจุด")
        self.root.wait_window(d)
        if d.result:
            self.steps.append(d.result)
            self.refresh(select=len(self.steps) - 1)

    def edit_step(self, i=None):
        if i is None:
            i = self._sel()
        if i is None or not 0 <= i < len(self.steps):
            return
        d = StepDialog(self.root, self.steps[i], f"แก้ไขจุด #{i + 1}")
        self.root.wait_window(d)
        if d.result:
            self.steps[i] = d.result
            self.refresh(select=i)

    def move(self, delta):
        i = self._sel()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.steps):
            self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
            self.refresh(select=j)

    def delete_step(self):
        i = self._sel()
        if i is None:
            return
        del self.steps[i]
        self.refresh(select=min(i, len(self.steps) - 1))

    def clear_steps(self):
        if self.steps and messagebox.askyesno(APP_NAME, "ลบทุกจุด?"):
            self.steps.clear()
            self.refresh()

    # ---------- run control
    def _cfg(self):
        mode = self.mode.get()
        try:
            minutes = float(self.minutes.get())
        except (tk.TclError, ValueError):
            minutes = 5.0
        return {"mode": mode,
                "rounds": max(1, self._safe_int(self.rounds, 10)),
                "minutes": max(0.01, minutes),
                "jitter_px": min(MAX_JITTER_PX, max(0, self._safe_int(self.jit_px, 0))),
                "jitter_ms": min(MAX_JITTER_MS, max(0, self._safe_int(self.jit_ms, 0))),
                "hover_ms": min(MAX_HOVER_MS, max(0, self._safe_int(self.hover, DEFAULT_SETTINGS["hover_ms"])))}

    def toggle(self):
        if self.runner and self.runner.is_alive():
            self.runner.stop("หยุดโดยผู้ใช้")
            return
        if not self.steps:
            self.status.set(hotkey_labels(self.hotkeys)["no_steps"])
            return
        origin = get_virtual_origin()  # อ่านใหม่ทุกครั้ง เผื่อเสียบ/ถอดจอระหว่างใช้งาน
        rect = get_virtual_rect()
        for n, s in enumerate(self.steps, 1):
            if out_of_screen(s["x"], s["y"], rect):
                self.status.set(f"จุด #{n} อยู่นอกจอ (ถอดจอออก?)")
                return
            if in_corner(s["x"], s["y"], origin):
                self.status.set(f"จุด #{n} อยู่ในมุม kill switch แก้ก่อนค่อยเริ่ม")
                return
        self._suspend_markers(True)  # ต้องซ่อนก่อน start ไม่งั้น clicker คลิกโดนหมุดแทนแอปเป้าหมาย
        self.runner = Runner(self.steps, self._cfg(), self.mouse,
                             on_status=lambda rnd, i, k, n: self.q.put(("status", rnd, i, k, n)),
                             on_done=lambda reason: self.q.put(("done", reason)),
                             origin=origin)
        self.runner.start()
        self._update_hotkey_labels()
        self.status.set("กำลังรัน…")

    # ---------- hotkeys
    def _update_hotkey_labels(self):
        lb = hotkey_labels(self.hotkeys)
        self.hint_lbl.configure(text=lb["header"])
        self.markers_chk.configure(text=lb["markers"])
        # markers_suspended = สถานะรันฝั่ง UI (True ตั้งแต่กดเริ่มจนได้ "done")
        self.run_btn.configure(text=lb["stop"] if self.markers_suspended else lb["start"])

    def _start_listener(self):
        self.matcher = HotkeyMatcher(self.hotkeys)
        self.kb = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.kb.daemon = True
        self.kb.start()

    def _stop_listener(self):
        if self.kb is not None:
            self.kb.stop()
            try:
                self.kb.join(timeout=1)
            except RuntimeError:  # ยังไม่ได้ start
                pass
            self.kb = None

    def _restart_listener(self):
        # หยุดตัวเก่าให้จบก่อนค่อยสร้างตัวใหม่ ห้ามมี listener ค้างสองตัว
        self._stop_listener()
        self._start_listener()

    def apply_hotkeys(self, hotkeys):
        """เรียกจาก HotkeyDialog ตอนกดบันทึก เขียนไฟล์ไม่ได้ให้ OSError หลุดออกไปให้ dialog โชว์"""
        hotkeys = validate_hotkeys(hotkeys)
        save_hotkeys(self.settings_file, hotkeys)
        self.hotkeys = hotkeys
        self._restart_listener()
        self._update_hotkey_labels()
        self.status.set("บันทึกปุ่มลัดแล้ว")

    def open_hotkeys(self):
        if self.runner and self.runner.is_alive():
            self.status.set("หยุดก่อนค่อยตั้งปุ่มลัด")
            return
        self.matcher.paused = True  # ระหว่าง dialog เปิด ปุ่มลัดทุกตัวปิดชั่วคราว
        try:
            self.hotkey_dialog = HotkeyDialog(self)
            self.root.wait_window(self.hotkey_dialog)
        finally:
            self.hotkey_dialog = None
            self.matcher.paused = False  # ถ้ากดบันทึก matcher นี้คือตัวใหม่ (ไม่ได้ pause อยู่แล้ว)

    # ---------- cross-thread plumbing
    def _on_press(self, key):
        # callback นี้รันใน thread ของ pynput ห้ามเรียก tkinter ตรงๆ (ถ้าเรียกจะ crash แบบสุ่ม)
        m = self.matcher
        action = m.press(key_to_vk(key))
        if action == "add":
            self.q.put(("add", *self.mouse.position))
        elif action:
            self.q.put((action,))
        elif m.paused and m.last_combo is not None:
            self.q.put(("captured", m.last_combo))  # ให้ HotkeyDialog ที่รอจับคีย์อยู่

    def _on_release(self, key):
        self.matcher.release(key_to_vk(key))

    def _poll(self):
        last_status = None
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "toggle":
                    self.toggle()
                elif kind == "add":
                    if self.runner and self.runner.is_alive():
                        self.status.set("หยุดก่อนค่อยเพิ่มจุด")
                    else:
                        self.add_at(int(msg[1]), int(msg[2]))
                elif kind == "markers":
                    self.toggle_markers()
                elif kind == "captured":
                    if self.hotkey_dialog is not None:
                        self.hotkey_dialog.on_captured(msg[1])
                elif kind == "status":
                    last_status = msg  # คลิกถี่ๆ ไม่ต้องวาดทุกครั้ง เอาแค่ล่าสุดของรอบ poll นี้
                elif kind == "done":
                    last_status = None
                    self.status.set(msg[1])
                    self._mark_running(None)
                    # ใช้ flag แทน is_alive() เพราะ on_done ถูกเรียกใน finally ก่อนเธรดจบจริง
                    self._suspend_markers(False)
                    self._update_hotkey_labels()
        except queue.Empty:
            pass
        if last_status and self.runner and self.runner.is_alive():
            _, rnd, i, k, n = last_status
            self.status.set(format_status(rnd, i, k, n))
            self._mark_running(i - 1)
        self.root.after(30, self._poll)

    def _mark_running(self, row):
        # ไฮไลต์ด้วย tag แยกจาก selection ผู้ใช้จะได้เลือกแถวไปแก้ระหว่างรันได้โดยไม่โดนแย่ง
        if self.running_row is not None and self.tree.exists(str(self.running_row)):
            self.tree.item(str(self.running_row), tags=())
        self.running_row = row
        if row is not None and self.tree.exists(str(row)):
            self.tree.item(str(row), tags=("running",))

    def _tick_mouse(self):
        x, y = self.mouse.position
        self.pos_lbl.configure(text=f"เมาส์: {int(x)}, {int(y)}")
        self.root.after(100, self._tick_mouse)

    # ---------- save / load
    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("AutoClicker profile", "*.json")])
        if not path:
            return
        try:
            data = {"version": FILE_VERSION, "steps": self.steps, "settings": self._cfg(),
                    "defaults": {"type": LABEL_TO_TYPE[self.def_type.get()],
                                 "delay_ms": self._default_delay_ms(),  # ไฟล์เก็บเป็น ms เสมอ
                                 "repeat": self._safe_int(self.def_repeat, 1)}}
            # ตรวจด้วยตัวเดียวกับตอนโหลด ไฟล์ที่เซฟเองต้องโหลดกลับได้เสมอ
            parse_profile(data)
        except ValueError as e:
            messagebox.showerror(APP_NAME, f"บันทึกไม่ได้:\n{e}")
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"บันทึกไฟล์ไม่ได้:\n{e}")
            return
        self.status.set(f"บันทึกแล้ว ({len(self.steps)} จุด)")

    def load(self):
        if self.runner and self.runner.is_alive():
            self.status.set("หยุดก่อนค่อยเปิดไฟล์")
            return
        path = filedialog.askopenfilename(filetypes=[("AutoClicker profile", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            # validate ให้ครบทั้งไฟล์ก่อนค่อยเขียนทับ ถ้าไฟล์พังครึ่งๆ ของเดิมจะไม่หายไปด้วย
            steps, cfg, dflt = parse_profile(data)  # ไม่เช็กโซน kill switch ให้โหลดขึ้นมาแก้ได้
        except (OSError, ValueError) as e:  # JSONDecodeError/UnicodeDecodeError เป็น ValueError
            messagebox.showerror(APP_NAME, f"เปิดไฟล์ไม่ได้:\n{e}")
            return
        self.steps = steps
        self.mode.set(cfg["mode"])
        self.rounds.set(cfg["rounds"])
        self.minutes.set(cfg["minutes"])
        self.jit_px.set(cfg["jitter_px"])
        self.jit_ms.set(cfg["jitter_ms"])
        self.hover.set(cfg["hover_ms"])
        self.def_type.set(CLICK_LABEL[dflt["type"]])
        value, unit = pick_unit(dflt["delay_ms"])  # ไฟล์เก็บ ms เสมอ UI โชว์หน่วยที่อ่านง่ายสุด
        self.def_delay.set(value)
        self.def_delay_unit.set(unit)
        self.def_repeat.set(dflt["repeat"])
        self.refresh()
        self.status.set(f"โหลดแล้ว ({len(steps)} จุด)")

    def _on_close(self):
        if self.runner and self.runner.is_alive():
            self.runner.stop()
            self.runner.join(timeout=1)  # ให้มันปล่อยปุ่มที่กดค้างก่อนปิดโปรแกรม
        self._stop_listener()
        for m in self.markers:
            m.destroy()
        self.markers = []
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        # Tahoma มีตัวอักษรไทยครบบน Windows
        # widget ttk ไม่อ่าน *Font ต้องตั้งที่ named font ที่ ttk ใช้ด้วย
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkCaptionFont"):
            tkfont.nametofont(name).configure(family="Tahoma", size=10)
        root.option_add("*Font", ("Tahoma", 10))
        root.option_add("*TCombobox*Listbox.font", ("Tahoma", 10))
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
