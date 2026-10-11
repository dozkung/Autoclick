"""ของที่เทสต์ใช้ร่วมกัน: stub tkinter/pynput, fake mouse/var และ helper สร้างข้อมูล
import ไฟล์นี้แล้ว sys.path จะชี้ไปที่ราก repo (import autoclicker ได้) แต่ยังไม่ใส่ stub"""

import os
import sys
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from autoclicker import constants, model  # ไม่ใช้ tkinter/pynput


def install_stubs():
    """ใส่ tkinter/pynput ปลอมใน sys.modules ต้องเรียกก่อน import module ที่ใช้ tkinter/pynput
    เรียกซ้ำได้ (ครั้งที่ 2 ไม่ทำอะไร) ส่วน model/screen/hotkeys ไม่ต้องใช้ stub"""
    if getattr(sys.modules.get("tkinter"), "_autoclicker_stub", False):
        return

    class _Any:
        """รับทุก argument ไม่ทำอะไร ใช้แทน class ของ tkinter/pynput ที่เทสต์ไม่ได้แตะ"""

        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            return lambda *a, **k: None

    # --- tkinter
    tk = types.ModuleType("tkinter")
    tk._autoclicker_stub = True
    tk.TclError = type("TclError", (Exception,), {})
    for name in ("Tk", "Toplevel", "StringVar", "IntVar", "DoubleVar", "BooleanVar"):
        setattr(tk, name, type(name, (_Any,), {}))
    ttk = types.ModuleType("tkinter.ttk")
    for name in (
        "Frame",
        "Label",
        "Button",
        "Entry",
        "Combobox",
        "Spinbox",
        "Treeview",
        "Scrollbar",
        "LabelFrame",
        "Radiobutton",
        "Checkbutton",
        "Style",
    ):
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

    sys.modules.update(
        {
            "tkinter": tk,
            "tkinter.ttk": ttk,
            "tkinter.filedialog": filedialog,
            "tkinter.messagebox": messagebox,
            "tkinter.font": font,
            "pynput": pynput,
            "pynput.keyboard": keyboard,
            "pynput.mouse": mouse,
        }
    )


VK_F6, VK_F7, VK_F8, VK_1, VK_A = 0x75, 0x76, 0x77, 0x31, 0x41
VK_LSHIFT, VK_RSHIFT, VK_LCTRL, VK_RCTRL, VK_LALT = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4


class FakeMouse:
    """แทน pynput.mouse.Controller บันทึกทุกการคลิกพร้อมพิกัดตอนนั้น"""

    def __init__(self, pos=(500, 500)):
        self._lock = threading.Lock()
        self._pos = pos
        self.log = []  # (action, button, count, (x, y)) เฉพาะปุ่มเมาส์
        self.events = []  # (kind, (x, y), เวลา) ทุกอย่างรวม move/nudge ไว้เช็กลำดับ
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


def step(x, y, ctype="left", delay_ms=10, hold_ms=0, repeat=1, gap_ms=constants.DEFAULT_GAP_MS):
    return model.make_step(x, y, ctype, delay_ms, hold_ms, repeat, gap_ms)


class FakeVar:
    def __init__(self, v=None):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class FakeWidget:
    def __init__(self):
        self.text = None

    def configure(self, **k):
        self.text = k.get("text", self.text)


def parse_geometry(g):
    """ "48x48+-1944+-24" -> (w, h, x, y)"""
    import re

    w, h, x, y = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", g).groups()
    return int(w), int(h), int(x), int(y)


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
