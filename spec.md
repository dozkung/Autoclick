# AutoClicker (Windows) — Spec

> สเปกนี้สำหรับให้ Claude Code พัฒนาต่อ โค้ดที่มีอยู่ (`main.py` + package `autoclicker/` ดูหัวข้อ 3) เป็น reference implementation ให้แก้ให้ตรงสเปก ไม่ต้องเขียนใหม่ทั้งหมด

## 1. เป้าหมาย

โปรแกรม auto clicker บน Windows ที่ตั้งจุดคลิกได้หลายจุด แต่ละจุดมีประเภทคลิกและเวลารอเป็นของตัวเอง โปรแกรมคลิกไล่ตามเลขลำดับ (1 → 2 → 3 → …) แล้ววนกลับไปจุดแรก หยุดได้ตามเงื่อนไขที่ตั้งไว้ แพ็กเป็น `.exe` ไฟล์เดียวได้

**ไม่อยู่ในขอบเขต:** การจับภาพหน้าจอ / image matching, macro คีย์บอร์ด, รองรับ macOS/Linux, ยึดพิกัดกับหน้าต่าง (window-relative)

## 2. Tech stack

| เรื่อง | ใช้ |
|---|---|
| ภาษา | Python 3.10+ |
| UI | `tkinter` + `ttk` (มากับ Python) |
| คุมเมาส์ + global hotkey | `pynput` |
| วาดหมุดขอบเนียน | `Pillow` (ถ้าไม่มี ใช้หมุดแบบธรรมดาแทน ดู 5.8) |
| แพ็ก | PyInstaller (`--onefile --noconsole`) |
| ไฟล์โปรไฟล์ | JSON (UTF-8) |

ห้ามเพิ่ม dependency อื่น ถ้าไม่จำเป็นจริงๆ

## 3. โครงไฟล์

```
main.py                  # entry point: ตั้ง DPI awareness ก่อน แล้วค่อย import ที่เหลือ, main()
autoclicker/
├── __init__.py          # ว่าง (ห้าม import submodule: main.py ต้องตั้ง DPI ก่อน tkinter/pynput)
├── constants.py         # ค่าคงที่ทั้งหมด (MIN_DELAY_MS, สีหมุด, DEFAULT_HOTKEYS ...) ไม่ import อะไร
├── win32.py             # struct / ค่าคงที่ / WinDLL (argtypes ครบ) ของ Win32 ที่ใช้ร่วมกัน
├── screen.py            # _set_dpi_aware, get_virtual_origin/rect, in_corner, out_of_screen, window_dpi_scale
├── model.py             # make_step, validate_step, parse_profile, to_ms, pick_unit, format_duration,
│                        #   step_row, step_from_form, try_move_step
├── hotkeys.py           # key_to_vk, HotkeyMatcher, read_modifiers_async, load/save_hotkeys, hotkey_labels
├── runner.py            # Runner, nudge_mouse, format_status
├── markers.py           # render_marker_image, layered window (Win32), Marker, marker_geometry
└── ui/
    ├── app.py           # App
    └── dialogs.py       # StepDialog, HotkeyDialog
tests/
├── support.py           # stub tkinter/pynput (install_stubs), FakeMouse, helper สร้างข้อมูล
├── ui_support.py        # FakeApp, FakeMarker, FakeListener (import แล้วใส่ stub ให้อัตโนมัติ)
├── test_model.py  test_screen.py  test_hotkeys.py   # ไม่ต้อง stub อะไร
├── test_runner.py                                    # stub แค่ pynput
├── test_markers.py  test_dialogs.py  test_app.py     # stub tkinter + pynput
├── test_keys.py                                      # step กดปุ่ม (Runner/App/StepDialog) stub tkinter + pynput
└── test_structure.py    # ห้าม tkinter ใน logic, ห้าม import วน, DPI ต้องมาก่อน
requirements.txt         # pynput, Pillow
requirements-dev.txt     # + ruff
ruff.toml                # ruff format/check (line-length 110)
build.bat                # สร้าง dist\AutoClicker.exe จาก main.py
spec.md
```

**กติกาการ import:**
- `main.py` ต้องเรียก `_set_dpi_aware()` **ก่อน** import tkinter / pynput / `autoclicker.ui`
  - `screen.py` จึงห้าม import tkinter/pynput
  - `autoclicker/__init__.py` ห้าม import submodule
- `model.py`, `screen.py`, `runner.py` (รวม `hotkeys.py`, `constants.py`, `win32.py`) ห้าม import tkinter เทสต์ของพวกนี้จะได้ไม่ต้อง stub tkinter
- ทิศทาง import มีทางเดียว ห้าม import วน: `constants` / `win32` → `screen` → `model` / `hotkeys` / `runner` / `markers` → `ui.dialogs` → `ui.app` → `main.py`
- ทุกข้อมีเทสต์ใน `tests/test_structure.py` (รันใน subprocess)
- เทสต์ที่ monkeypatch ชื่อที่ `App` ใช้ (เช่น `Runner`, `get_virtual_rect`) ต้อง patch ที่ `autoclicker.ui.app` ซึ่งเป็นที่ที่ `App` อ่านชื่อนั้น ไม่ใช่ที่ module ต้นทาง

## 4. Data model

### Step (จุดคลิก 1 จุด)

| field | type | กติกา |
|---|---|---|
| `x`, `y` | int หรือ null | พิกัดจอแบบ physical pixel ห้ามอยู่ในโซน kill switch (ดู 5.5) ต้องเป็นจำนวนเต็มจริง ทศนิยมหรือ bool ไม่ผ่าน · step กดปุ่ม (`type == "key"`) ต้องเป็น `null` |
| `type` | `"left" \| "right" \| "double" \| "hold" \| "key"` | `key` = กดปุ่มคีย์บอร์ด (ดู 5.11) |
| `key_vk` | int 1–254 | เฉพาะ `type == "key"`: Windows virtual key code ของปุ่มที่จะกด กติกาเดียวกับปุ่มลัด (ห้าม Ctrl/Alt/Shift เดี่ยว, Esc, ปุ่ม Windows) step คลิกไม่มี field นี้ |
| `key_mods` | list ของ `"ctrl"`/`"alt"`/`"shift"` | เฉพาะ `type == "key"`: modifier ที่กดพร้อมกัน (ไม่มี = `[]`) |
| `delay_ms` | int | เวลารอหลัง **คลิกครั้งสุดท้าย** ของจุดนี้ ก่อนไปจุดถัดไป ขั้นต่ำ 10 สูงสุด 86,400,000 (24 ชม.) |
| `hold_ms` | int | ใช้กับ `type == "hold"` (ค่าเริ่มต้น 500) และ `type == "key"` (กดปุ่มค้างนานเท่านี้ ค่าเริ่มต้น 50) ขั้นต่ำ 0 สูงสุด 86,400,000 (24 ชม.) |
| `repeat` | int 1–1000 (ค่าเริ่มต้น 1) | จำนวนครั้งที่คลิกที่จุดนี้ |
| `gap_ms` | int 10–60000 (ค่าเริ่มต้น 100) | เว้นระหว่างคลิกแต่ละครั้งในจุดเดียวกัน (ใช้เมื่อ `repeat > 1`) |

`repeat` และ `gap_ms` ถ้าไม่มีในข้อมูลให้ใช้ค่าเริ่มต้น เพื่อให้ไฟล์โปรไฟล์เก่าโหลดได้ (backward compatible)

**หน่วยเวลา:** ข้อมูลภายในและไฟล์โปรไฟล์เก็บเวลาเป็น **ms (int) เสมอ** ส่วนหน่วย ms / วินาที / นาที มีแค่ใน UI ตอนกรอกและตอนแสดง (ดู 5.2) เพดาน 24 ชม. มีไว้กันพิมพ์ผิดหน่วยแล้วโปรแกรมรอเป็นปี (`gap_ms` มีเพดานของตัวเองที่ 60000 ซึ่งต่ำกว่าอยู่แล้ว)

ค่าที่ไม่ผ่านกติกา (เช่น `delay_ms < 10`, `hold_ms < 0`, `repeat` นอก 1–1000, `gap_ms` นอก 10–60000, ทศนิยม หรือ bool) ให้ **ปฏิเสธ** (`validate_step` raise `ValueError`) ห้ามปรับค่าให้เองแบบเงียบๆ

เลขลำดับ (#) **ไม่เก็บใน data** ให้คำนวณจากตำแหน่งใน list ทุกครั้งที่วาดตาราง

### RunConfig

| field | type | ความหมาย |
|---|---|---|
| `mode` | `"loop" \| "count" \| "time"` | วนไม่จำกัด / วน N รอบ / วนจนครบเวลา |
| `rounds` | int ≥ 1 | ใช้เมื่อ `mode == "count"` |
| `minutes` | float > 0 | ใช้เมื่อ `mode == "time"` |
| `jitter_px` | int 0–50 | สุ่มเพี้ยนพิกัด ±px ทั้งแกน X และ Y |
| `jitter_ms` | int 0–5000 | สุ่มเพี้ยน `delay_ms` และ `gap_ms` ±ms (ผลลัพธ์ต้องไม่ต่ำกว่า 10ms) |
| `hover_ms` | int 0–1000 (ค่าเริ่มต้น 50) | รอ hover หลังย้ายเมาส์ ก่อนคลิกทุกครั้ง (ดู 5.3) ไฟล์เก่าที่ไม่มีให้ใช้ 50 UI เป็น Spinbox "รอ hover (ms)" ในแถวสุ่มเพี้ยน |
| `countdown_s` | int 0–30 (ค่าเริ่มต้น 3) | นับถอยหลังก่อนเริ่มคลิก (ดู 5.10) ไฟล์เก่าที่ไม่มีให้ใช้ 3 |
| `pause_on_switch` | bool (ค่าเริ่มต้น `true`) | หยุดชั่วคราวเมื่อหน้าต่างเป้าหมายไม่อยู่ข้างหน้า (ดู 5.10) ไฟล์เก่าที่ไม่มีให้ใช้ `true` ค่าที่ไม่ใช่ bool ให้ปฏิเสธ |

ค่าที่มาจาก UI ให้บังคับให้อยู่ในช่วงข้างบนก่อนส่งเข้า `Runner` ส่วนค่าที่มาจากไฟล์ ถ้าอยู่นอกช่วงให้ปฏิเสธ (ดู 5.6)

### ไฟล์โปรไฟล์ (JSON)

```json
{
  "version": 1,
  "steps": [{"x": 812, "y": 455, "type": "left", "delay_ms": 500, "hold_ms": 500, "repeat": 3, "gap_ms": 100}],
  "settings": {"mode": "count", "rounds": 10, "minutes": 5, "jitter_px": 3, "jitter_ms": 50, "hover_ms": 50,
               "countdown_s": 3, "pause_on_switch": true},
  "defaults": {"type": "left", "delay_ms": 500, "repeat": 1}
}
```

## 5. ฟีเจอร์

### 5.1 เพิ่มจุด
- **ปุ่มลัด "เพิ่มจุด"** (global hotkey ค่าเริ่มต้น F8 ตั้งเองได้ ดู 5.9) = เพิ่มจุดที่ตำแหน่งเมาส์ตอนนั้น ใช้ type, delay และจำนวนจากแถว "ค่าเริ่มต้นจุดใหม่" (`gap_ms` ใช้ค่าเริ่มต้น 100)
- ปุ่ม **"เพิ่มเอง"** = เปิด dialog กรอกค่าเอง
- ถ้าพิกัดอยู่ในโซน kill switch ให้ปฏิเสธแล้วขึ้นข้อความใน status
- ถ้ากำลังรันอยู่ ปุ่มลัดเพิ่มจุดจะไม่ทำอะไร แค่ขึ้น status ว่า "หยุดก่อนค่อยเพิ่มจุด"

### 5.2 ตารางจุด
- คอลัมน์: `#`, `X`, `Y`, `ประเภท`, `จำนวน`, `เว้น` (ถ้า `repeat == 1` ให้แสดง `-`), `ค้าง` (ถ้าไม่ใช่ hold ให้แสดง `-`), `รอ` (ค่าของแต่ละแถวสร้างจาก `step_row(n, step)`)
  - คอลัมน์เวลา (รอ / เว้น / ค้าง) แสดงด้วย `format_duration(ms)`: น้อยกว่า 1 วิ → `"500 ms"`, น้อยกว่า 1 นาที → `"1.5 วิ"`, ตั้งแต่ 1 นาที → `"2 นาที"` หรือ `"1 นาที 30 วิ"`
- **หน่วยเวลาตอนกรอก:** ช่องเวลาใน dialog (รอหลังครั้งสุดท้าย, เว้นระหว่างครั้ง, กดค้างนาน) และช่อง "รอ" ในค่าเริ่มต้นจุดใหม่ มี Combobox หน่วย `[ms, วินาที, นาที]` ข้างช่องตัวเลข
  - รับทศนิยมได้ เช่น 1.5 วินาที = 1500 ms, 0.5 นาที = 30000 ms
  - แปลงเป็น ms ด้วย `to_ms(value_str, unit)` ซึ่งใช้ `round()` ไม่ใช่ `int()` เพราะ `0.29*1000 = 289.999…` ถ้าไม่ใช่ตัวเลข, ติดลบ, nan หรือ inf ให้ `ValueError`
  - หลังแปลงยัง validate ด้วยกติกาเดิมของหัวข้อ 4
  - ตอนเปิด dialog หรือโหลดไฟล์ เลือกหน่วยให้อัตโนมัติด้วย `pick_unit(ms)` → `(value, unit)`: หาร 60000 ลงตัว = นาที, หาร 1000 ลงตัว = วินาที, ไม่งั้นใช้ ms
  - ช่อง "รอ hover" และ "± เวลา" (สุ่มเพี้ยน) ยังเป็น ms อย่างเดียว
- แถว "ค่าเริ่มต้นจุดใหม่" มี ประเภท, รอ (ตัวเลข + หน่วย) และ **จำนวน** (Spinbox 1–1000 ค่าเริ่มต้น 1) จุดที่เพิ่มด้วยปุ่มลัดหรือปุ่ม "เพิ่มเอง" จะใช้ค่าเหล่านี้
- ดับเบิลคลิกแถว = แก้ไข ปุ่ม Delete = ลบ
- ปุ่มด้านข้าง: เพิ่มเอง, แก้ไข, ▲ ขึ้น, ▼ ลง, ลบ, ล้างทั้งหมด (ล้างทั้งหมดต้องถามยืนยันก่อน)
- ลบหรือย้ายแล้วเลข # ต้องรันใหม่อัตโนมัติ และยังเลือกแถวที่ถูกต้องอยู่
- dialog แก้ไขมีช่อง X, Y, ประเภท, จำนวนครั้ง, เว้นระหว่างครั้ง, รอหลังครั้งสุดท้าย, กดค้างนาน (3 ช่องหลังมีหน่วย) แปลงค่าด้วย `step_from_form` (ข้อความ error บอกชื่อช่อง) แล้ว validate ด้วย `validate_step` ว่า X/Y/จำนวนเป็นจำนวนเต็ม, `delay_ms` 10 ms–24 ชม., `hold_ms` 0–24 ชม., `repeat` 1–1000, `gap_ms` 10–60000 และไม่อยู่ในโซน kill switch ถ้าไม่ผ่านให้ขึ้น error แล้วค้าง dialog ไว้ ห้ามปรับค่าให้เอง
- ระหว่างรัน ให้ไฮไลต์แถวที่กำลังคลิกด้วย **tag สีพื้นหลัง** ห้ามใช้ selection ของตาราง เพื่อให้ผู้ใช้เลือกแถวไปแก้ระหว่างรันได้โดยไม่โดนแย่ง selection (เลขแถวที่ไฮไลต์อิงจาก snapshot ตอนกดเริ่ม)

### 5.3 ประเภทคลิก
| type | พฤติกรรม |
|---|---|
| `left` | คลิกซ้าย 1 ครั้ง |
| `right` | คลิกขวา 1 ครั้ง |
| `double` | คลิกซ้าย 2 ครั้งติดกัน (`click(Button.left, 2)`) |
| `hold` | กดซ้ายค้างไว้ `hold_ms` แล้วปล่อย |

ทุกประเภท ทำซ้ำ `repeat` ครั้งต่อจุด (`Runner._run_step`):
1. คลิก 1 ครั้ง (`Runner._click`) ทำตามลำดับนี้ **ทุกคลิก** รวมถึงคลิกซ้ำในจุดเดียวกัน:
   1. สุ่ม jitter พิกัดใหม่ (ไม่ใช่สุ่มครั้งเดียวต่อจุด) แล้ว clamp ไม่ให้เข้าโซน kill switch
   2. วาร์ปเมาส์ไปที่จุด (`mouse.position = (x, y)` ซึ่ง pynput ใช้ `SetCursorPos`)
   3. **ส่ง mouse-move จริง** ด้วย `nudge_mouse()` คือ `SendInput` แบบ relative (`MOUSEEVENTF_MOVE`) dx = +1 แล้ว −1 เพราะ `SetCursorPos` ไม่เกิด move event เกมที่อัปเดต hover จาก move event (เช่น Roblox) จะยังคิดว่าเมาส์อยู่ที่เดิม แล้วคลิกไปลงที่ตำแหน่ง hover เก่า
      - ถ้าไม่ใช่ Windows หรือเรียกไม่ได้ให้ข้ามเงียบๆ และถ้า nudge raise ให้ข้ามไป Runner ต้องไม่ตาย
      - `Runner(..., nudge=...)` inject ได้ เทสต์ต้อง inject ตัวปลอมเสมอ ไม่งั้นจะขยับเมาส์จริง
   4. รอ `hover_ms` ผ่าน `_wait()` (หยุด / kill switch / deadline ได้ระหว่างรอ ถ้าโดนหยุดตรงนี้จะไม่คลิก)
   5. ถ้าตำแหน่งเมาส์ไม่ตรง `(x, y)` (เช่นเปิด Enhance pointer precision แล้ว +1/−1 ไม่หักล้างกันพอดี) ให้ตั้ง position ซ้ำ เช็กหลังรอ hover เพราะ `SendInput` เข้าคิวแบบ async ถ้าอ่านทันทีอาจยังไม่เห็นผล
   6. คลิกตาม type
2. ถ้ายังไม่ใช่ครั้งสุดท้าย รอ `gap_ms` (± `jitter_ms`) แล้วกลับไปข้อ 1
3. หลังครั้งสุดท้ายรอ `delay_ms` (± `jitter_ms`) แล้วไปจุดถัดไป

- `hold` + `repeat` = กดค้าง `hold_ms` แล้วปล่อย ซ้ำ `repeat` ครั้ง (ปล่อยปุ่มทุกครั้ง อยู่ใน `try/finally`)
- `double` + `repeat` = ดับเบิลคลิก `repeat` ครั้ง
- การรอทุกช่วง (`hover_ms`, `gap_ms`, `delay_ms`, `hold_ms`) ใช้ `_wait()` ซึ่งเช็ก stop, kill switch และ deadline ทุก ≤ 20ms เช่นกดหยุดระหว่างคลิกชุดหนึ่งต้องหยุดทันที ไม่ต้องรอให้ครบ `repeat`

### 5.4 การรัน
- **ปุ่มลัด "เริ่ม/หยุด"** (global hotkey ค่าเริ่มต้น F6 ดู 5.9) หรือปุ่ม ▶/■ = เริ่ม / หยุด ข้อความบนปุ่มแสดงชื่อปุ่มลัดที่ตั้งไว้
- ถ้ายังไม่มีจุดให้กดเริ่มไม่ได้ ขึ้น status แทน
- ตอนกดเริ่ม ให้อ่านขนาด virtual screen ใหม่แล้วเช็กทุกจุดตามลำดับ ถ้าเจอจุดที่ไม่ผ่านให้ไม่เริ่ม แล้วขึ้น status บอกจุดแรกที่เจอ
  - จุดอยู่นอก virtual screen → `จุด #n อยู่นอกจอ (ถอดจอออก?)` (ดู 5.5)
  - จุดอยู่ในโซน kill switch → `จุด #n อยู่ในมุม kill switch แก้ก่อนค่อยเริ่ม`
- ตอนเริ่มรันให้ snapshot list ของ steps ไว้ ถ้าแก้ตารางระหว่างรัน รอบที่กำลังรันจะไม่เปลี่ยนตาม
- กดเริ่มแล้วซ่อนหมุดทันที แล้วนับถอยหลังก่อนคลิกจริง (ดู 5.10)
- `Runner` เรียก `on_status(รอบ, จุด, ครั้งที่, repeat)` ก่อนคลิกทุกครั้ง status bar แสดง `รอบ N · จุด #i` และถ้า `repeat > 1` ให้ต่อท้ายด้วย `(k/n)` เช่น `รอบ 2 · จุด #1 (2/3)` (`format_status`) แล้วไฮไลต์แถวที่กำลังคลิกในตาราง (ดู 5.2)
- เมื่อหยุด status ต้องบอกเหตุผล: `ครบ N รอบ` / `ครบเวลาที่ตั้งไว้` / `หยุดโดยผู้ใช้` / `หยุดฉุกเฉิน (เมาส์ชนมุมซ้ายบนสุดของจอ)` / `สลับไปหน้าต่างเกมก่อนนับถอยหลังจบ` / `หน้าต่างเป้าหมายถูกปิด` / `error: ...`

### 5.5 Kill switch (บังคับมี ปิดไม่ได้)
- โซน kill switch อิง **มุมซ้ายบนของ virtual screen (รวมทุกจอ)** เพราะเป็นขอบจริงที่หยุดเมาส์ไว้ได้
  - origin `(vx, vy)` อ่านจาก `GetSystemMetrics(76)` / `GetSystemMetrics(77)` (`SM_XVIRTUALSCREEN`, `SM_YVIRTUALSCREEN`) ถ้าไม่ใช่ Windows หรือเรียกไม่ได้ให้ใช้ `(0, 0)`
  - โซนคือ `vx <= x <= vx+3 and vy <= y <= vy+3` เช่นถ้ามีจอเสริมอยู่ทางซ้าย origin `(-1920, 0)` จุด `(0,0)` จะไม่ใช่โซน แต่ `(-1920, 0)` เป็นโซน
  - อ่าน origin ใหม่ทุกครั้งที่กดเริ่ม (เผื่อเสียบหรือถอดจอ) แล้วส่งเข้า `Runner` ส่วน `in_corner(x, y, origin)` ต้องรับ origin เป็นพารามิเตอร์
  - ตอนกดเริ่ม ถ้ามีจุดไหนอยู่ในโซนของ origin ปัจจุบัน ให้ปฏิเสธการเริ่มแล้วขึ้น status
  - ตอนเพิ่มหรือแก้จุด (ปุ่มลัดเพิ่มจุด และ dialog) ต้องเช็กโซนด้วย ส่วนตอนโหลดไฟล์ไม่ต้องเช็ก (ดู 5.6)
- **จุดนอกจอ:** `get_virtual_rect()` คืน `(vx, vy, cx, cy)` จาก `GetSystemMetrics(76..79)` (`SM_X/Y/CX/CYVIRTUALSCREEN`) ถ้าไม่ใช่ Windows หรือเรียกไม่ได้ (รวมกรณีที่ cx หรือ cy ≤ 0) ให้คืน `None`
  - `out_of_screen(x, y, rect)` คืนจริงถ้าจุดอยู่นอก `vx..vx+cx-1, vy..vy+cy-1` ถ้า `rect` เป็น `None` ให้คืนเท็จเสมอ (ข้ามการเช็ก)
  - เช็กตอนกดเริ่มตาม 5.4
- ถ้าเมาส์อยู่ในโซนระหว่างรัน ให้หยุดทันที
- ต้องเช็กทุก ≤ 20ms ระหว่างที่รอ ไม่ใช่เช็กแค่ก่อนคลิก
- jitter ต้อง clamp พิกัดไม่ให้หลุดเข้าโซนนี้ ไม่งั้นโปรแกรมจะหยุดตัวเอง

### 5.6 Save / Load
- ปุ่ม "บันทึก…" / "เปิด…" ใช้ file dialog นามสกุล `.json`
- ตอนโหลดต้อง **validate ทั้งไฟล์ให้ผ่านหมดก่อน** ทั้ง `steps`, `settings` และ `defaults` (ฟังก์ชัน `parse_profile`) แล้วค่อยเขียนทับข้อมูลเดิมทีเดียว ถ้าไฟล์พังหรือมีค่าไหนไม่ผ่าน ให้ขึ้น error และข้อมูลเดิมทั้งหมดต้องไม่หายหรือถูกแก้ไปครึ่งเดียว
  - step ตามกติกาหัวข้อ 4 **ยกเว้นโซน kill switch** (`parse_profile(data, origin=None)` ข้ามการเช็กโซน) เพื่อให้โหลดไฟล์ที่มีจุดในโซนขึ้นมาแก้ได้ ส่วนการกันจุดในโซนให้ไปทำตอนกดเริ่ม (5.4)
  - `settings` ตามช่วงใน RunConfig ถ้าค่าผิดชนิดหรืออยู่นอกช่วงให้ปฏิเสธทั้งไฟล์
  - `defaults.type` ต้องเป็น type ที่รู้จัก, `defaults.delay_ms >= 10` และ `defaults.repeat` อยู่ใน 1–1000
- ห้ามโหลดระหว่างที่กำลังรัน
- field ที่ไม่มีในไฟล์ให้ใช้ค่า default แทน ไฟล์เก่าที่ไม่มี `repeat`/`gap_ms` ใน step จะได้ `repeat = 1`, `gap_ms = 100` และถ้าไม่มี `defaults.repeat` จะได้ `1`
- ก่อนบันทึก ให้ตรวจข้อมูลที่จะเขียนด้วย `parse_profile` ตัวเดียวกับตอนโหลด (รวม `defaults.delay_ms >= 10`) ถ้าไม่ผ่านให้ขึ้น error แล้วไม่เขียนไฟล์ ไฟล์ที่เซฟเองต้องโหลดกลับได้เสมอ
- ถ้าบันทึกไฟล์ไม่สำเร็จ (เช่นไม่มีสิทธิ์เขียน) ให้ขึ้น error

### 5.7 อื่นๆ
- มุมขวาบนแสดงพิกัดเมาส์แบบ live (อัปเดตทุก 100ms) เอาไว้ช่วยตั้งจุด
- checkbox "หน้าต่างอยู่บนสุด" ค่าเริ่มต้นเปิด
- ฟอนต์ Tahoma 10 (มีตัวอักษรไทยครบบน Windows) ข้อความ UI เป็นภาษาไทย

### 5.8 หมุดบนจอ (on-screen markers)
- แต่ละ step มีหมุด **วงกลมทึบ** ลอยอยู่บนจอ (`tk.Toplevel` ที่ตั้ง `overrideredirect(True)` และ `-topmost True`)
  - **หน้าตา:** วงกลมทึบสีตามประเภท (ซ้าย = น้ำเงิน, ขวา = ส้ม, ดับเบิล = ม่วง, กดค้าง = แดง) ขอบขาว ~2px และเลขลำดับสีขาวตัวหนาอยู่กลางวง
  - **ป้าย ×n:** ถ้า `repeat > 1` เลขขยับขึ้น แล้วมี `×3` ตัวเล็กอยู่ใต้เลขภายในวง
  - **ขนาดตัวอักษร:** เลขหลายหลักและ ×n ที่หลายหลักใช้ฟอนต์เล็กลงให้พอดีวง ข้อความ, ตำแหน่ง และขนาดฟอนต์มาจาก `marker_text_layout(n, repeat, size)` ใช้ร่วมกันทั้งสองโหมด
  - **ขนาดตาม DPI:** หน้าต่าง `marker_size(scale)` = 30×30 px ที่ 100% (วงกลม ~28px + ขอบเผื่อ 1px) คูณ DPI scale เช่นที่ 150% = 44×44 ขนาดเป็นเลขคู่เสมอ
    - `App.marker_scale` = `GetDpiForWindow(hwnd)/96` ถ้าเรียกไม่ได้ใช้ `tk scaling/(96/72)` แล้วค่อย 1.0 (ไม่ต่ำกว่า 1)
    - ใช้ DPI ของหน้าต่างหลักตอนเปิดโปรแกรม ค่าเดียวทุกจอ
- **โหมดแบบเรียบ (ค่าเริ่มต้นบน Windows):** ขอบเนียนด้วย per-pixel alpha
  - วาดด้วย Pillow ใน `render_marker_image(n, color, repeat, size)` → ภาพ RGBA (ไม่แตะ Win32 จึงเทสต์ได้)
    - วาดใหญ่ 4 เท่าแล้วย่อด้วย LANCZOS (supersampling)
    - ฟอนต์ `C:\Windows\Fonts\tahomabd.ttf` → `arialbd.ttf` → `segoeuib.ttf` → `ImageFont.load_default`
  - `premultiply_bgra(img)` แปลงเป็นไบต์ BGRA แบบ **premultiplied alpha** (r·a/255 ปัดเศษ) ถ้าไม่คูณ alpha ก่อน ขอบโปร่งครึ่งๆ จะสว่างผิด
  - แสดงด้วย `UpdateLayeredWindow` (ULW) บน HWND ระดับบนสุด `int(top.wm_frame(), 16)`
    - ใช้ 32-bit top-down DIB section (`BITMAPINFOHEADER`, `BI_RGB`, `biHeight` ติดลบ) และ `BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)` กับ `ULW_ALPHA` โดย `pptDst` = มุมซ้ายบนตามศูนย์กลาง
    - user32/gdi32 ใช้ `WinDLL` ของตัวเองที่ตั้ง `argtypes`/`restype` ครบ (handle 64-bit) ห้ามไปแก้ `ctypes.windll` ที่ pynput ใช้ร่วม
    - คืน resource GDI ครบทุกครั้งใน `finally` คือ SelectObject เดิมกลับ, DeleteObject, DeleteDC และ ReleaseDC (ลองจริงแล้ว: สร้าง/ทำลายหมุด 200 รอบ GDI objects ไม่เพิ่ม)
  - **ลำดับตอนแสดงครั้งแรก:** Tk สร้าง wrapper HWND ตอน map ครั้งแรก จึงวาดด้วย ULW ใน `Marker.deiconify()` ครั้งแรก
    1. ตั้ง `-alpha 0` ไว้ก่อน กันเห็นสี่เหลี่ยมพื้นเทาแวบหนึ่ง
    2. ล้าง `WS_EX_LAYERED` แล้วตั้งใหม่ (`make_layered`) เพราะหลัง `SetLayeredWindowAttributes` (ซึ่ง Tk `-alpha` เรียก) ULW จะ fail จนกว่าจะทำแบบนี้
    3. เรียก ULW
  - ซ่อนแล้วแสดงใหม่ (ตอนเริ่ม/หยุดรัน) ภาพยังอยู่ ไม่ต้องวาดใหม่
  - **ห้ามใช้ `-transparentcolor`** บนหน้าต่างที่ใช้ ULW (ใช้ด้วยกันไม่ได้)
  - ตอนลากย้ายด้วย `geometry()` (ซึ่งเป็น SetWindowPos) ภาพ layered ติดไปด้วย ไม่ต้องวาดใหม่ทุก motion
- **โหมดแบบธรรมดา (fallback):** Canvas + `-transparentcolor` (ขอบเป็นพิกเซล) ใช้เมื่อไม่ใช่ Windows, import Pillow ไม่ได้ (`_load_pil()` คืน `None`) หรือ Win32 call ไหน fail ระหว่างสร้าง/แสดงหมุด
  - หมุดต้องขึ้นเสมอ ห้ามโปรแกรมล้ม
  - `App.marker_fallback()` ปิดโหมดแบบเรียบไปตลอดที่เหลือ และขึ้น status เตือน **ครั้งเดียว** ว่า `หมุดแบบเรียบไม่พร้อม ใช้แบบธรรมดา`
  - Canvas ห้ามใช้ anti-aliasing เพราะขอบจะติดสี transparentcolor เป็นขอบชมพู (Tk บน Windows ไม่ทำอยู่แล้ว)
  - ฟอนต์ใช้ขนาดติดลบ (pixel) เพราะ scale แล้ว ถ้าใช้ point Tk จะขยายตาม DPI ซ้ำอีกรอบ
- ศูนย์กลางหมุด (pixel `size//2` ของหน้าต่าง) ต้องตรงกับพิกัด `(x, y)` ของ step เป๊ะ คือวางหน้าต่างที่ `(x - size//2, y - size//2)` และต้องรองรับพิกัดติดลบ (จอเสริมทางซ้าย)
  - `marker_geometry(x, y, size)` คืน geometry string เช่น `"30x30+-1935+-15"` ห้ามใช้ `"-1935"` เพราะใน Tk ตัวเลขที่นำหน้าด้วย `-` แปลว่าวัดจากขอบขวา/ล่าง
- **การรับ event:** bind ที่ Toplevel (ไม่ใช่ที่ canvas) ใช้ได้ทั้งสองโหมด ส่วนที่ทึบรับ press/drag/double-click ของ Tk ส่วนที่ alpha = 0 (หรือสี transparentcolor) คลิกทะลุไปถึงหน้าต่างข้างใต้
- **ลาก** หมุดด้วยเมาส์ซ้าย = ย้ายจุด (ขยับน้อยกว่า 3px ถือว่าเป็นคลิก)
  - ระหว่างลากขยับแค่หมุด แล้วค่อยอัปเดต step และตารางตอนปล่อยเมาส์
  - ตอนปล่อยให้ใช้ `try_move_step(steps, index, x, y, origin, rect)` → `(ok, reason)` ซึ่ง validate ด้วย `validate_step(..., get_virtual_origin())` และ `out_of_screen(..., get_virtual_rect())` ถ้าไม่ผ่านจะไม่แก้ steps หมุดดีดกลับตำแหน่งเดิม และ status บอกเหตุผล
  - ห้ามลากหมุดระหว่างรัน
- **คลิก** หมุด = เลือกแถวนั้นในตาราง ส่วน **ดับเบิลคลิก** = เปิด `StepDialog` แก้ไขจุดนั้น
- หมุดต้องตรงกับ `self.steps` เสมอ ไม่ว่าจะเพิ่ม, ลบ, แก้, ย้ายลำดับ, ล้าง หรือโหลดไฟล์ โดยให้ `refresh()` เป็นจุดเดียวที่สร้างหมุด (destroy ของเก่าทั้งหมดก่อน ไม่ให้หน้าต่างรั่ว) หมุดถูกสร้างแบบซ่อนไว้ก่อน แล้วค่อยแสดงตามสถานะ
- checkbox **"แสดงหมุด"** (ค่าเริ่มต้นเปิด) และปุ่มลัด **"แสดง/ซ่อนหมุด"** (ค่าเริ่มต้น **F7** ดู 5.9) ใช้สลับแสดง/ซ่อนหมุด checkbox แสดงชื่อปุ่มลัดที่ตั้งไว้
- **ระหว่างรัน:**
  - `toggle()` ต้องซ่อนหมุดทั้งหมด (และ `update_idletasks()`) **ก่อน** start `Runner` ไม่งั้น clicker จะคลิกโดนหมุดแทนแอปเป้าหมาย
  - พอได้ข้อความ `"done"` ให้แสดงหมุดกลับตามสถานะ checkbox ให้ใช้ flag `markers_suspended` ตัดสิน ห้ามใช้ `runner.is_alive()` เพราะ `on_done` ถูกเรียกใน `finally` ก่อนเธรดจบจริง
  - ถ้าแก้ตารางระหว่างรัน หมุดที่สร้างใหม่ต้องยังซ่อนอยู่
- ตอนปิดโปรแกรมให้ destroy หมุดทั้งหมด

### 5.9 ปุ่มลัด (ตั้งเองได้)
| หน้าที่ (`action`) | ทำอะไร | ค่าเริ่มต้น |
|---|---|---|
| `toggle` | เริ่ม / หยุด | F6 |
| `add` | เพิ่มจุดที่ตำแหน่งเมาส์ | F8 |
| `markers` | แสดง / ซ่อนหมุด | F7 (ไม่ใช้ F9 เพราะชนกับ Developer Console ของ Roblox) |

- ใช้ได้ทั้งตอนที่หน้าต่างโปรแกรม focus อยู่และไม่ได้ focus (global hotkey ผ่าน `pynput.keyboard.Listener`)
- **รูปแบบ:** ปุ่มลัดเก็บเป็น `{"mods": [...], "vk": int}` โดย `mods` เป็น subset ของ `ctrl`, `alt`, `shift` (เรียงตามลำดับนี้เสมอ) ส่วน `vk` เป็น Windows virtual key code
  - **ต้องจับคีย์ด้วย vk ห้ามใช้ตัวอักษร** เพราะบนคีย์บอร์ดไทยตัวอักษรจะเปลี่ยนตามภาษาที่เลือก (A → ฟ) แต่ vk เท่าเดิม vk ของ pynput อยู่ที่ `KeyCode.vk` หรือ `Key.xxx.value.vk` (`key_to_vk`)
  - modifier ซ้าย/ขวานับเป็นตัวเดียวกัน (`0x10/0xA0/0xA1` = shift, `0x11/0xA2/0xA3` = ctrl, `0x12/0xA4/0xA5` = alt)
  - รับทั้งคีย์เดี่ยวและคอมโบที่มี Ctrl/Alt/Shift (เช่น Ctrl+Shift+1) แต่ **ไม่รับ** modifier เดี่ยวๆ, ไม่รับ Esc และไม่รับปุ่ม Windows (`0x5B`/`0x5C` ระบบจองไว้)
  - หน้าที่ต้องมีครบทั้ง 3 พอดี และ **ห้ามสองหน้าที่ใช้ปุ่มเดียวกัน**
  - ฟังก์ชัน: `parse_hotkey(data)`, `validate_hotkeys(dict)`, `assign_hotkey(hotkeys, action, hk)` (ตั้งปุ่มให้หน้าที่เดียว ซ้ำแล้ว raise) และ `hotkey_to_text(hk)` (เช่น `"Ctrl+Shift+1"`, `"F6"`)
- **การ match (`HotkeyMatcher`):**
  - รับ `press(vk)` / `release(vk)` แล้วคืนชื่อ action ที่ trigger
  - เก็บ set ของปุ่มที่กดค้างอยู่ แล้ว trigger **เฉพาะตอนกดลงครั้งแรก** autorepeat ตอนกดค้างไม่นับ และปุ่มจะถูกเอาออกจาก set ตอน `on_release`
  - คอมโบต้องกด modifier ค้างไว้ก่อนค่อยกดคีย์หลัก และ modifier ต้องตรงกันพอดี (Ctrl+F6 ไม่ใช่ F6)
  - ตอนกดคีย์หลัก modifier ที่กดอยู่ให้อ่านจาก **สถานะจริง** ด้วย `GetAsyncKeyState(0x11 / 0x12 / 0x10) & 0x8000` (`read_modifiers_async`) ไม่นับจาก set เพราะ event ตอนปล่อยอาจหาย (Win+L, UAC) แล้ว modifier จะค้างใน set
    - ตัวอ่านนี้ inject ได้ผ่าน `HotkeyMatcher(hotkeys, read_mods=...)` ถ้าไม่ใช่ Windows, อ่านไม่ได้ หรือตัวอ่านคืน `None` ให้ fallback ไปนับจาก set
    - set ยังใช้กัน autorepeat ของคีย์หลักเหมือนเดิม
  - ถ้า `paused = True` จะไม่ trigger อะไรเลย แต่ยังเก็บ set ของปุ่มที่กดค้างอยู่ (ปลด pause แล้วปุ่มที่ยังค้างอยู่จะไม่ trigger) และบันทึก `last_combo` ไว้ให้ dialog จับคีย์ใช้
- **Thread safety:** callback ของ listener (`on_press`/`on_release`) ห้ามแตะ tkinter ต้องส่งข้อความผ่าน queue เท่านั้น ทั้ง action และคีย์ที่จับได้ให้ dialog (`("captured", hk)`)
- **UI:**
  - ปุ่ม **"ปุ่มลัด…"** เปิด dialog ที่มี 3 แถว (ชื่อหน้าที่ + ปุ่มแสดงคีย์ปัจจุบัน) กดปุ่มในแถวแล้วขึ้น `กดปุ่มที่ต้องการ… (Esc = ยกเลิก)` แล้วจับคีย์ถัดไปที่กด Esc = ยกเลิกการจับ
  - คีย์ที่จับมาจาก pynput listener ตัวเดียวกับที่ใช้ match ปุ่มลัด ไม่ได้มาจาก key event ของ Tk เพื่อให้ได้ vk ชุดเดียวกัน
  - ถ้าตั้งซ้ำกับหน้าที่อื่น ให้ขึ้น error ใน dialog และคงค่าเดิมไว้
  - มีปุ่ม "คืนค่าเริ่มต้น", "บันทึก" และ "ยกเลิก"
  - **ระหว่างที่ dialog เปิดอยู่ ปุ่มลัดทุกตัวต้องปิดชั่วคราว** (`matcher.paused`) และเปิด dialog ระหว่างรันไม่ได้
  - ข้อความทุกที่ที่แสดงชื่อปุ่มลัด (แถบบนสุด, ปุ่ม ▶ เริ่ม / ■ หยุด, checkbox แสดงหมุด, status ตอนยังไม่มีจุด) สร้างจาก `hotkey_labels(hotkeys)` และอัปเดตทันทีหลังบันทึก
  - กดบันทึกแล้ว ต้องหยุด listener ตัวเก่า (`stop()` + `join(timeout=1)`) ก่อนสร้างตัวใหม่ ห้ามมี listener ค้างสองตัว
- **การเก็บค่า:** ปุ่มลัดเป็นค่าของเครื่อง ไม่ใช่ของโปรไฟล์ เก็บที่ `%APPDATA%\AutoClicker\settings.json` แยกจากไฟล์โปรไฟล์ที่ save/load
  ```json
  {"version": 1, "hotkeys": {"toggle": {"mods": [], "vk": 117}, "add": {"mods": [], "vk": 119}, "markers": {"mods": [], "vk": 118}}}
  ```
  - อ่านตอนเปิดโปรแกรม ถ้าไม่มีไฟล์ใช้ค่าเริ่มต้นเงียบๆ และหน้าที่ไหนไม่มีในไฟล์ใช้ค่าเริ่มต้นของหน้าที่นั้น
  - ถ้าไฟล์พังหรือค่าไม่ถูก (รวมกรณีปุ่มซ้ำกัน) ให้ใช้ค่าเริ่มต้นทั้งชุดแล้วขึ้น status เตือน **ห้ามทำให้โปรแกรมเปิดไม่ขึ้น**
  - เขียนลงไฟล์ `.tmp` ก่อน แล้วค่อย `os.replace` ทับไฟล์จริง ถ้าเขียนไม่ได้ให้ขึ้น error ใน dialog

### 5.10 นับถอยหลัง + หยุดชั่วคราวเมื่อสลับหน้าต่าง
ทั้งสองอย่างทำงานคู่กัน: ระหว่างนับถอยหลังผู้ใช้สลับไปหน้าต่างเกม แล้วหน้าต่างที่อยู่ข้างหน้าตอนนับถอยหลังจบจะถือเป็น **หน้าต่างเป้าหมาย**

- **UI:** แถว "ตอนเริ่ม:" ในกรอบตั้งค่า มี Spinbox "นับถอยหลัง (วิ)" 0–30 (ค่าเริ่มต้น 3) และ checkbox "หยุดเมื่อสลับหน้าต่าง" (ค่าเริ่มต้นเปิด) ทั้งสองค่าเก็บใน `settings` ของโปรไฟล์ (ดู RunConfig)
- **นับถอยหลัง** (`Runner._countdown`):
  - กดเริ่มแล้วซ่อนหมุดทันที แล้ว status แสดง `เริ่มใน 3…` → `เริ่มใน 2…` → `เริ่มใน 1…` (`countdown_text`) ทีละวินาที
  - นับใน Runner ผ่าน `_wait()` จึงกดหยุด (F6) หรือชนมุม kill switch ยกเลิกได้ระหว่างนับ และจะไม่มีคลิกเลย
  - โหมดจำกัดเวลา: deadline เริ่มนับ **หลัง** นับถอยหลังจบ
- **เลือกหน้าต่างเป้าหมาย** (ตอนนับถอยหลังจบ และเปิด `pause_on_switch` อยู่):
  - `foreground_window()` = `GetForegroundWindow` แล้ว `GetAncestor(GA_ROOT)`
  - ถ้าหน้าต่างนั้นเป็นของโปรแกรมเราเอง (`GetWindowThreadProcessId` == `os.getpid()`) ให้หยุดทันที reason `สลับไปหน้าต่างเกมก่อนนับถอยหลังจบ`
  - ถ้าไม่ใช่ Windows หรืออ่าน foreground ไม่ได้ (คืน `None`) ให้ปิดฟีเจอร์นี้เงียบๆ แล้วคลิกได้ตามเดิม
- **เช็กหน้าต่างเป้าหมาย:** ใน `_wait()` ทุก ≤100ms (`FG_CHECK_S`) และเช็กทันทีตอนเริ่มทุก `_wait` นอกจากนี้ `_click` เรียก `_wait(0)` ก่อนคลิกจริงทุกครั้ง จึงเท่ากับเช็กก่อนทุกคลิก
  - **foreground ไม่ใช่เป้าหมาย:** หยุดชั่วคราว (`_pause`) โดยไม่คลิก status `หยุดชั่วคราว: หน้าต่างเกมไม่ได้อยู่ข้างหน้า`
  - **กลับมาเป็นเป้าหมาย:** รอต่อเนื่องอีก 500ms (`RESUME_DELAY_S` ถ้าหลุดอีกรอบระหว่างนี้ต้องนับใหม่) แล้วทำต่อจาก step เดิม และส่ง status ของ step นั้นซ้ำ
    - ถ้าหยุดชั่วคราวระหว่างรอ hover ให้วาร์ปเมาส์, nudge และรอ hover ใหม่ เพราะผู้ใช้อาจขยับเมาส์ไปแล้ว
    - ถ้าหลุดระหว่างกดค้าง (`hold`) ให้ปล่อยปุ่มทันที (ห้ามค้างปุ่มไว้ระหว่างหยุด) พอกลับมาให้กดใหม่ทั้งครั้ง
  - **ระหว่างหยุดชั่วคราว:** F6 และ kill switch ยังหยุดได้ และ deadline ของโหมดเวลายังเดินต่อ
  - **หน้าต่างเป้าหมายถูกปิด** (`IsWindow` = false ไม่ว่าจะกำลังทำงานหรือหยุดชั่วคราวอยู่): หยุดถาวร reason `หน้าต่างเป้าหมายถูกปิด`
- **การทดสอบ:** `Runner(..., foreground=, is_window=, window_pid=)` inject ได้เหมือน `nudge` เทสต์ต้อง inject ตัวปลอมเสมอ ไม่งั้นจะไปอ่านหน้าต่างจริงของเครื่อง
- **ข้อความระหว่างรัน:** ข้อความที่ไม่ใช่สถานะคลิก (นับถอยหลัง, หยุดชั่วคราว) ส่งผ่าน `on_notice(text)` → queue `("notice", text)` และใช้ status throttle แบบเดียวกับ `status`

### 5.11 Step กดปุ่มคีย์บอร์ด (`type == "key"`)

ใช้กับของในเกมที่กดด้วยคีย์บอร์ด เช่น ProximityPrompt ของ Roblox (ปุ่ม E) ตั้งลำดับแบบ คลิก → กด E → คลิก ได้

- **เพิ่ม:** ปุ่ม "เพิ่มปุ่มคีย์บอร์ด…" ข้างปุ่ม "เพิ่มเอง" (เริ่มที่ปุ่ม E) หรือเปลี่ยนประเภทใน dialog เป็น "กดปุ่ม"
  - dialog ซ่อนช่อง X/Y แสดงปุ่ม "เลือกปุ่ม…" กดแล้วจับปุ่มถัดไปผ่าน pynput listener ตัวเดียวกับปุ่มลัด (`App.begin_key_capture` / `end_key_capture`) ได้ vk ชุดเดียวกัน ระหว่างจับปุ่มลัดทุกตัวปิด Esc = ยกเลิก
  - ระหว่างจับปุ่ม Enter/Esc ห้ามไปกดตกลง/ปิด dialog ปิด dialog กลางคันต้องเปิดปุ่มลัดคืน
- **ไม่มีพิกัด:** ไม่มีหมุดบนจอ (หมุดของ step อื่นยังใช้เลข # ตามตาราง), ไม่เช็กนอกจอ/kill switch ตอนกดเริ่ม, ลากย้ายไม่ได้, ตารางคอลัมน์ X แสดงชื่อปุ่ม (เช่น `Ctrl+E`) คอลัมน์ Y แสดง `-` คอลัมน์ค้างแสดง `hold_ms`
- `repeat` / `gap_ms` / `delay_ms` / jitter เวลา ใช้เหมือน step คลิก ส่วน jitter พิกัดและรอ hover ไม่เกี่ยว (ไม่ยุ่งกับเมาส์เลย)
- **การกด (Runner):** เช็กหน้าต่างเป้าหมายก่อนกด (5.10) → กด mods ตามลำดับ Ctrl/Alt/Shift → กดปุ่ม → รอ `hold_ms` ผ่าน `_wait` → ปล่อยปุ่ม → ปล่อย mods ย้อนลำดับ
  - ส่งด้วย `SendInput` แบบ **scan code** (`KEYEVENTF_SCANCODE`, scan code จาก `MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)`) **ห้ามใช้** `pynput.keyboard.Controller`: เกมอย่าง Roblox อ่านปุ่มจาก scan code ถ้าส่งแค่ vk เกมไม่รับ ถ้า MapVirtualKey คืน 0 ให้ส่ง vk แทน
  - ลูกศร / Insert / Delete / Home / End / PageUp / PageDown / NumLock / Num / ต้องใส่ `KEYEVENTF_EXTENDEDKEY` (`EXTENDED_VKS`) ไม่งั้นกลายเป็นปุ่มบน numpad
  - **ปล่อยทุกปุ่มเสมอ** (`_release_keys` ใน finally ของการกดและของ `run()`) แม้โดนหยุด/ชนมุม/ปล่อยตัวไหนพังก็ต้องปล่อยตัวที่เหลือต่อ ไม่งั้น Ctrl/Shift ค้างทั้งเครื่อง
  - หน้าต่างเป้าหมายหลุดระหว่างกดค้าง: ปล่อยปุ่มก่อน หยุดชั่วคราว แล้วกดใหม่ทั้งครั้ง (เหมือนเมาส์กดค้าง)
  - `SendInput` ส่งไม่สำเร็จ (มักเพราะเกมรันแบบ admin) = raise → Runner หยุดด้วย `error: ...` ไม่ใช่กดไม่ติดเงียบๆ
  - `send_key` inject เข้า Runner ได้ (`key_sender=`) เทสต์ต้อง inject เสมอ ห้ามกดปุ่มจริง
- **กันปุ่มลัดทำงานเอง** (เช่น step กด F6 = หยุดตัวเอง) 2 ชั้น:
  1. ห้ามตั้งปุ่มของ step ให้ตรงกับปุ่มลัด (เทียบ mods ตรงตัวแบบ matcher: Shift+F6 ≠ F6) เช็กตอนจับปุ่มและตอนกดตกลงใน dialog และ **ตอนกดเริ่ม** (`find_key_conflict`) เพราะโปรไฟล์อาจเซฟไว้ตอนปุ่มลัดเป็นค่าอื่น
  2. listener ข้าม event ที่ `injected = True` (pynput ≥ 1.8 ส่ง flag นี้มา, รุ่นเก่าไม่มี flag จึงมีแค่ชั้นที่ 1)
- ค่าเริ่มต้นจุดใหม่ (`defaults.type`) ยังเป็นได้แค่ประเภทคลิก เพราะปุ่มลัดเพิ่มจุดใช้ตำแหน่งเมาส์
- ไฟล์โปรไฟล์เก่าโหลดได้เหมือนเดิม step คลิกไม่มี `key_vk` / `key_mods` (โปรแกรมเวอร์ชันก่อนหน้าจะเปิดไฟล์ที่มี step กดปุ่มไม่ได้ เพราะไม่รู้จัก `type == "key"`)

ตัวอย่าง step ใน JSON:

```json
{"x": null, "y": null, "type": "key", "key_vk": 69, "key_mods": [], "delay_ms": 500, "hold_ms": 50, "repeat": 1, "gap_ms": 100}
```

เทสต์มือ: กด E ใน Roblox ที่ ProximityPrompt จริง, ตั้ง Ctrl+A ใน Notepad (ต้องเลือกข้อความทั้งหมด), กดค้าง 2000ms แล้วกด F6 กลางคัน (Ctrl/Shift ต้องไม่ค้าง ลองพิมพ์ต่อดู), ลองตั้งปุ่มเป็น F6 (ต้องขึ้น error)

## 6. ข้อกำหนดด้านเทคนิค (ห้ามพลาด)

1. **DPI awareness** — เรียก `SetProcessDpiAwareness(2)` (fallback เป็น `SetProcessDPIAware()`) **ก่อน** import pynput และก่อนสร้าง `Tk()` ไม่งั้นจอที่ตั้ง scaling 125/150% พิกัดจะคลาด
2. **Thread safety** — callback ของ pynput และ worker thread **ห้ามแตะ tkinter ตรงๆ** ให้ส่งข้อความผ่าน `queue.Queue` แล้วให้ UI thread poll ทุก ~30ms ผ่าน `root.after`
3. **หยุดได้ทันที** — ห้ามใช้ `time.sleep(delay)` ก้อนเดียว ให้รอผ่าน `threading.Event.wait()` เป็นช่วงละไม่เกิน 20ms แล้วเช็ก stop / kill switch / deadline ทุกช่วง ตั้ง delay 30 วิไว้ก็ต้องหยุดได้ภายใน < 100ms
4. **ห้ามให้ปุ่มเมาส์ค้าง** — `hold` ต้องอยู่ใน `try/finally` เพื่อ `release()` เสมอ ใน `run()` ก็ต้องมี finally ปล่อยปุ่มที่ยังค้างอยู่ด้วย ตอนปิดหน้าต่างให้ `stop()` แล้ว `join(timeout=1)` ก่อน destroy
5. **ห้ามเธรดตายเงียบ** — worker ต้องจับ exception แล้วรายงานเป็น `error: ...` ผ่าน queue
6. **delay ขั้นต่ำ 10ms** กันลูปเปล่ากิน CPU 100%
7. **status throttle** — ใน 1 รอบ poll ให้วาดแค่ status ล่าสุด ไม่ต้องวาดทุกข้อความ

## 7. Build

`build.bat`:
```bat
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --noconsole --name AutoClicker ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  main.py
```
ต้องใส่ hidden-import เพราะ pynput เลือก backend แบบ dynamic import ถ้าไม่ใส่ exe จะเปิดแล้วปิดทันทีโดยไม่มี error ให้เห็น

## 8. Acceptance criteria

### เทสต์อัตโนมัติ (`tests/`, รันด้วย `python -m unittest discover -s tests` บน CI / Linux ได้โดยไม่ต้องมีจอ)
ให้ stub `pynput` กับ `tkinter` แล้วเทสต์ `Runner` ด้วย fake mouse ที่บันทึก log การคลิกไว้:

- [ ] 3 จุด (`left`, `right`, `double`) × `count=3` → คลิก 9 ครั้ง ตามลำดับ ที่พิกัดถูก จบด้วย reason `ครบ 3 รอบ`
- [ ] `delay_ms=30000` แล้วเรียก `stop()` → thread จบภายใน 0.3s
- [ ] `hold` ที่ `hold_ms=30000` แล้วเรียก `stop()` กลางคัน → มี `press` ตามด้วย `release` และไม่มีปุ่มค้าง
- [ ] `mode=time, minutes=0.5/60` → จบในราว 0.5s ด้วย reason `ครบเวลาที่ตั้งไว้`
- [ ] ย้าย fake mouse ไปที่ `(0,0)` ระหว่างรัน → หยุดด้วย reason kill switch
- [ ] จุดที่ `(4,4)` + `jitter_px=10` × 50 รอบ → ไม่มีคลิกไหนตกในโซน kill switch
- [ ] `validate_step({"x": 1})` → raise `ValueError`
- [ ] โหลดไฟล์ JSON พัง → `steps` เดิมยังอยู่ครบ

### เทสต์มือบน Windows
- [ ] ปุ่มลัดเพิ่มจุด (ค่าเริ่มต้น F8) เพิ่มจุดได้ตรงตำแหน่งเมาส์ ทั้งตอน scaling 100% และ 150%
- [ ] ปุ่มลัดเริ่ม/หยุด (ค่าเริ่มต้น F6) ใช้ได้ ทั้งตอนที่หน้าต่างโปรแกรม focus อยู่และไม่ได้ focus
- [ ] ลากเมาส์ไปมุมซ้ายบนระหว่างรัน → หยุดทันที
- [ ] Save → ปิดโปรแกรม → Load → ได้ข้อมูลเดิมครบ
- [ ] `build.bat` สร้าง `dist\AutoClicker.exe` ที่ดับเบิลคลิกแล้วใช้งานได้ ไม่มีหน้าต่าง console

## 9. งานต่อ (optional — ทำหลังข้อ 8 ผ่านหมดแล้ว)

- จำ path ของโปรไฟล์ล่าสุด แล้วโหลดอัตโนมัติตอนเปิดโปรแกรม

## 10. ข้อควรรู้ (ใส่ใน README ด้วย)

- ถ้าแอปเป้าหมายรันแบบ Administrator ตัว AutoClicker ต้องรันแบบ admin ด้วย (Windows UIPI จะทิ้ง input จากโปรเซสที่สิทธิ์ต่ำกว่าแบบเงียบๆ)
- เกมที่อ่าน raw input หรือมี anti-cheat ระดับ kernel อาจไม่รับคลิกจำลอง หรือตรวจจับได้
- Windows Defender อาจเตือน exe เป็น false positive เพราะโปรแกรมคุมเมาส์และดัก keyboard
