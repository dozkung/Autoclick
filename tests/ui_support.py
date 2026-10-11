"""fake ของฝั่ง UI (App/Marker/Listener) import ไฟล์นี้แล้ว stub tkinter/pynput จะถูกใส่ให้อัตโนมัติ"""

import queue
import types

import support

support.install_stubs()

from autoclicker import constants, model
from autoclicker import hotkeys as hotkeys_mod
from autoclicker.ui import app as app_mod
from support import SET_ONLY, FakeMouse, FakeVar, FakeWidget


class FakeMarker:
    """แทน Marker (Toplevel) บันทึกการซ่อน/แสดง/ดีดกลับลง log ที่แชร์กับ test"""

    def __init__(self, index, log):
        self.index, self.log, self.visible = index, log, False

    def withdraw(self):
        self.visible = False
        self.log.append(("withdraw", self.index))

    def deiconify(self):
        self.visible = True
        self.log.append(("deiconify", self.index))

    def snap_back(self):
        self.log.append(("snap_back", self.index))

    def destroy(self):
        self.log.append(("destroy", self.index))


class FakeTree:
    def __init__(self):
        self.selected = None

    def selection_set(self, iid):
        self.selected = iid

    def see(self, iid):
        pass

    def exists(self, iid):
        return False


class FakeApp(app_mod.App):
    """App ที่ข้าม __init__ (ไม่สร้าง Tk) ใส่แค่ attribute ที่ method ต่างๆ ใช้"""

    def __init__(self, steps):
        self.log = []
        self.runner = None
        self.steps = list(steps)
        self.status = FakeVar()
        self.mode, self.rounds, self.minutes = FakeVar("loop"), FakeVar(10), FakeVar(5.0)
        self.jit_px, self.jit_ms = FakeVar(0), FakeVar(0)
        self.def_type, self.def_delay = FakeVar(constants.CLICK_LABEL["left"]), FakeVar(500)
        self.def_delay_unit = FakeVar("ms")
        self.def_repeat = FakeVar(1)
        self.hover = FakeVar(50)
        self.countdown, self.pause_switch = FakeVar(3), FakeVar(True)
        self.show_markers = FakeVar(True)
        self.markers_suspended = False
        self.smooth_markers, self._marker_warned, self.marker_scale = False, False, 1.0
        self.hotkeys = {a: dict(hk) for a, hk in constants.DEFAULT_HOTKEYS.items()}
        self.matcher = hotkeys_mod.HotkeyMatcher(self.hotkeys, read_mods=SET_ONLY)
        self.kb = None
        self.hotkey_dialog = None
        self.key_capture = None
        self.settings_file = None
        self.hint_lbl, self.markers_chk = FakeWidget(), FakeWidget()
        self.running_row = None
        self.markers = []
        self.q = queue.Queue()
        self.mouse = FakeMouse()
        self.tree = FakeTree()
        self.root = types.SimpleNamespace(
            update_idletasks=lambda: self.log.append("update_idletasks"), after=lambda *a: None
        )
        self.run_btn = FakeWidget()

    def refresh(self, select=None):
        # แทน refresh จริง: สร้าง FakeMarker ตามจำนวน steps เหมือน _rebuild_markers
        self.log.append(("refresh", select))
        for m in self.markers:
            m.destroy()
        # เหมือน _rebuild_markers จริง: step กดปุ่มไม่มีหมุด
        self.markers = [FakeMarker(i, self.log) for i, s in enumerate(self.steps) if not model.is_key_step(s)]
        self._apply_markers()


def fake_app(steps):
    return FakeApp(steps)


class FakeListener:
    instances = []

    def __init__(self, on_press=None, on_release=None):
        self.on_press, self.on_release = on_press, on_release
        self.running = False
        self.daemon = False
        FakeListener.instances.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def join(self, timeout=None):
        pass
