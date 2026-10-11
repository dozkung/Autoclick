"""ปุ่มลัด: แปลง/validate, จับคู่ press/release (HotkeyMatcher) และไฟล์ตั้งค่าของเครื่อง
ห้าม import tkinter/pynput: callback ของ pynput ส่ง vk มาให้ (key_to_vk) แล้ว module นี้ไม่แตะ UI"""

import ctypes
import json
import os
import sys

from .constants import (
    APP_NAME,
    DEFAULT_HOTKEYS,
    HOTKEY_ACTIONS,
    HOTKEY_LABEL,
    MOD_LABEL,
    MOD_ORDER,
    SETTINGS_VERSION,
    VK_ESCAPE,
    VK_TO_MOD,
    VK_WIN,
)

_VK_NAMES = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x13: "Pause",
    0x14: "CapsLock",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2D: "Insert",
    0x2E: "Delete",
    0x6A: "Num *",
    0x6B: "Num +",
    0x6D: "Num -",
    0x6E: "Num .",
    0x6F: "Num /",
    0x90: "NumLock",
    0x91: "ScrollLock",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}


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
            raise ValueError(
                f"{hotkey_to_text(hk)} ซ้ำกันระหว่าง '{HOTKEY_LABEL[seen[key]]}' กับ '{HOTKEY_LABEL[action]}'"
            )
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
        "header": (
            f"{t['toggle']} = เริ่ม/หยุด    {t['add']} = เพิ่มจุดที่เมาส์    "
            f"{t['markers']} = แสดง/ซ่อนหมุด    เมาส์ชนมุมซ้ายบนสุดของจอ = หยุดฉุกเฉิน"
        ),
        "start": f"▶ เริ่ม ({t['toggle']})",
        "stop": f"■ หยุด ({t['toggle']})",
        "markers": f"แสดงหมุด ({t['markers']})",
        "no_steps": f"ยังไม่มีจุด กด {t['add']} ที่ตำแหน่งที่จะคลิกก่อน",
    }
