"""ข้อมูลจุดคลิก (step), การ validate, ไฟล์โปรไฟล์ และหน่วยเวลา
ห้าม import tkinter: เทสต์ของ module นี้ต้องรันได้โดยไม่ต้อง stub tkinter"""

from .constants import (
    CLICK_LABEL,
    CLICK_TYPES,
    DEFAULT_DEFAULTS,
    DEFAULT_GAP_MS,
    DEFAULT_KEY_HOLD_MS,
    DEFAULT_SETTINGS,
    KEY_TYPE,
    LABEL_TO_TYPE,
    MAX_COUNTDOWN_S,
    MAX_DURATION_MS,
    MAX_GAP_MS,
    MAX_HOVER_MS,
    MAX_JITTER_MS,
    MAX_JITTER_PX,
    MAX_REPEAT,
    MIN_DELAY_MS,
    MODES,
    STEP_TYPES,
    TIME_UNITS,
)
from .hotkeys import hotkey_conflict, hotkey_to_text, parse_hotkey
from .screen import in_corner, out_of_screen


def make_step(
    x,
    y,
    ctype="left",
    delay_ms=500,
    hold_ms=500,
    repeat=1,
    gap_ms=DEFAULT_GAP_MS,
    key_vk=None,
    key_mods=None,
):
    s = {
        "x": x,
        "y": y,
        "type": ctype,
        "delay_ms": delay_ms,
        "hold_ms": hold_ms,
        "repeat": repeat,
        "gap_ms": gap_ms,
    }
    if ctype == KEY_TYPE:  # field ของปุ่มมีเฉพาะ step กดปุ่ม step คลิกหน้าตาในไฟล์เหมือนเดิม
        s["key_vk"] = key_vk
        s["key_mods"] = list(key_mods or [])
    return s


def make_key_step(vk, mods=(), delay_ms=500, hold_ms=DEFAULT_KEY_HOLD_MS, repeat=1, gap_ms=DEFAULT_GAP_MS):
    """step กดปุ่มคีย์บอร์ด: ไม่มีพิกัด (x/y = None)"""
    return make_step(None, None, KEY_TYPE, delay_ms, hold_ms, repeat, gap_ms, vk, list(mods))


def is_key_step(s):
    return s["type"] == KEY_TYPE


def step_key(s):
    """ปุ่มของ step กดปุ่มในรูปแบบเดียวกับปุ่มลัด {"mods": [...], "vk": int}"""
    return {"mods": list(s["key_mods"]), "vk": s["key_vk"]}


def key_text(s):
    return hotkey_to_text(step_key(s))


def _int_field(d, key, default=None):
    v = d.get(key, default)
    if v is None:
        raise ValueError(f"ไม่มีค่า {key}")
    if isinstance(v, bool) or not isinstance(v, int):  # bool เป็น subclass ของ int ต้องกันเอง
        raise ValueError(f"{key} ต้องเป็นจำนวนเต็ม: {v!r}")
    return v


def validate_step(d, origin=(0, 0)):
    """ตรวจ step (จากไฟล์หรือ dialog) คืน step ที่ใช้ได้ ถ้าข้อมูลพังให้ raise ValueError
    origin=None = ข้ามการเช็กโซน kill switch (ใช้ตอนโหลดไฟล์ ให้โหลดขึ้นมาแก้ได้ ไปเช็กตอนกดเริ่มแทน)"""
    if not isinstance(d, dict):
        raise ValueError(f"ข้อมูลจุดต้องเป็น object: {d!r}")
    ctype = d.get("type", "left")
    if ctype not in STEP_TYPES:
        raise ValueError(f"ประเภทคลิกไม่รู้จัก: {ctype}")
    key = None
    if ctype == KEY_TYPE:
        # กดปุ่มไม่มีพิกัด: ไม่มีหมุด ไม่เช็ก kill switch / นอกจอ
        if d.get("x") is not None or d.get("y") is not None:
            raise ValueError("step กดปุ่มต้องไม่มีพิกัด (x/y ต้องเป็น null)")
        try:
            # ใช้กติกาเดียวกับปุ่มลัด: ห้าม Ctrl/Alt/Shift เดี่ยว, Esc, ปุ่ม Windows
            key = parse_hotkey({"vk": d.get("key_vk"), "mods": d.get("key_mods", [])})
        except ValueError as e:
            raise ValueError(f"ปุ่มที่จะกด: {e}") from None
        x = y = None
    else:
        x, y = _int_field(d, "x"), _int_field(d, "y")
    delay_ms = _int_field(d, "delay_ms", 500)
    hold_ms = _int_field(d, "hold_ms", DEFAULT_KEY_HOLD_MS if key else 500)
    if delay_ms < MIN_DELAY_MS:
        raise ValueError(f"รอหลังกดต้องไม่น้อยกว่า {MIN_DELAY_MS} ms")
    if delay_ms > MAX_DURATION_MS:
        raise ValueError("รอหลังกดต้องไม่เกิน 24 ชม.")
    if hold_ms < 0:
        raise ValueError("กดค้างนานต้องไม่ติดลบ")
    if hold_ms > MAX_DURATION_MS:
        raise ValueError("กดค้างนานต้องไม่เกิน 24 ชม.")
    # ไฟล์โปรไฟล์เก่าไม่มี repeat/gap_ms ใช้ค่าเริ่มต้น
    repeat = _int_field(d, "repeat", 1)
    gap_ms = _int_field(d, "gap_ms", DEFAULT_GAP_MS)
    if not 1 <= repeat <= MAX_REPEAT:
        raise ValueError(f"จำนวนครั้งต้องอยู่ระหว่าง 1–{MAX_REPEAT}")
    if not MIN_DELAY_MS <= gap_ms <= MAX_GAP_MS:
        raise ValueError(f"เว้นระหว่างครั้งต้องอยู่ระหว่าง {MIN_DELAY_MS}–{MAX_GAP_MS} ms")
    if key is not None:
        return make_step(None, None, KEY_TYPE, delay_ms, hold_ms, repeat, gap_ms, key["vk"], key["mods"])
    if origin is not None and in_corner(x, y, origin):
        raise ValueError(f"จุด ({x}, {y}) อยู่ในมุม kill switch")
    return make_step(x, y, ctype, delay_ms, hold_ms, repeat, gap_ms)


def parse_profile(data, origin=None):
    """ตรวจไฟล์โปรไฟล์ทั้งก้อนให้ผ่านหมดก่อน คืน (steps, settings, defaults)
    ยังไม่แตะ state ของโปรแกรม ถ้ามีอะไรพังให้ raise ValueError
    ปกติไม่เช็กโซน kill switch (origin=None) เพราะ toggle() เช็กตอนกดเริ่มอยู่แล้ว"""
    if not isinstance(data, dict):
        raise ValueError("ไฟล์โปรไฟล์ต้องเป็น JSON object")
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise ValueError("steps ต้องเป็น list")
    steps = []
    for n, s in enumerate(raw_steps, 1):
        try:
            steps.append(validate_step(s, origin))
        except ValueError as e:
            raise ValueError(f"จุด #{n}: {e}") from e

    raw = data.get("settings", {})
    if not isinstance(raw, dict):
        raise ValueError("settings ต้องเป็น object")
    st = dict(DEFAULT_SETTINGS)
    st["mode"] = raw.get("mode", st["mode"])
    if st["mode"] not in MODES:
        raise ValueError(f"mode ไม่รู้จัก: {st['mode']}")
    st["rounds"] = _int_field(raw, "rounds", st["rounds"])
    if st["rounds"] < 1:
        raise ValueError("rounds ต้องไม่น้อยกว่า 1")
    minutes = raw.get("minutes", st["minutes"])
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not minutes > 0:
        raise ValueError(f"minutes ต้องเป็นตัวเลขมากกว่า 0: {minutes!r}")
    st["minutes"] = float(minutes)
    st["jitter_px"] = _int_field(raw, "jitter_px", st["jitter_px"])
    if not 0 <= st["jitter_px"] <= MAX_JITTER_PX:
        raise ValueError(f"jitter_px ต้องอยู่ระหว่าง 0–{MAX_JITTER_PX}")
    st["jitter_ms"] = _int_field(raw, "jitter_ms", st["jitter_ms"])
    if not 0 <= st["jitter_ms"] <= MAX_JITTER_MS:
        raise ValueError(f"jitter_ms ต้องอยู่ระหว่าง 0–{MAX_JITTER_MS}")
    st["hover_ms"] = _int_field(raw, "hover_ms", st["hover_ms"])  # ไฟล์เก่าไม่มี -> 50
    if not 0 <= st["hover_ms"] <= MAX_HOVER_MS:
        raise ValueError(f"hover_ms ต้องอยู่ระหว่าง 0–{MAX_HOVER_MS}")
    st["countdown_s"] = _int_field(raw, "countdown_s", st["countdown_s"])  # ไฟล์เก่าไม่มี -> 3
    if not 0 <= st["countdown_s"] <= MAX_COUNTDOWN_S:
        raise ValueError(f"countdown_s ต้องอยู่ระหว่าง 0–{MAX_COUNTDOWN_S}")
    st["pause_on_switch"] = raw.get("pause_on_switch", st["pause_on_switch"])  # ไฟล์เก่าไม่มี -> True
    if not isinstance(st["pause_on_switch"], bool):
        raise ValueError(f"pause_on_switch ต้องเป็น true/false: {st['pause_on_switch']!r}")

    raw = data.get("defaults", {})
    if not isinstance(raw, dict):
        raise ValueError("defaults ต้องเป็น object")
    dflt = dict(DEFAULT_DEFAULTS)
    dflt["type"] = raw.get("type", dflt["type"])
    if dflt["type"] not in CLICK_TYPES:
        raise ValueError(f"defaults.type ไม่รู้จัก: {dflt['type']}")
    dflt["delay_ms"] = _int_field(raw, "delay_ms", dflt["delay_ms"])
    if not MIN_DELAY_MS <= dflt["delay_ms"] <= MAX_DURATION_MS:
        raise ValueError(f"defaults.delay_ms ต้องอยู่ระหว่าง {MIN_DELAY_MS}–{MAX_DURATION_MS}")
    dflt["repeat"] = _int_field(raw, "repeat", dflt["repeat"])
    if not 1 <= dflt["repeat"] <= MAX_REPEAT:
        raise ValueError(f"defaults.repeat ต้องอยู่ระหว่าง 1–{MAX_REPEAT}")
    return steps, st, dflt


def to_ms(value_str, unit):
    """แปลงค่าที่กรอกใน UI (รับทศนิยม เช่น "1.5" วินาที) เป็น ms
    ใช้ round() ไม่ใช่ int() เพราะ 0.29*1000 = 289.999... จะได้ 289"""
    if unit not in TIME_UNITS:
        raise ValueError(f"หน่วยไม่รู้จัก: {unit}")
    try:
        v = float(str(value_str).strip())
    except ValueError:
        raise ValueError(f"ต้องเป็นตัวเลข: {value_str!r}") from None
    if v != v or v in (float("inf"), float("-inf")):  # nan / inf
        raise ValueError(f"ต้องเป็นตัวเลข: {value_str!r}")
    if v < 0:
        raise ValueError("ต้องไม่ติดลบ")
    return round(v * TIME_UNITS[unit])


def pick_unit(ms):
    """เลือกหน่วยที่อ่านง่ายสุดสำหรับค่าเดิม (ใช้ตอนเปิด dialog) คืน (value, unit)"""
    if ms > 0 and ms % 60000 == 0:
        return ms // 60000, "นาที"
    if ms > 0 and ms % 1000 == 0:
        return ms // 1000, "วินาที"
    return ms, "ms"


def _fmt_sec(ms):
    return f"{ms / 1000:.3f}".rstrip("0").rstrip(".")


def format_duration(ms):
    """แสดงเวลาในตาราง: "500 ms" / "1.5 วิ" / "2 นาที" / "1 นาที 30 วิ" """
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60000:
        return f"{_fmt_sec(ms)} วิ"
    minutes, rest = divmod(ms, 60000)
    return f"{minutes} นาที" if rest == 0 else f"{minutes} นาที {_fmt_sec(rest)} วิ"


def step_row(n, s):
    """ค่าของ 1 แถวในตาราง (n = เลขลำดับที่คำนวณจากตำแหน่ง) ช่องที่ไม่ใช้กับจุดนี้แสดง "-" """
    key = is_key_step(s)
    return (
        n,
        key_text(s) if key else s["x"],  # step กดปุ่มไม่มีพิกัด ใช้ช่อง X โชว์ชื่อปุ่มแทน
        "-" if key else s["y"],
        CLICK_LABEL[s["type"]],
        s["repeat"],
        format_duration(s["gap_ms"]) if s["repeat"] > 1 else "-",
        format_duration(s["hold_ms"]) if s["type"] in ("hold", KEY_TYPE) else "-",
        format_duration(s["delay_ms"]),
    )


def step_from_form(form):
    """แปลงค่าจาก StepDialog (string ทั้งหมด + หน่วย) เป็น step ยังไม่ validate กติกา
    ข้อความ error บอกชื่อช่อง ผู้ใช้จะได้รู้ว่าผิดตรงไหน"""

    def as_int(key, label):
        try:
            return int(str(form[key]).strip())
        except ValueError:
            raise ValueError(f"{label} ต้องเป็นจำนวนเต็ม") from None

    def as_ms(key, label):
        try:
            return to_ms(form[key], form[key + "_unit"])
        except ValueError as e:
            raise ValueError(f"{label}: {e}") from None

    ctype = LABEL_TO_TYPE[form["type"]]
    if ctype == KEY_TYPE:  # ช่อง X/Y ถูกซ่อน ใช้ปุ่มที่จับไว้แทน
        return make_key_step(
            form["key_vk"],
            form.get("key_mods", []),
            as_ms("delay_ms", "รอหลังครั้งสุดท้าย"),
            as_ms("hold_ms", "กดค้างนาน"),
            as_int("repeat", "จำนวนครั้ง"),
            as_ms("gap_ms", "เว้นระหว่างครั้ง"),
        )
    return make_step(
        as_int("x", "X"),
        as_int("y", "Y"),
        ctype,
        as_ms("delay_ms", "รอหลังครั้งสุดท้าย"),
        as_ms("hold_ms", "กดค้างนาน"),
        as_int("repeat", "จำนวนครั้ง"),
        as_ms("gap_ms", "เว้นระหว่างครั้ง"),
    )


def try_move_step(steps, index, x, y, origin, rect):
    """ย้ายจุดที่ index ไป (x, y) คืน (ok, reason) ถ้าไม่ผ่านจะไม่แตะ steps"""
    if not 0 <= index < len(steps):
        return False, f"ไม่มีจุด #{index + 1}"
    if is_key_step(steps[index]):
        return False, f"จุด #{index + 1} เป็นการกดปุ่ม ไม่มีพิกัดให้ย้าย"
    if out_of_screen(x, y, rect):
        return False, f"ย้ายจุด #{index + 1} ไม่ได้: ({x}, {y}) อยู่นอกจอ"
    try:
        moved = validate_step(dict(steps[index], x=x, y=y), origin)
    except ValueError as e:
        return False, f"ย้ายจุด #{index + 1} ไม่ได้: {e}"
    steps[index] = moved
    return True, f"ย้ายจุด #{index + 1} ไป ({x}, {y})"


def find_key_conflict(steps, hotkeys):
    """หา step กดปุ่มตัวแรกที่ชนปุ่มลัด คืนข้อความ error หรือ None
    เช็กตอนกดเริ่ม (ไฟล์โปรไฟล์อาจตั้งไว้ตอนปุ่มลัดยังเป็นอีกค่า) และตอนกดตกลงใน dialog"""
    for n, s in enumerate(steps, 1):
        if is_key_step(s):
            label = hotkey_conflict(step_key(s), hotkeys)
            if label:
                return f"จุด #{n} กดปุ่ม {key_text(s)} ซึ่งเป็นปุ่มลัด '{label}' แก้ก่อนค่อยเริ่ม"
    return None
