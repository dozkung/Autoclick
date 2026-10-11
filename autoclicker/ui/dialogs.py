"""หน้าต่างย่อย: แก้ไข step คลิก/กดปุ่ม (StepDialog) และตั้งปุ่มลัด (HotkeyDialog)"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..constants import (
    APP_NAME,
    CLICK_LABEL,
    DEFAULT_HOTKEYS,
    DEFAULT_STEP_KEY,
    HOTKEY_ACTIONS,
    HOTKEY_LABEL,
    KEY_TYPE,
    LABEL_TO_TYPE,
    STEP_TYPES,
    TIME_UNITS,
    VK_ESCAPE,
)
from ..hotkeys import assign_hotkey, hotkey_conflict, hotkey_to_text, parse_hotkey, validate_hotkeys
from ..model import pick_unit, step_from_form, step_key, validate_step
from ..screen import get_virtual_origin


class StepDialog(tk.Toplevel):
    """เพิ่ม/แก้ไข step 1 ตัว ประเภท "กดปุ่ม" จะซ่อนช่อง X/Y แล้วโชว์ปุ่ม "เลือกปุ่ม…" แทน
    การจับปุ่มใช้ pynput listener ของ App (app.begin_key_capture) เหมือน HotkeyDialog"""

    KEY_PROMPT = "กดปุ่มที่ต้องการ… (Esc = ยกเลิก)"

    def __init__(self, master, step, title, app=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.app = app
        self.capturing = False
        # ปุ่มของ step กดปุ่ม (step คลิกเริ่มที่ E เผื่อเปลี่ยนประเภทเป็นกดปุ่ม)
        if step["type"] == KEY_TYPE:
            self.key = {"mods": list(step["key_mods"]), "vk": step["key_vk"]}
        else:
            self.key = {"mods": [], "vk": DEFAULT_STEP_KEY}
        self.vars = {
            # step กดปุ่มไม่มีพิกัด ใส่ 100 ไว้ เผื่อเปลี่ยนเป็นคลิกจะได้มีค่าเริ่ม
            "x": tk.StringVar(value=str(100 if step["x"] is None else step["x"])),
            "y": tk.StringVar(value=str(100 if step["y"] is None else step["y"])),
            "type": tk.StringVar(value=CLICK_LABEL[step["type"]]),
            "repeat": tk.StringVar(value=str(step["repeat"])),
        }
        for key in ("delay_ms", "hold_ms", "gap_ms"):  # ช่องเวลา: ตัวเลข + หน่วย เลือกหน่วยจากค่าเดิม
            value, unit = pick_unit(step[key])
            self.vars[key] = tk.StringVar(value=str(value))
            self.vars[key + "_unit"] = tk.StringVar(value=unit)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        rows = [
            ("ประเภท", "type"),
            ("X", "x"),
            ("Y", "y"),
            ("ปุ่ม", "key"),
            ("จำนวนครั้ง", "repeat"),
            ("เว้นระหว่างครั้ง", "gap_ms"),
            ("รอหลังครั้งสุดท้าย", "delay_ms"),
            ("กดค้างนาน", "hold_ms"),
        ]
        self.row_widgets = {}  # key -> widget ในแถวนั้น (ไว้ซ่อน/แสดงตามประเภท)
        for r, (lbl, key) in enumerate(rows):
            widgets = [ttk.Label(f, text=lbl)]
            widgets[0].grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            if key == "type":
                w = ttk.Combobox(
                    f,
                    textvariable=self.vars[key],
                    state="readonly",
                    values=[CLICK_LABEL[t] for t in STEP_TYPES],
                    width=14,
                )
                w.bind("<<ComboboxSelected>>", lambda e: self._sync_type())
            elif key == "key":
                w = self.key_btn = ttk.Button(f, width=24, command=self._capture_key)
            else:
                w = ttk.Entry(f, textvariable=self.vars[key], width=10)
            w.grid(row=r, column=1, sticky="ew", pady=3)
            widgets.append(w)
            if key + "_unit" in self.vars:
                u = ttk.Combobox(
                    f,
                    textvariable=self.vars[key + "_unit"],
                    state="readonly",
                    values=list(TIME_UNITS),
                    width=6,
                )
                u.grid(row=r, column=2, padx=(4, 0), pady=3)
                widgets.append(u)
            self.row_widgets[key] = widgets
        bf = ttk.Frame(f)
        bf.grid(row=len(rows), column=0, columnspan=3, pady=(10, 0))
        ttk.Button(bf, text="ตกลง", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bf, text="ยกเลิก", command=self._close).pack(side="left", padx=4)
        # ระหว่างรอจับปุ่ม Enter/Esc เป็นปุ่มที่กำลังจับ ห้ามไปกดตกลง/ปิด dialog
        self.bind("<Return>", lambda e: None if self.capturing else self._ok())
        self.bind("<Escape>", lambda e: None if self.capturing else self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._sync_type()
        self.grab_set()

    def _is_key(self):
        return LABEL_TO_TYPE.get(self.vars["type"].get()) == KEY_TYPE

    def _sync_type(self):
        """กดปุ่ม: ซ่อน X/Y โชว์แถวปุ่ม / คลิก: กลับกัน"""
        is_key = self._is_key()
        for key, show in (("x", not is_key), ("y", not is_key), ("key", is_key)):
            for w in self.row_widgets.get(key, ()):
                if show:
                    w.grid()
                else:
                    w.grid_remove()  # grid_remove จำตำแหน่งไว้ grid() ครั้งหน้ากลับที่เดิม
        self._render_key()

    def _render_key(self):
        if hasattr(self, "key_btn"):
            self.key_btn.configure(text=self.KEY_PROMPT if self.capturing else hotkey_to_text(self.key))

    def _capture_key(self):
        if self.app is None:
            return
        self.capturing = True
        self._render_key()
        self.focus_set()  # ดึง focus ออกจากปุ่ม ไม่งั้นกด Space/Enter จะไปกดปุ่มใน dialog ซ้ำ
        self.app.begin_key_capture(self)

    def _stop_capture(self):
        if self.capturing:
            self.capturing = False
            if self.app is not None:
                self.app.end_key_capture()

    def on_captured(self, hk):
        """ปุ่มที่จับได้ (ส่งมาจาก App._poll) Esc = ยกเลิกการจับ ไม่เปลี่ยนปุ่ม"""
        if not self.capturing:
            return
        self._stop_capture()
        if hk["vk"] != VK_ESCAPE:
            try:
                key = parse_hotkey(hk)
                self._check_hotkey_conflict(key)
                self.key = key
            except ValueError as e:
                messagebox.showerror(APP_NAME, str(e), parent=self)
        self._render_key()

    def _check_hotkey_conflict(self, key):
        if self.app is not None:
            label = hotkey_conflict(key, self.app.hotkeys)
            if label:
                raise ValueError(f"{hotkey_to_text(key)} เป็นปุ่มลัด '{label}' ของโปรแกรม ใช้เป็นปุ่มที่จะกดไม่ได้")

    def _close(self):
        self._stop_capture()  # ปิด dialog ระหว่างรอจับปุ่ม ต้องเปิดปุ่มลัดคืน
        self.destroy()

    def _ok(self):
        if self.capturing:
            return
        try:
            form = {k: v.get() for k, v in self.vars.items()}
            form["key_vk"], form["key_mods"] = self.key["vk"], self.key["mods"]
            # แปลงหน่วยเป็น ms ก่อน แล้วค่อย validate ด้วยกติกาเดิม (delay >= 10ms ฯลฯ)
            step = validate_step(step_from_form(form), get_virtual_origin())
            if step["type"] == KEY_TYPE:
                self._check_hotkey_conflict(step_key(step))
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e), parent=self)
            return
        self.result = step
        self._close()


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
            row=len(HOTKEY_ACTIONS), column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
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
