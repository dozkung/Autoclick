"""เธรดที่คลิกจริง (Runner) และการขยับเมาส์ให้เกมรับรู้ (nudge_mouse)
ห้าม import tkinter: Runner คุยกับ UI ผ่าน callback ที่ใส่ queue เท่านั้น
import pynput ได้ แต่ main.py ต้องตั้ง DPI awareness ก่อน import module นี้"""

import ctypes
import random
import sys
import threading
import time

from pynput.mouse import Button

from .constants import CORNER, KILL_REASON, MIN_DELAY_MS
from .screen import in_corner
from .win32 import _INPUT, _INPUT_MOUSE, _MOUSEEVENTF_MOVE


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


def format_status(rnd, i, k, n):
    """ข้อความ status ระหว่างรัน คลิกจุดเดียวหลายครั้งให้บอกครั้งที่ (k/n) ด้วย"""
    text = f"รอบ {rnd} · จุด #{i}"
    return f"{text} ({k}/{n})" if n > 1 else text


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
