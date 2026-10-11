"""สร้าง version resource ของ exe (ไฟล์ให้ PyInstaller --version-file) จาก APP_VERSION ใน constants.py

build.bat เรียกสคริปต์นี้ทุกครั้งก่อน build เวอร์ชันจะได้อยู่ที่ constants.py ที่เดียว ไม่ hardcode ซ้ำ
exe ที่มี version resource (ชื่อบริษัท/คำอธิบาย/เวอร์ชัน) โดน Defender จับผิดตัว (false positive) น้อยกว่า exe เปล่าๆ

usage: python tools/make_version_info.py OUT_PATH
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from autoclicker.constants import APP_NAME, APP_VERSION  # noqa: E402  (ไม่ import tkinter/pynput)

AUTHOR = "Nopparuch Lanumthiang"  # ตรงกับ LICENSE
COPYRIGHT = f"Copyright (c) 2026 {AUTHOR} (MIT License)"
EXE_NAME = f"{APP_NAME}.exe"


def version_tuple(version):
    """ "1.0.1" -> (1, 0, 1, 0) Windows ต้องการเลข 4 ช่อง"""
    parts = [int(p) for p in version.split(".")]
    if not 1 <= len(parts) <= 4 or any(p < 0 or p > 65535 for p in parts):
        raise ValueError(f"เวอร์ชันไม่ถูกต้องสำหรับ Windows: {version!r}")
    return tuple(parts + [0] * (4 - len(parts)))


def make_version_info(version=APP_VERSION):
    """ข้อความไฟล์ version info รูปแบบที่ PyInstaller อ่านได้ (VSVersionInfo)"""
    vt = version_tuple(version)
    strings = [
        ("CompanyName", AUTHOR),
        ("FileDescription", APP_NAME),
        ("FileVersion", version),
        ("InternalName", APP_NAME),
        ("LegalCopyright", COPYRIGHT),
        ("OriginalFilename", EXE_NAME),
        ("ProductName", APP_NAME),
        ("ProductVersion", version),
    ]
    string_structs = ",\n".join(f"            StringStruct({k!r}, {v!r})" for k, v in strings)
    return f"""# สร้างอัตโนมัติโดย tools/make_version_info.py ตอน build ห้ามแก้มือ
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vt},
    prodvers={vt},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
{string_structs}
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: python tools/make_version_info.py OUT_PATH")
    out = argv[1]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(make_version_info())
    print(out)


if __name__ == "__main__":
    main(sys.argv)
