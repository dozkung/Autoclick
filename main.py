"""
AutoClicker — multi-point auto clicker สำหรับ Windows

ปุ่มลัด (ใช้ได้ทั้งตอนหน้าต่างไม่ได้ focus, ตั้งเองได้ที่ปุ่ม "ปุ่มลัด…")
  F6  = เริ่ม / หยุด                  (ค่าเริ่มต้น)
  F8  = เพิ่มจุดที่ตำแหน่งเมาส์ตอนนี้    (ค่าเริ่มต้น)
  F7  = แสดง / ซ่อนหมุดบนจอ            (ค่าเริ่มต้น)
  เอาเมาส์ชนมุมซ้ายบนสุดของจอ (virtual screen รวมทุกจอ) = หยุดฉุกเฉิน (kill switch)
"""

# ต้องตั้ง DPI awareness ก่อน import tkinter/pynput และก่อนสร้างหน้าต่างหรืออ่านพิกัดเมาส์
# ไม่งั้นจอที่ตั้ง scaling 125/150% จะได้พิกัดคลาดจากจุดจริง
# screen.py ไม่ import tkinter/pynput จึง import ก่อนได้ (ห้ามย้ายการเรียกนี้ไปไว้ใน module อื่น)
from autoclicker.screen import _set_dpi_aware

_set_dpi_aware()

import tkinter as tk  # noqa: E402
from tkinter import font as tkfont  # noqa: E402

from autoclicker.ui.app import App  # noqa: E402  (ข้างในมี pynput ต้อง import หลังตั้ง DPI)


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
