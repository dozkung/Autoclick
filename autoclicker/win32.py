"""struct, ค่าคงที่ และ user32/gdi32 (WinDLL ที่ตั้ง argtypes ครบ) ของ Win32 ที่ใช้ร่วมกัน
import ได้ทุก platform: ยังไม่แตะ DLL จนกว่าจะเรียก _win32_api()"""

import ctypes
import types


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]  # MOUSEINPUT ใหญ่สุดใน union อยู่แล้ว ขนาด INPUT จึงถูก

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


_INPUT_MOUSE = 0


_MOUSEEVENTF_MOVE = 0x0001


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


_GWL_EXSTYLE = -20


_WS_EX_LAYERED = 0x00080000


_ULW_ALPHA = 0x02


_AC_SRC_OVER, _AC_SRC_ALPHA = 0x00, 0x01


_win32 = None


def _win32_api():
    """user32/gdi32 ที่ตั้ง argtypes/restype ครบ (handle เป็น 64-bit ถ้าปล่อยเป็น int จะโดนตัด)
    ใช้ WinDLL ของตัวเอง ไม่แก้ ctypes.windll ที่ส่วนอื่น (pynput) ใช้ร่วม"""
    global _win32
    if _win32 is None:
        from ctypes import wintypes as wt

        u = ctypes.WinDLL("user32", use_last_error=True)
        g = ctypes.WinDLL("gdi32", use_last_error=True)
        H = ctypes.c_void_p
        u.GetDC.argtypes, u.GetDC.restype = [wt.HWND], H
        u.ReleaseDC.argtypes, u.ReleaseDC.restype = [wt.HWND, H], ctypes.c_int
        u.GetWindowLongPtrW.argtypes, u.GetWindowLongPtrW.restype = [wt.HWND, ctypes.c_int], ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.UpdateLayeredWindow.argtypes = [
            wt.HWND,
            H,
            ctypes.POINTER(_POINT),
            ctypes.POINTER(_SIZE),
            H,
            ctypes.POINTER(_POINT),
            wt.DWORD,
            ctypes.POINTER(_BLENDFUNCTION),
            wt.DWORD,
        ]
        u.UpdateLayeredWindow.restype = wt.BOOL
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [H], H
        g.CreateDIBSection.argtypes = [
            H,
            ctypes.POINTER(_BITMAPINFOHEADER),
            wt.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wt.HANDLE,
            wt.DWORD,
        ]
        g.CreateDIBSection.restype = H
        g.SelectObject.argtypes, g.SelectObject.restype = [H, H], H
        g.DeleteObject.argtypes, g.DeleteObject.restype = [H], wt.BOOL
        g.DeleteDC.argtypes, g.DeleteDC.restype = [H], wt.BOOL
        try:
            u.GetDpiForWindow.argtypes, u.GetDpiForWindow.restype = [wt.HWND], wt.UINT
        except AttributeError:  # Windows เก่ากว่า 10 1607
            pass
        # หน้าต่างข้างหน้า (หยุดชั่วคราวเมื่อสลับหน้าต่าง) HWND ต้องเป็น pointer ไม่งั้นโดนตัดเหลือ 32-bit
        u.GetForegroundWindow.argtypes, u.GetForegroundWindow.restype = [], wt.HWND
        u.GetAncestor.argtypes, u.GetAncestor.restype = [wt.HWND, wt.UINT], wt.HWND
        u.IsWindow.argtypes, u.IsWindow.restype = [wt.HWND], wt.BOOL
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u.GetWindowThreadProcessId.restype = wt.DWORD
        _win32 = types.SimpleNamespace(user32=u, gdi32=g)
    return _win32
