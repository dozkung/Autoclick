"""เทสต์การ build: version resource สร้างจาก APP_VERSION และตัวเลือก PyInstaller ที่ลด false positive"""

import os
import re
import subprocess
import sys
import tempfile
import unittest

import support  # ตั้ง sys.path ให้ import autoclicker ได้

ROOT = support.ROOT
sys.path.insert(0, os.path.join(ROOT, "tools"))

import make_version_info as mvi  # noqa: E402

from autoclicker import constants  # noqa: E402


def read_bat():
    with open(os.path.join(ROOT, "build.bat"), encoding="utf-8") as f:
        return f.read()


def pyinstaller_command(bat):
    """บรรทัดคำสั่ง PyInstaller ทั้งก้อน (ต่อบรรทัดที่ลงท้ายด้วย ^)"""
    m = re.search(r"python -m PyInstaller(?:[^\n]*\^\n)*[^\n]*", bat)
    return m.group(0).replace("^\n", " ")


class VersionInfoTests(unittest.TestCase):
    def test_version_tuple(self):
        self.assertEqual(mvi.version_tuple("1.0.1"), (1, 0, 1, 0))
        self.assertEqual(mvi.version_tuple("2.3"), (2, 3, 0, 0))
        for bad in ("1.x", "1.2.3.4.5", "70000.0.0", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mvi.version_tuple(bad)

    def test_fields_come_from_app_version(self):
        text = mvi.make_version_info()
        v = constants.APP_VERSION
        self.assertIn(f"filevers={mvi.version_tuple(v)}", text)
        self.assertIn(f"prodvers={mvi.version_tuple(v)}", text)
        for key, val in [
            ("FileDescription", "AutoClicker"),
            ("ProductName", "AutoClicker"),
            ("FileVersion", v),
            ("ProductVersion", v),
            ("OriginalFilename", "AutoClicker.exe"),
        ]:
            self.assertIn(f"StringStruct({key!r}, {val!r})", text)
        for key in ("CompanyName", "LegalCopyright"):
            self.assertIn(f"StringStruct({key!r},", text)

    def test_other_version_changes_everything(self):
        text = mvi.make_version_info("9.8.7")
        self.assertIn("filevers=(9, 8, 7, 0)", text)
        self.assertIn("StringStruct('FileVersion', '9.8.7')", text)

    def test_script_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sub", "version_info.txt")
            res = subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "make_version_info.py"), out],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(f.read(), mvi.make_version_info())

    def test_pyinstaller_can_parse_it(self):
        try:
            from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file
        except ImportError:
            self.skipTest("ไม่มี PyInstaller")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(mvi.make_version_info("1.2.3"))
            info = load_version_info_from_text_file(path)
            self.assertEqual(info.ffi.fileVersionMS, (1 << 16) | 2)
            self.assertEqual(info.ffi.fileVersionLS, 3 << 16)


class BuildBatTests(unittest.TestCase):
    def test_onedir_without_upx_with_version_icon_hidden_imports(self):
        cmd = pyinstaller_command(read_bat())
        self.assertIn("--onedir", cmd)
        self.assertNotIn("--onefile", cmd)
        self.assertIn("--noupx", cmd)
        self.assertNotRegex(cmd, r"--upx-dir")
        self.assertIn("--version-file build\\version_info.txt", cmd)
        self.assertIn("--icon assets\\app.ico", cmd)
        self.assertIn("--hidden-import pynput.keyboard._win32", cmd)
        self.assertIn("--hidden-import pynput.mouse._win32", cmd)
        self.assertIn("--name AutoClicker ", cmd)  # exe = AutoClicker.exe ตามที่ USER_GUIDE บอก

    def test_version_info_regenerated_before_build_and_zipped_after(self):
        bat = read_bat()
        gen = bat.index("tools\\make_version_info.py build\\version_info.txt")
        build = bat.index("python -m PyInstaller")
        zip_ = bat.index("Compress-Archive")
        self.assertLess(gen, build)
        self.assertLess(build, zip_)
        self.assertIn("-DestinationPath 'dist\\AutoClicker-%VER%.zip'", bat)

    def test_version_info_not_committed(self):
        # ต้องสร้างใหม่ทุก build ห้ามมีไฟล์ค้างใน repo ที่เลขเวอร์ชันอาจไม่ตรง
        self.assertFalse(os.path.exists(os.path.join(ROOT, "version_info.txt")))


if __name__ == "__main__":
    unittest.main()
