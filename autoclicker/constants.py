"""ค่าคงที่ทั้งหมดของโปรแกรม (ไม่ import อะไรเลย จะได้ไม่เกิด import วน)"""

APP_NAME = "AutoClicker"
FILE_VERSION = 1
CORNER = 3  # px: เมาส์เข้ามุมซ้ายบนของ virtual screen ในระยะนี้ถือว่าสั่งหยุดฉุกเฉิน
MIN_DELAY_MS = 10  # กัน delay 0 ไม่ให้ลูปเปล่ากิน CPU 100%
MAX_JITTER_PX = 50
MAX_JITTER_MS = 5000
KILL_REASON = "หยุดฉุกเฉิน (เมาส์ชนมุมซ้ายบนสุดของจอ)"

CLICK_TYPES = ["left", "right", "double", "hold"]
CLICK_LABEL = {"left": "คลิกซ้าย", "right": "คลิกขวา", "double": "ดับเบิลคลิก", "hold": "กดค้าง"}
LABEL_TO_TYPE = {v: k for k, v in CLICK_LABEL.items()}
MODES = ("loop", "count", "time")
DEFAULT_SETTINGS = {
    "mode": "loop",
    "rounds": 10,
    "minutes": 5.0,
    "jitter_px": 0,
    "jitter_ms": 0,
    "hover_ms": 50,
}
MAX_HOVER_MS = 1000  # รอ hover หลังย้ายเมาส์ก่อนคลิก (เกมอัปเดต hover ทีละเฟรม ~16ms)
DEFAULT_DEFAULTS = {"type": "left", "delay_ms": 500, "repeat": 1}
MAX_DURATION_MS = 86_400_000  # 24 ชม. กันพิมพ์ผิดหน่วยแล้วโปรแกรมรอเป็นปี
TIME_UNITS = {"ms": 1, "วินาที": 1000, "นาที": 60000}  # หน่วยใน UI (ข้อมูลภายในเป็น ms เสมอ)
MAX_REPEAT = 1000  # คลิกซ้ำที่จุดเดียวได้สูงสุดกี่ครั้ง
DEFAULT_GAP_MS = 100  # เว้นระหว่างคลิกแต่ละครั้งในจุดเดียวกัน
MAX_GAP_MS = 60000

MARKER_SIZE = 30  # ขนาดหน้าต่างหมุด (px ที่ scaling 100%): วงกลม ~28px + ขอบเผื่อ 1px ต่อด้าน
MARKER_DRAG_PX = 3  # ขยับน้อยกว่านี้ถือว่าเป็นคลิก ไม่ใช่ลาก
MARKER_KEY = "#ff00fe"  # สีพื้นหลังที่ใช้เป็น -transparentcolor (ห้ามซ้ำกับสีหมุด)
MARKER_COLOR = {"left": "#1e6fd9", "right": "#f08c00", "double": "#7b3fe4", "hold": "#d62828"}
MARKER_SS = 4  # supersampling: วาดใหญ่ 4 เท่าแล้วย่อ ได้ขอบเนียน

# ปุ่มลัดเก็บเป็น {"mods": [...], "vk": int} ใช้ Windows virtual key code ไม่ใช้ตัวอักษร
# เพราะคีย์บอร์ดไทยตัวอักษรเปลี่ยนตามภาษา (A -> ฟ) แต่ vk เท่าเดิม
SETTINGS_VERSION = 1
HOTKEY_ACTIONS = ("toggle", "add", "markers")
HOTKEY_LABEL = {"toggle": "เริ่ม / หยุด", "add": "เพิ่มจุดที่เมาส์", "markers": "แสดง / ซ่อนหมุด"}
MOD_ORDER = ("ctrl", "alt", "shift")
MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
VK_ESCAPE = 0x1B
# modifier ซ้าย/ขวา/กลาง นับเป็นตัวเดียวกัน (pynput บน Windows ส่ง L/R มา: Key.shift = 0xA0)
VK_TO_MOD = {
    0x10: "shift",
    0xA0: "shift",
    0xA1: "shift",
    0x11: "ctrl",
    0xA2: "ctrl",
    0xA3: "ctrl",
    0x12: "alt",
    0xA4: "alt",
    0xA5: "alt",
}
VK_WIN = (0x5B, 0x5C)  # ปุ่ม Windows ระบบจองไว้ ไม่รับเป็นปุ่มลัด
DEFAULT_HOTKEYS = {
    "toggle": {"mods": [], "vk": 0x75},  # F6
    "add": {"mods": [], "vk": 0x77},  # F8
    "markers": {"mods": [], "vk": 0x76},  # F7 (F9 ชน Developer Console ของ Roblox)
}
