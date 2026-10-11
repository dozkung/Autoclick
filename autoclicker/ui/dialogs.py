"""หน้าต่างย่อย: แก้ไขจุดคลิก (StepDialog) และตั้งปุ่มลัด (HotkeyDialog)"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..constants import (
    APP_NAME,
    CLICK_LABEL,
    CLICK_TYPES,
    DEFAULT_HOTKEYS,
    HOTKEY_ACTIONS,
    HOTKEY_LABEL,
    TIME_UNITS,
    VK_ESCAPE,
)
from ..hotkeys import assign_hotkey, hotkey_to_text, validate_hotkeys
from ..model import pick_unit, step_from_form, validate_step
from ..screen import get_virtual_origin


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
        rows = [
            ("X", "x"),
            ("Y", "y"),
            ("ประเภท", "type"),
            ("จำนวนครั้ง", "repeat"),
            ("เว้นระหว่างครั้ง", "gap_ms"),
            ("รอหลังครั้งสุดท้าย", "delay_ms"),
            ("กดค้างนาน", "hold_ms"),
        ]
        for r, (lbl, key) in enumerate(rows):
            ttk.Label(f, text=lbl).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            if key == "type":
                w = ttk.Combobox(
                    f,
                    textvariable=self.vars[key],
                    state="readonly",
                    values=[CLICK_LABEL[t] for t in CLICK_TYPES],
                    width=14,
                )
            else:
                w = ttk.Entry(f, textvariable=self.vars[key], width=10)
            w.grid(row=r, column=1, sticky="ew", pady=3)
            if key + "_unit" in self.vars:
                ttk.Combobox(
                    f,
                    textvariable=self.vars[key + "_unit"],
                    state="readonly",
                    values=list(TIME_UNITS),
                    width=6,
                ).grid(row=r, column=2, padx=(4, 0), pady=3)
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
