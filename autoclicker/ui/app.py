"""หน้าต่างหลัก (App): ตารางจุด, ตั้งค่า, รัน/หยุด, ปุ่มลัด, หมุดบนจอ และ save/load
import pynput: main.py ต้องตั้ง DPI awareness ก่อน import module นี้"""

import json
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pynput import keyboard
from pynput import mouse as pmouse

from ..constants import (
    APP_NAME,
    CLICK_LABEL,
    CLICK_TYPES,
    DEFAULT_SETTINGS,
    DEFAULT_STEP_KEY,
    FILE_VERSION,
    LABEL_TO_TYPE,
    MAX_COUNTDOWN_S,
    MAX_HOVER_MS,
    MAX_JITTER_MS,
    MAX_JITTER_PX,
    MAX_REPEAT,
    TIME_UNITS,
)
from ..hotkeys import (
    HotkeyMatcher,
    hotkey_labels,
    key_to_vk,
    load_hotkeys,
    save_hotkeys,
    settings_path,
    validate_hotkeys,
)
from ..markers import Marker, smooth_markers_available
from ..model import (
    find_key_conflict,
    is_key_step,
    make_key_step,
    make_step,
    parse_profile,
    pick_unit,
    step_row,
    to_ms,
    try_move_step,
    validate_step,
)
from ..runner import Runner, format_status
from ..screen import get_virtual_origin, get_virtual_rect, in_corner, out_of_screen, window_dpi_scale
from .dialogs import HotkeyDialog, StepDialog


class App:
    def __init__(self, root):
        self.root = root
        self.mouse = pmouse.Controller()
        self.steps = []
        self.runner = None
        self.running_row = None  # index ของแถวที่ runner กำลังคลิก (ไฮไลต์ด้วย tag ไม่ใช้ selection)
        self.markers = []  # หมุดบนจอ สร้างใหม่ใน refresh() เท่านั้น
        self.markers_suspended = False  # True ระหว่างรัน: ซ่อนหมุดไม่ให้ clicker คลิกโดนหมุดเอง
        self.q = queue.Queue()  # ข้อความจากเธรดอื่น (hotkey/runner) -> UI เธรดหลัก
        self.settings_file = settings_path()
        self.hotkeys, hotkey_warning = load_hotkeys(self.settings_file)
        self.kb = None
        self.matcher = None
        self.hotkey_dialog = None
        self.key_capture = None  # StepDialog ที่รอจับปุ่มสำหรับ step กดปุ่ม (รับคีย์ผ่าน listener เดียวกัน)

        self.marker_scale = self._marker_dpi_scale()
        self.smooth_markers = False  # ตั้งจริงใน _init_marker_mode หลังมี status bar
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
        for text, cmd in [
            ("เพิ่มเอง", self.add_manual),
            ("เพิ่มปุ่มคีย์บอร์ด…", self.add_key_step),
            ("แก้ไข", self.edit_step),
            ("▲ ขึ้น", lambda: self.move(-1)),
            ("▼ ลง", lambda: self.move(1)),
            ("ลบ", self.delete_step),
            ("ล้างทั้งหมด", self.clear_steps),
        ]:
            ttk.Button(side, text=text, command=cmd, width=16).pack(pady=2)

        # ---- settings
        st = ttk.LabelFrame(r, text="ตั้งค่า", padding=10)
        st.pack(fill="x", padx=10)

        ttk.Label(st, text="ค่าเริ่มต้นจุดใหม่:").grid(row=0, column=0, sticky="w")
        self.def_type = tk.StringVar(value=CLICK_LABEL["left"])
        ttk.Combobox(
            st,
            textvariable=self.def_type,
            state="readonly",
            width=11,
            values=[CLICK_LABEL[t] for t in CLICK_TYPES],
        ).grid(row=0, column=1, padx=4)
        ttk.Label(st, text="รอ").grid(row=0, column=2)
        df = ttk.Frame(st)
        df.grid(row=0, column=3, padx=4)
        self.def_delay = tk.StringVar(value="500")  # ตัวเลขตามหน่วยใน def_delay_unit (รับทศนิยม)
        self.def_delay_unit = tk.StringVar(value="ms")
        ttk.Spinbox(df, from_=0, to=1_000_000, increment=1, textvariable=self.def_delay, width=7).pack(
            side="left"
        )
        ttk.Combobox(
            df, textvariable=self.def_delay_unit, state="readonly", values=list(TIME_UNITS), width=6
        ).pack(side="left", padx=(2, 0))
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
        ttk.Radiobutton(mf, text="จำนวนรอบ", variable=self.mode, value="count").pack(
            side="left", padx=(10, 2)
        )
        ttk.Spinbox(mf, from_=1, to=1_000_000, textvariable=self.rounds, width=7).pack(side="left")
        ttk.Radiobutton(mf, text="จำกัดเวลา (นาที)", variable=self.mode, value="time").pack(
            side="left", padx=(10, 2)
        )
        ttk.Spinbox(mf, from_=0.1, to=10_000, increment=0.5, textvariable=self.minutes, width=7).pack(
            side="left"
        )

        ttk.Label(st, text="สุ่มเพี้ยน:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        jf = ttk.Frame(st)
        jf.grid(row=2, column=1, columnspan=4, sticky="w", pady=(8, 0))
        self.jit_px = tk.IntVar(value=0)
        self.jit_ms = tk.IntVar(value=0)
        ttk.Label(jf, text="± พิกัด (px)").pack(side="left")
        ttk.Spinbox(jf, from_=0, to=50, textvariable=self.jit_px, width=5).pack(side="left", padx=(2, 12))
        ttk.Label(jf, text="± เวลา (ms)").pack(side="left")
        ttk.Spinbox(jf, from_=0, to=5000, increment=10, textvariable=self.jit_ms, width=6).pack(
            side="left", padx=2
        )
        self.hover = tk.IntVar(value=DEFAULT_SETTINGS["hover_ms"])
        ttk.Label(jf, text="รอ hover (ms)").pack(side="left", padx=(12, 0))
        ttk.Spinbox(jf, from_=0, to=MAX_HOVER_MS, increment=10, textvariable=self.hover, width=5).pack(
            side="left", padx=2
        )

        ttk.Label(st, text="ตอนเริ่ม:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        sf = ttk.Frame(st)
        sf.grid(row=3, column=1, columnspan=4, sticky="w", pady=(8, 0))
        self.countdown = tk.IntVar(value=DEFAULT_SETTINGS["countdown_s"])
        ttk.Label(sf, text="นับถอยหลัง (วิ)").pack(side="left")
        ttk.Spinbox(sf, from_=0, to=MAX_COUNTDOWN_S, textvariable=self.countdown, width=4).pack(
            side="left", padx=(2, 12)
        )
        self.pause_switch = tk.BooleanVar(value=DEFAULT_SETTINGS["pause_on_switch"])
        ttk.Checkbutton(sf, text="หยุดเมื่อสลับหน้าต่าง", variable=self.pause_switch).pack(side="left")

        self.topmost = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            st,
            text="หน้าต่างอยู่บนสุด",
            variable=self.topmost,
            command=lambda: r.attributes("-topmost", self.topmost.get()),
        ).grid(row=0, column=5, sticky="e", padx=(16, 0))
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
        # step กดปุ่มไม่มีพิกัด จึงไม่มีหมุด (Marker.index ยังเป็น index ใน steps เลขบนหมุดตรงกับตาราง)
        self.markers = [Marker(self, i, s) for i, s in enumerate(self.steps) if not is_key_step(s)]
        self._apply_markers()

    def _marker(self, i):
        """หมุดของ step ที่ index i (None ถ้า step นั้นไม่มีหมุด) markers ไม่ได้เรียงตรง index เสมอไป"""
        return next((m for m in self.markers if m.index == i), None)

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
        marker = self._marker(i)
        if not self.can_drag_markers():
            if marker:
                marker.snap_back()
            self.status.set("หยุดก่อนค่อยลากหมุด")
            return
        ok, reason = try_move_step(self.steps, i, x, y, get_virtual_origin(), get_virtual_rect())
        if ok:
            self.refresh(select=i)
        elif marker:
            marker.snap_back()
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
        return make_step(
            x,
            y,
            LABEL_TO_TYPE[self.def_type.get()],
            self._default_delay_ms(),
            repeat=self._safe_int(self.def_repeat, 1),
        )

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
        d = StepDialog(self.root, init, "เพิ่มจุด", app=self)
        self.root.wait_window(d)
        if d.result:
            self.steps.append(d.result)
            self.refresh(select=len(self.steps) - 1)

    def add_key_step(self):
        try:
            delay = self._default_delay_ms()
        except ValueError:
            delay = 500  # ช่องรอผิด ใช้ค่าตั้งต้นไปก่อน แก้ใน dialog ได้
        init = make_key_step(DEFAULT_STEP_KEY, delay_ms=delay, repeat=self._safe_int(self.def_repeat, 1))
        d = StepDialog(self.root, init, "เพิ่มปุ่มคีย์บอร์ด", app=self)
        self.root.wait_window(d)
        if d.result:
            self.steps.append(d.result)
            self.refresh(select=len(self.steps) - 1)

    def edit_step(self, i=None):
        if i is None:
            i = self._sel()
        if i is None or not 0 <= i < len(self.steps):
            return
        d = StepDialog(self.root, self.steps[i], f"แก้ไขจุด #{i + 1}", app=self)
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
        return {
            "mode": mode,
            "rounds": max(1, self._safe_int(self.rounds, 10)),
            "minutes": max(0.01, minutes),
            "jitter_px": min(MAX_JITTER_PX, max(0, self._safe_int(self.jit_px, 0))),
            "jitter_ms": min(MAX_JITTER_MS, max(0, self._safe_int(self.jit_ms, 0))),
            "hover_ms": min(MAX_HOVER_MS, max(0, self._safe_int(self.hover, DEFAULT_SETTINGS["hover_ms"]))),
            "countdown_s": min(
                MAX_COUNTDOWN_S, max(0, self._safe_int(self.countdown, DEFAULT_SETTINGS["countdown_s"]))
            ),
            "pause_on_switch": bool(self.pause_switch.get()),
        }

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
            if is_key_step(s):  # กดปุ่มไม่มีพิกัด ไม่ต้องเช็กจอ/มุม
                continue
            if out_of_screen(s["x"], s["y"], rect):
                self.status.set(f"จุด #{n} อยู่นอกจอ (ถอดจอออก?)")
                return
            if in_corner(s["x"], s["y"], origin):
                self.status.set(f"จุด #{n} อยู่ในมุม kill switch แก้ก่อนค่อยเริ่ม")
                return
        # step กดปุ่มห้ามตรงกับปุ่มลัด ไม่งั้นโปรแกรมกดปุ่มหยุดตัวเอง (โปรไฟล์อาจเซฟไว้ตอนปุ่มลัดเป็นค่าอื่น)
        conflict = find_key_conflict(self.steps, self.hotkeys)
        if conflict:
            self.status.set(conflict)
            return
        self._suspend_markers(True)  # ต้องซ่อนก่อน start ไม่งั้น clicker คลิกโดนหมุดแทนแอปเป้าหมาย
        self.runner = Runner(
            self.steps,
            self._cfg(),
            self.mouse,
            on_status=lambda rnd, i, k, n: self.q.put(("status", rnd, i, k, n)),
            on_done=lambda reason: self.q.put(("done", reason)),
            on_notice=lambda text: self.q.put(("notice", text)),
            origin=origin,
        )
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

    def begin_key_capture(self, sink):
        """ให้ sink (StepDialog) รับปุ่มถัดไปที่กด ผ่าน pynput listener ตัวเดียวกับปุ่มลัด
        (vk ชุดเดียวกับที่ matcher ใช้) ระหว่างรอ ปุ่มลัดทุกตัวปิดชั่วคราว"""
        self.key_capture = sink
        self.matcher.paused = True

    def end_key_capture(self):
        self.key_capture = None
        if self.hotkey_dialog is None:  # HotkeyDialog เปิดอยู่ก็ต้องปิดปุ่มลัดต่อ
            self.matcher.paused = False

    # ---------- cross-thread plumbing
    def _on_press(self, key, injected=False):
        # callback นี้รันใน thread ของ pynput ห้ามเรียก tkinter ตรงๆ (ถ้าเรียกจะ crash แบบสุ่ม)
        if injected:
            # ปุ่มที่โปรแกรมส่งเอง (step กดปุ่ม) ห้ามไปโดนปุ่มลัด pynput >= 1.8 ส่ง flag นี้มา
            # pynput เก่าไม่ส่ง (= False ตลอด) ยังมีการเช็กปุ่มชนปุ่มลัดตอนตั้ง step / ตอนกดเริ่มกันไว้อีกชั้น
            return
        m = self.matcher
        action = m.press(key_to_vk(key))
        if action == "add":
            self.q.put(("add", *self.mouse.position))
        elif action:
            self.q.put((action,))
        elif m.paused and m.last_combo is not None:
            self.q.put(("captured", m.last_combo))  # ให้ HotkeyDialog ที่รอจับคีย์อยู่

    def _on_release(self, key, injected=False):
        if injected:
            return
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
                    sink = self.hotkey_dialog or getattr(self, "key_capture", None)
                    if sink is not None:
                        sink.on_captured(msg[1])
                elif kind in ("status", "notice"):
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
            if last_status[0] == "notice":  # นับถอยหลัง / หยุดชั่วคราว: ข้อความล้วน ไม่ไฮไลต์แถว
                self.status.set(last_status[1])
            else:
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
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("AutoClicker profile", "*.json")]
        )
        if not path:
            return
        try:
            data = {
                "version": FILE_VERSION,
                "steps": self.steps,
                "settings": self._cfg(),
                "defaults": {
                    "type": LABEL_TO_TYPE[self.def_type.get()],
                    "delay_ms": self._default_delay_ms(),  # ไฟล์เก็บเป็น ms เสมอ
                    "repeat": self._safe_int(self.def_repeat, 1),
                },
            }
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
        self.countdown.set(cfg["countdown_s"])
        self.pause_switch.set(cfg["pause_on_switch"])
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
