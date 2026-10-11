"""DPI, virtual screen (รวมทุกจอ) และโซน kill switch
ห้าม import tkinter/pynput: main.py import ไฟล์นี้เพื่อตั้ง DPI awareness ก่อนตัวอื่นทั้งหมด"""

import ctypes
import sys

from .constants import CORNER
from .win32 import _win32_api


def _set_dpi_aware():
    # ต้องเรียกก่อนสร้างหน้าต่างหรืออ่านพิกัดเมาส์
    # ถ้าไม่เรียก จอที่ตั้ง scaling 125/150% จะได้พิกัดคลาดจากจุดจริง
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_virtual_origin():
    """มุมซ้ายบนของ virtual screen (รวมทุกจอ) ถ้ามีจอเสริมอยู่ทางซ้าย/บน ค่าจะติดลบ
    ขอบนี้คือจุดที่เมาส์ไปต่อไม่ได้จริง เลยใช้เป็น kill switch ได้"""
    if sys.platform != "win32":
        return (0, 0)
    try:
        gsm = ctypes.windll.user32.GetSystemMetrics
        return (int(gsm(76)), int(gsm(77)))  # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN
    except Exception:
        return (0, 0)


def get_virtual_rect():
    """(vx, vy, cx, cy) ของ virtual screen (รวมทุกจอ) ถ้าไม่ใช่ Windows หรืออ่านไม่ได้คืน None"""
    if sys.platform != "win32":
        return None
    try:
        gsm = ctypes.windll.user32.GetSystemMetrics
        # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
        vx, vy, cx, cy = (int(gsm(i)) for i in (76, 77, 78, 79))
    except Exception:
        return None
    if cx <= 0 or cy <= 0:  # GetSystemMetrics คืน 0 เมื่อเรียกไม่สำเร็จ
        return None
    return (vx, vy, cx, cy)


def out_of_screen(x, y, rect):
    """จุดอยู่นอก virtual screen ไหม (เช่นถอดจอที่จุดนั้นอยู่ออกไปแล้ว) rect เป็น None = ไม่เช็ก"""
    if rect is None:
        return False
    vx, vy, cx, cy = rect
    return not (vx <= x <= vx + cx - 1 and vy <= y <= vy + cy - 1)


def in_corner(x, y, origin=(0, 0)):
    vx, vy = origin
    return vx <= x <= vx + CORNER and vy <= y <= vy + CORNER


def window_dpi_scale(hwnd):
    """GetDpiForWindow(hwnd)/96 ถ้าเรียกไม่ได้คืน None"""
    try:
        dpi = _win32_api().user32.GetDpiForWindow(hwnd)
    except (OSError, AttributeError):
        return None
    return dpi / 96 if dpi else None
