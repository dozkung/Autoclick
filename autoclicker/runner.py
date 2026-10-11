"""เธรดที่คลิกจริง (Runner), การขยับเมาส์ให้เกมรับรู้ (nudge_mouse) และการกดปุ่มคีย์บอร์ด (send_key)
ห้าม import tkinter: Runner คุยกับ UI ผ่าน callback ที่ใส่ queue เท่านั้น
import pynput ได้ แต่ main.py ต้องตั้ง DPI awareness ก่อน import module นี้"""

import ctypes
import os
import random
import sys
import threading
import time

from pynput.mouse import Button

from .constants import (
    CORNER,
    EXTENDED_VKS,
    FG_CHECK_S,
    KEY_TYPE,
    KILL_REASON,
    MIN_DELAY_MS,
    MOD_ORDER,
    MOD_VK,
    OWN_WINDOW_REASON,
    PAUSED_TEXT,
    RESUME_DELAY_S,
    TARGET_CLOSED_REASON,
)
from .screen import foreground_window, in_corner
from .screen import is_window as win_is_window
from .screen import window_pid as win_window_pid
from .win32 import (
    _INPUT,
    _INPUT_KEYBOARD,
    _INPUT_MOUSE,
    _KEYEVENTF_EXTENDEDKEY,
    _KEYEVENTF_KEYUP,
    _KEYEVENTF_SCANCODE,
    _MAPVK_VK_TO_VSC,
    _MOUSEEVENTF_MOVE,
)


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


def key_input_fields(vk, down, scan):
    """ค่า (wVk, wScan, dwFlags) ของ KEYBDINPUT 1 ตัว แยกออกมาให้เทสต์ได้โดยไม่แตะ Win32
    มี scan code: ส่งแบบ KEYEVENTF_SCANCODE เพราะเกมอย่าง Roblox อ่านปุ่มจาก scan code
    ถ้าส่งแค่ vk (แบบ pynput keyboard.Controller) เกมจะไม่รับ
    ไม่มี scan code (MapVirtualKey คืน 0 เช่นปุ่มพิเศษบางตัว): ส่ง vk ตามปกติ ดีกว่าไม่ส่งเลย
    ลูกศร/Insert/Delete/Home/End/PageUp/PageDown ต้องมี EXTENDEDKEY ไม่งั้นกลายเป็นปุ่มบน numpad"""
    flags = 0 if down else _KEYEVENTF_KEYUP
    if vk in EXTENDED_VKS:
        flags |= _KEYEVENTF_EXTENDEDKEY
    if scan:
        return 0, scan, flags | _KEYEVENTF_SCANCODE
    return vk, 0, flags


def send_key(vk, down):
    """กด (down=True) หรือปล่อยปุ่ม vk 1 ตัวด้วย SendInput แบบ scan code
    ไม่ใช่ Windows หรือส่งไม่สำเร็จ = raise (Runner จะหยุดแล้วโชว์ error ไม่ใช่กดไม่ติดเงียบๆ)"""
    if sys.platform != "win32":
        raise RuntimeError("กดปุ่มคีย์บอร์ดได้เฉพาะบน Windows")
    u = ctypes.windll.user32
    wvk, wscan, flags = key_input_fields(vk, down, u.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC))
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ki.wVk, inp.ki.wScan, inp.ki.dwFlags = wvk, wscan, flags
    if u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) != 1:
        # มักเกิดเมื่อหน้าต่างเป้าหมายรันแบบ admin (UIPI กัน input จากโปรแกรมสิทธิ์ต่ำกว่า)
        raise OSError("ส่งปุ่มคีย์บอร์ดไม่สำเร็จ (เกมรันแบบ Administrator อยู่หรือเปล่า?)")


def format_status(rnd, i, k, n):
    """ข้อความ status ระหว่างรัน คลิกจุดเดียวหลายครั้งให้บอกครั้งที่ (k/n) ด้วย"""
    text = f"รอบ {rnd} · จุด #{i}"
    return f"{text} ({k}/{n})" if n > 1 else text


def countdown_text(left):
    """ข้อความ status ระหว่างนับถอยหลังก่อนเริ่ม"""
    return f"เริ่มใน {left}…"


class Runner(threading.Thread):
    """เธรดที่สั่งคลิกจริง ห้ามแตะ tkinter ในนี้ ให้ส่งข้อความผ่าน callback (ซึ่งใช้ queue) แทน

    foreground / is_window / window_pid inject ได้เหมือน nudge (เทสต์จะได้ไม่ไปอ่านหน้าต่างจริง)
    ถ้า foreground คืน None (ไม่ใช่ Windows / เรียก API ไม่ได้) ฟีเจอร์หยุดเมื่อสลับหน้าต่างจะปิดเงียบๆ"""

    def __init__(
        self,
        steps,
        cfg,
        mouse_ctl,
        on_status,
        on_done,
        origin=(0, 0),
        nudge=None,
        on_notice=None,
        foreground=None,
        is_window=None,
        window_pid=None,
        key_sender=None,
    ):
        super().__init__(daemon=True)
        self.steps = [dict(s) for s in steps]  # snapshot: ระหว่างรันแก้ตารางได้ ไม่ชนกับเธรดนี้
        self.cfg = cfg
        self.origin = origin  # มุมซ้ายบนของ virtual screen ตอนกดเริ่ม
        self.nudge = nudge or nudge_mouse  # inject ได้ เทสต์จะได้ไม่ไปขยับเมาส์จริง
        self.send_key = key_sender or send_key  # inject ได้ เทสต์จะได้ไม่ไปกดปุ่มจริง
        self.mouse = mouse_ctl
        self.on_status = on_status
        self.on_done = on_done
        self.on_notice = on_notice or (lambda text: None)  # ข้อความอิสระ (นับถอยหลัง / หยุดชั่วคราว)
        self.foreground = foreground or foreground_window
        self.is_window = is_window or win_is_window
        self.window_pid = window_pid or win_window_pid
        self.target = None  # หน้าต่างเกม: จำตอนนับถอยหลังจบ (None = ไม่เช็กหน้าต่าง)
        self._pause_count = 0  # เพิ่มทุกครั้งที่หยุดชั่วคราว ใช้รู้ว่าต้องวาร์ปเมาส์/รอ hover ใหม่ไหม
        self._last_status = None  # ไว้ส่งซ้ำตอนทำต่อหลังหยุดชั่วคราว status จะได้ไม่ค้างข้อความเดิม
        self.stop_evt = threading.Event()
        self.reason = "หยุดแล้ว"
        self.deadline = None
        self._held = None
        self._held_keys = []  # ปุ่มคีย์บอร์ดที่กดค้างอยู่ (ตามลำดับที่กด) ต้องปล่อยให้หมดเสมอ

    def stop(self, reason="หยุดแล้ว"):
        if not self.stop_evt.is_set():
            self.reason = reason
            self.stop_evt.set()

    def _check(self):
        """เช็ก stop / kill switch / deadline คืน False ถ้าต้องหยุด"""
        if self.stop_evt.is_set():
            return False
        x, y = self.mouse.position
        if in_corner(x, y, self.origin):
            self.stop(KILL_REASON)
            return False
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.stop("ครบเวลาที่ตั้งไว้")
            return False
        return True

    def _target_state(self):
        """True = หน้าต่างเป้าหมายอยู่ข้างหน้า, None = ไม่อยู่ (ต้องหยุดชั่วคราว), False = ถูกปิด (หยุดถาวรแล้ว)"""
        if not self.is_window(self.target):
            self.stop(TARGET_CLOSED_REASON)
            return False
        return True if self.foreground() == self.target else None

    def _wait(self, sec, pausable=True):
        """รอแบบแบ่งช่วงสั้นๆ ไม่ใช้ time.sleep(sec) ตรงๆ
        เพราะถ้า delay ตั้งไว้ 30 วินาที กดหยุดแล้วต้องรอให้ครบก่อนถึงจะหยุดได้
        ถ้ามีหน้าต่างเป้าหมาย เช็กทุก ≤FG_CHECK_S ว่ายังอยู่ข้างหน้าไหม ถ้าไม่อยู่จะหยุดชั่วคราวในนี้เลย
        pausable=False (ระหว่างกดค้าง): ไม่หยุดชั่วคราวในนี้ แต่คืน None ให้คนเรียกปล่อยปุ่มก่อน"""
        end = time.monotonic() + max(0.0, sec)
        next_fg = 0.0  # เช็กหน้าต่างทันทีรอบแรก = เช็กก่อนทุกคลิก
        while True:
            if not self._check():
                return False
            now = time.monotonic()
            if self.target is not None and now >= next_fg:
                next_fg = now + FG_CHECK_S
                state = self._target_state()
                if state is False:
                    return False
                if state is None:
                    if not pausable:
                        return None
                    if not self._pause():
                        return False
                    continue
            left = end - now
            if left <= 0:
                return True
            self.stop_evt.wait(min(left, 0.02))

    def _pause(self):
        """หยุดชั่วคราว (ไม่คลิก) จนหน้าต่างเป้าหมายกลับมาข้างหน้าครบ RESUME_DELAY_S
        ระหว่างนี้ stop / kill switch ยังหยุดได้ และ deadline ของโหมดเวลายังเดินต่อ คืน False ถ้าโดนหยุด"""
        self._pause_count += 1
        self.on_notice(PAUSED_TEXT)
        resume_at = None
        while True:
            if not self._check():
                return False
            state = self._target_state()
            if state is False:
                return False
            now = time.monotonic()
            if state is None:
                resume_at = None  # หลุดอีกรอบระหว่างรอ 500ms ต้องเริ่มนับใหม่
            elif resume_at is None:
                resume_at = now + RESUME_DELAY_S
            elif now >= resume_at:
                break
            self.stop_evt.wait(0.02)
        if self._last_status is not None:
            self.on_status(*self._last_status)
        return True

    def _countdown(self):
        """นับถอยหลังผ่าน _wait (ยกเลิกด้วย F6 / ชนมุมได้) แล้วจำหน้าต่างเป้าหมาย คืน False ถ้าโดนหยุด"""
        for left in range(self.cfg["countdown_s"], 0, -1):
            self.on_notice(countdown_text(left))
            if not self._wait(1.0):
                return False
        if self.cfg["pause_on_switch"]:
            hwnd = self.foreground()
            if hwnd:  # None = ไม่ใช่ Windows / อ่านไม่ได้ -> ปิดฟีเจอร์เงียบๆ คลิกได้ตามเดิม
                if self.window_pid(hwnd) == os.getpid():
                    # หน้าต่างข้างหน้าคือโปรแกรมเราเอง ถ้าคลิกต่อจะไปคลิกใส่ตัวเอง
                    self.stop(OWN_WINDOW_REASON)
                    return False
                self.target = hwnd
        return True

    def _click(self, s):
        """คลิก 1 ครั้งตาม type คืน False ถ้าโดนหยุด
        ถ้าหน้าต่างเป้าหมายหลุดระหว่างกดค้าง: ปุ่มถูกปล่อยแล้ว รอกลับมาแล้วกดใหม่ทั้งครั้ง (ทำต่อจาก step เดิม)"""
        while True:
            result = self._click_once(s)
            if result is not None:
                return result
            if not self._pause():
                return False

    def _click_once(self, s):
        """คลิก 1 ครั้งตาม type (สุ่มพิกัดใหม่ทุกครั้ง) คืน False ถ้าโดนหยุดระหว่างรอ hover หรือกดค้าง
        คืน None ถ้าหน้าต่างเป้าหมายหลุดระหว่างกดค้าง (ต้องกดใหม่)
        ลำดับ: วาร์ปเมาส์ -> ส่ง move event จริง -> รอ hover -> (ตั้งตำแหน่งซ้ำถ้าเพี้ยน) -> คลิก
        step กดปุ่มไม่ยุ่งกับเมาส์เลย ส่งต่อให้ _key_once"""
        if s["type"] == KEY_TYPE:
            return self._key_once(s)
        while True:
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
            paused_before = self._pause_count
            # รอให้แอปเป้าหมายอัปเดต hover ก่อนคลิก (รอผ่าน _wait: หยุด/kill switch ได้ระหว่างรอ)
            if not self._wait(self.cfg["hover_ms"] / 1000):
                return False
            # เช็กหน้าต่างเป้าหมายอีกรอบก่อนคลิกจริง (รอ hover นานได้ถึง 1 วิ)
            if not self._wait(0):
                return False
            if self._pause_count == paused_before:
                break
            # หยุดชั่วคราวระหว่างรอ hover ผู้ใช้อาจขยับเมาส์ไปแล้ว ต้องวาร์ป/nudge/รอ hover ใหม่
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
                # pausable=False: หน้าต่างหลุดระหว่างกดค้าง ห้ามค้างปุ่มไว้ระหว่างหยุดชั่วคราว
                return self._wait(s["hold_ms"] / 1000, pausable=False)
            finally:
                # ต้องปล่อยเสมอ ถึงจะโดนหยุดกลางคันก็ตาม ไม่งั้นปุ่มเมาส์ค้างทั้งเครื่อง
                self.mouse.release(Button.left)
                self._held = None
        return True

    def _key_once(self, s):
        """กดปุ่ม 1 ครั้ง: กด mods -> กดปุ่ม -> ค้าง hold_ms -> ปล่อยปุ่ม -> ปล่อย mods (ย้อนลำดับ)
        คืน False ถ้าโดนหยุด, None ถ้าหน้าต่างเป้าหมายหลุดระหว่างกดค้าง (ปล่อยแล้ว _click จะรอแล้วกดใหม่)"""
        if not self._wait(0):  # เช็กหน้าต่างเป้าหมายก่อนกด ถ้าหลุดอยู่จะหยุดชั่วคราวในนี้
            return False
        vks = [MOD_VK[m] for m in MOD_ORDER if m in s["key_mods"]] + [s["key_vk"]]
        try:
            for vk in vks:
                self.send_key(vk, True)
                self._held_keys.append(vk)
            # pausable=False: หน้าต่างหลุดระหว่างกดค้าง ห้ามค้างปุ่มไว้ระหว่างหยุดชั่วคราว
            return self._wait(s["hold_ms"] / 1000, pausable=False)
        finally:
            self._release_keys()

    def _release_keys(self):
        """ปล่อยปุ่มที่กดค้างทั้งหมด ย้อนลำดับ (ปุ่มหลักก่อน แล้วค่อย mods)
        ปล่อยตัวไหนพังก็ต้องปล่อยตัวที่เหลือต่อ ไม่งั้น Ctrl/Shift ค้างทั้งเครื่อง"""
        while self._held_keys:
            vk = self._held_keys.pop()
            try:
                self.send_key(vk, False)
            except Exception:
                pass

    def _run_step(self, rnd, i, s):
        """คลิกจุดเดียวซ้ำ repeat ครั้ง เว้น gap_ms ระหว่างครั้ง แล้วรอ delay_ms หลังครั้งสุดท้าย
        คืน False ถ้าโดนหยุด (stop / kill switch / deadline) กลางทาง"""
        n = s["repeat"]
        jm = self.cfg["jitter_ms"]
        for k in range(1, n + 1):
            if not self._wait(0):
                return False
            self._last_status = (rnd, i, k, n)
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
            if not self._countdown():
                return
            if cfg["mode"] == "time":  # เริ่มนับเวลาหลังนับถอยหลังจบ
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
            self._release_keys()
            self.on_done(self.reason)
