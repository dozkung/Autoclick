"""เทสต์โครงสร้าง module: ห้าม import tkinter ใน module logic, ห้าม import วน, DPI ต้องมาก่อน
รันใน subprocess แยกทุกข้อ จะได้ไม่โดน stub/sys.modules ของเทสต์อื่นปน"""

import os
import subprocess
import sys
import textwrap
import unittest

import support

ROOT = support.ROOT
TESTS = os.path.dirname(os.path.abspath(__file__))

# pynput ปลอมแบบเล็กสุด (runner ต้องใช้ pynput.mouse.Button) ไม่แตะ tkinter
PYNPUT_STUB = """
import sys, types
p = types.ModuleType("pynput"); k = types.ModuleType("pynput.keyboard"); m = types.ModuleType("pynput.mouse")
k.Listener = object; k.Key = object
m.Button = types.SimpleNamespace(left="left", right="right"); m.Controller = object
p.keyboard, p.mouse = k, m
sys.modules.update({"pynput": p, "pynput.keyboard": k, "pynput.mouse": m})
"""


def run_py(code):
    """รันโค้ดใน python ตัวใหม่ (cwd = ราก repo) คืน (returncode, stdout+stderr)"""
    res = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return res.returncode, res.stdout + res.stderr


class NoTkinterInLogicTests(unittest.TestCase):
    def test_logic_modules_do_not_import_tkinter(self):
        for mod in ("constants", "win32", "screen", "model", "hotkeys", "runner"):
            with self.subTest(mod=mod):
                code, out = run_py(
                    PYNPUT_STUB
                    + f"""
import importlib
importlib.import_module("autoclicker.{mod}")
bad = sorted(m for m in sys.modules if m == "tkinter" or m.startswith("tkinter."))
print("TK", bad)
"""
                )
                self.assertEqual(code, 0, out)
                self.assertIn("TK []", out)

    def test_screen_imports_neither_tkinter_nor_pynput(self):
        # main.py import screen ก่อนตั้ง DPI ถ้า screen ดึง tkinter/pynput มาด้วย DPI จะช้าไป
        code, out = run_py("""
import sys
import autoclicker.screen
print("LOADED", sorted(m for m in sys.modules if m.split(".")[0] in ("tkinter", "pynput")))
""")
        self.assertEqual(code, 0, out)
        self.assertIn("LOADED []", out)


class LogicTestsNeedNoStubsTests(unittest.TestCase):
    def test_logic_test_files_import_without_tkinter_or_pynput(self):
        # บล็อก tkinter/pynput ทั้งหมด แล้ว import ไฟล์เทสต์ที่สัญญาว่าไม่ต้อง stub
        # (เคยพลาด: test_model ไป import runner ซึ่งดึง pynput มา บน CI ที่ไม่มีจอจะพัง)
        for test_file in ("test_model", "test_screen", "test_hotkeys"):
            with self.subTest(test_file=test_file):
                code, out = run_py(f"""
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("tkinter", "_tkinter", "pynput"):
            raise ImportError("blocked " + name)
sys.meta_path.insert(0, Block())
sys.path.insert(0, {TESTS!r})
import {test_file}
print("OK")
""")
                self.assertEqual(code, 0, out)
                self.assertIn("OK", out)


class NoCircularImportTests(unittest.TestCase):
    MODULES = (
        "autoclicker",
        "autoclicker.constants",
        "autoclicker.win32",
        "autoclicker.screen",
        "autoclicker.model",
        "autoclicker.hotkeys",
        "autoclicker.runner",
        "autoclicker.markers",
        "autoclicker.ui",
        "autoclicker.ui.dialogs",
        "autoclicker.ui.app",
    )

    def test_each_module_imports_first(self):
        # import วนจะพังเฉพาะตอน module นั้นถูก import เป็นตัวแรก จึงต้องลองทีละตัวใน process ใหม่
        for mod in self.MODULES:
            with self.subTest(mod=mod):
                code, out = run_py(f"""
import sys
sys.path.insert(0, {TESTS!r})
import support
support.install_stubs()
import importlib
importlib.import_module({mod!r})
print("OK")
""")
                self.assertEqual(code, 0, out)


class DpiOrderTests(unittest.TestCase):
    def test_main_sets_dpi_before_tkinter_and_pynput(self):
        # แทน _set_dpi_aware ด้วยตัวที่จดว่าตอนถูกเรียก tkinter/pynput ถูกโหลดไปแล้วหรือยัง
        # แล้วรัน main.py แบบไม่เข้า main() (run_name ไม่ใช่ "__main__")
        code, out = run_py(f"""
import builtins, runpy, sys
sys.path.insert(0, {TESTS!r})
import autoclicker.screen as screen
import support  # ยังไม่ใส่ stub: ไม่งั้นจะเห็น tkinter/pynput ตั้งแต่ก่อนเรียก DPI

calls = []
screen._set_dpi_aware = lambda: calls.append(
    sorted(m for m in sys.modules if m.split(".")[0] in ("tkinter", "pynput")))

# ใส่ stub (ไม่ต้องมีจอ) ตอนที่ main.py import tkinter/pynput/ui ครั้งแรกเท่านั้น
real_import = builtins.__import__
def hook(name, *a, **k):
    if name.split(".")[0] in ("tkinter", "pynput") or name.startswith("autoclicker.ui"):
        support.install_stubs()
    return real_import(name, *a, **k)
builtins.__import__ = hook
try:
    runpy.run_path("main.py", run_name="not_main")
finally:
    builtins.__import__ = real_import
print("CALLS", calls)
""")
        self.assertEqual(code, 0, out)
        self.assertIn("CALLS [[]]", out)  # เรียกครั้งเดียว และตอนนั้นยังไม่มี tkinter/pynput


class VersionTests(unittest.TestCase):
    def test_version_and_title(self):
        from autoclicker import constants

        self.assertRegex(constants.APP_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(constants.APP_TITLE, f"AutoClicker v{constants.APP_VERSION}")
        # APP_NAME เป็นชื่อโฟลเดอร์ settings ห้ามมีเวอร์ชัน ไม่งั้นปุ่มลัดหายทุกครั้งที่อัปเดต
        self.assertEqual(constants.APP_NAME, "AutoClicker")

    def test_build_bat_reads_version_from_constants(self):
        # build.bat ต้องอ่านเวอร์ชันจาก constants (ที่เดียว) ไม่ใช่เขียนเลขซ้ำไว้เอง
        code, out = run_py("from autoclicker.constants import APP_VERSION; print(APP_VERSION)")
        self.assertEqual(code, 0, out)
        with open(os.path.join(ROOT, "build.bat"), encoding="utf-8") as f:
            bat = f.read()
        self.assertIn("from autoclicker.constants import APP_VERSION", bat)
        self.assertIn("--name AutoClicker-%VER%", bat)
        self.assertNotIn(out.strip(), bat)


if __name__ == "__main__":
    unittest.main()
