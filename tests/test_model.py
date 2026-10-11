"""เทสต์ model: step, validate, ไฟล์โปรไฟล์, หน่วยเวลา (ไม่ต้อง stub tkinter/pynput)"""

import unittest

import support  # noqa: F401  (import เพื่อตั้ง sys.path ให้ import autoclicker ได้)
from autoclicker import (
    constants,
    model,
)
from support import step


class ValidateTests(unittest.TestCase):
    def test_missing_y_raises(self):
        with self.assertRaises(ValueError):
            model.validate_step({"x": 1})

    def test_rejects_bad_values(self):
        bad = [
            "not a dict",
            {"x": 0, "y": 0},  # อยู่ในโซน kill switch
            {"x": 10.5, "y": 10},  # ไม่ใช่จำนวนเต็ม
            {"x": True, "y": 10},
            {"x": 10, "y": 10, "type": "middle"},
            {"x": 10, "y": 10, "delay_ms": 9},
            {"x": 10, "y": 10, "hold_ms": -1},
        ]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(ValueError):
                model.validate_step(d)

    def test_fills_defaults(self):
        s = model.validate_step({"x": 10, "y": 20})
        self.assertEqual(
            s, {"x": 10, "y": 20, "type": "left", "delay_ms": 500, "hold_ms": 500, "repeat": 1, "gap_ms": 100}
        )

    def test_corner_uses_origin(self):
        self.assertEqual(model.validate_step({"x": 0, "y": 0}, (-1920, 0))["x"], 0)
        with self.assertRaises(ValueError):
            model.validate_step({"x": -1920, "y": 0}, (-1920, 0))

    def test_parse_profile_skips_corner_check_by_default(self):
        steps, _, _ = model.parse_profile({"steps": [{"x": 0, "y": 0}]})
        self.assertEqual(steps[0]["x"], 0)
        with self.assertRaises(ValueError):
            model.parse_profile({"steps": [{"x": 0, "y": 0}]}, origin=(0, 0))

    def test_parse_profile_defaults(self):
        steps, st, dflt = model.parse_profile({"steps": [{"x": 10, "y": 20}]})
        self.assertEqual(len(steps), 1)
        self.assertEqual(st, constants.DEFAULT_SETTINGS)
        self.assertEqual(dflt, constants.DEFAULT_DEFAULTS)

    def test_parse_profile_rejects_bad_settings(self):
        bad = [
            {"settings": []},
            {"settings": {"mode": "forever"}},
            {"settings": {"rounds": 0}},
            {"settings": {"minutes": 0}},
            {"settings": {"jitter_px": 51}},
            {"settings": {"jitter_ms": 5001}},
            {"defaults": {"delay_ms": 5}},
            {"steps": {"x": 1}},
        ]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(ValueError):
                model.parse_profile(d)


class TryMoveStepTests(unittest.TestCase):
    RECT = (-1920, 0, 3840, 1080)
    ORIGIN = (-1920, 0)

    def setUp(self):
        self.steps = [step(100, 100, "hold", 250, 300), step(200, 200, "right")]
        self.before = [dict(s) for s in self.steps]

    def test_ok_moves_and_keeps_other_fields(self):
        ok, reason = model.try_move_step(self.steps, 0, 640, 480, self.ORIGIN, self.RECT)
        self.assertTrue(ok, reason)
        self.assertEqual(self.steps[0], step(640, 480, "hold", 250, 300))
        self.assertEqual(self.steps[1], self.before[1])

    def test_negative_coords_on_left_monitor(self):
        ok, _ = model.try_move_step(self.steps, 1, -1000, 500, self.ORIGIN, self.RECT)
        self.assertTrue(ok)
        self.assertEqual((self.steps[1]["x"], self.steps[1]["y"]), (-1000, 500))

    def test_primary_corner_is_fine_with_negative_origin(self):
        ok, _ = model.try_move_step(self.steps, 0, 0, 0, self.ORIGIN, self.RECT)
        self.assertTrue(ok)

    def test_rejects_kill_zone(self):
        ok, reason = model.try_move_step(self.steps, 0, -1919, 2, self.ORIGIN, self.RECT)
        self.assertFalse(ok)
        self.assertIn("kill switch", reason)
        self.assertEqual(self.steps, self.before)

    def test_rejects_out_of_screen(self):
        ok, reason = model.try_move_step(self.steps, 0, 1920, 100, self.ORIGIN, self.RECT)
        self.assertFalse(ok)
        self.assertIn("นอกจอ", reason)
        self.assertEqual(self.steps, self.before)

    def test_unknown_rect_skips_screen_check(self):
        ok, _ = model.try_move_step(self.steps, 0, 9999, 9999, (0, 0), None)
        self.assertTrue(ok)

    def test_bad_index(self):
        for i in (-1, 2):
            ok, _ = model.try_move_step(self.steps, i, 300, 300, self.ORIGIN, self.RECT)
            self.assertFalse(ok)
        self.assertEqual(self.steps, self.before)


class RepeatModelTests(unittest.TestCase):
    def test_validate_rejects_bad_repeat_and_gap(self):
        base = {"x": 10, "y": 10}
        for extra in [
            {"repeat": 0},
            {"repeat": 1001},
            {"repeat": 1.5},
            {"repeat": True},
            {"repeat": "3"},
            {"gap_ms": 5},
            {"gap_ms": 60001},
            {"gap_ms": True},
            {"gap_ms": 10.0},
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                model.validate_step(dict(base, **extra))

    def test_validate_bounds_ok(self):
        for r, g in [(1, 10), (1000, 60000)]:
            s = model.validate_step({"x": 10, "y": 10, "repeat": r, "gap_ms": g})
            self.assertEqual((s["repeat"], s["gap_ms"]), (r, g))

    def test_old_profile_without_repeat_loads(self):
        old = {
            "version": 1,
            "steps": [{"x": 812, "y": 455, "type": "left", "delay_ms": 500, "hold_ms": 500}],
            "settings": {"mode": "count", "rounds": 10, "minutes": 5, "jitter_px": 3, "jitter_ms": 50},
            "defaults": {"type": "left", "delay_ms": 500},
        }
        steps, _, dflt = model.parse_profile(old)
        self.assertEqual((steps[0]["repeat"], steps[0]["gap_ms"]), (1, 100))
        self.assertEqual(dflt["repeat"], 1)

    def test_defaults_repeat_validated(self):
        for bad in (0, 1001, 2.0, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                model.parse_profile({"defaults": {"repeat": bad}})
        self.assertEqual(model.parse_profile({"defaults": {"repeat": 7}})[2]["repeat"], 7)

    def test_step_row(self):
        self.assertEqual(
            model.step_row(1, step(10, 20, "left", 500, 300)),
            (1, 10, 20, constants.CLICK_LABEL["left"], 1, "-", "-", "500 ms"),
        )
        self.assertEqual(
            model.step_row(2, step(10, 20, "hold", 90000, 1500, repeat=3, gap_ms=250)),
            (2, 10, 20, constants.CLICK_LABEL["hold"], 3, "250 ms", "1.5 วิ", "1 นาที 30 วิ"),
        )


class TimeUnitTests(unittest.TestCase):
    def test_to_ms(self):
        cases = [
            ("500", "ms", 500),
            ("1.5", "วินาที", 1500),
            ("0.5", "นาที", 30000),
            ("0.29", "วินาที", 290),  # int() จะได้ 289
            (" 2 ", "นาที", 120000),
            ("0", "ms", 0),
            ("1e3", "ms", 1000),
            (3, "วินาที", 3000),
            ("0.0005", "วินาที", 0),
            ("10.4", "ms", 10),
            ("10.6", "ms", 11),
        ]
        for value, unit, expect in cases:
            with self.subTest(value=value, unit=unit):
                self.assertEqual(model.to_ms(value, unit), expect)
                self.assertIsInstance(model.to_ms(value, unit), int)

    def test_to_ms_rejects(self):
        for value, unit in [
            ("abc", "ms"),
            ("", "ms"),
            ("-1", "ms"),
            ("-0.5", "วินาที"),
            ("nan", "ms"),
            ("inf", "วินาที"),
            ("1,5", "วินาที"),
            ("5", "ชม."),
        ]:
            with self.subTest(value=value, unit=unit), self.assertRaises(ValueError):
                model.to_ms(value, unit)

    def test_pick_unit(self):
        self.assertEqual(model.pick_unit(120000), (2, "นาที"))
        self.assertEqual(model.pick_unit(90000), (90, "วินาที"))
        self.assertEqual(model.pick_unit(3000), (3, "วินาที"))
        self.assertEqual(model.pick_unit(1500), (1500, "ms"))
        self.assertEqual(model.pick_unit(500), (500, "ms"))
        self.assertEqual(model.pick_unit(0), (0, "ms"))

    def test_pick_unit_round_trips(self):
        for ms in (0, 10, 500, 999, 1000, 1500, 60000, 90000, 86_400_000):
            self.assertEqual(model.to_ms(*model.pick_unit(ms)), ms)

    def test_format_duration(self):
        cases = [
            (0, "0 ms"),
            (500, "500 ms"),
            (999, "999 ms"),
            (1000, "1 วิ"),
            (1500, "1.5 วิ"),
            (1234, "1.234 วิ"),
            (59999, "59.999 วิ"),
            (60000, "1 นาที"),
            (120000, "2 นาที"),
            (90000, "1 นาที 30 วิ"),
            (90500, "1 นาที 30.5 วิ"),
            (60010, "1 นาที 0.01 วิ"),
        ]
        for ms, text in cases:
            with self.subTest(ms=ms):
                self.assertEqual(model.format_duration(ms), text)

    def test_duration_ceiling_24h(self):
        top = constants.MAX_DURATION_MS
        self.assertEqual(top, 86_400_000)
        ok = model.validate_step({"x": 10, "y": 10, "delay_ms": top, "hold_ms": top})
        self.assertEqual((ok["delay_ms"], ok["hold_ms"]), (top, top))
        for key in ("delay_ms", "hold_ms"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "24 ชม."):
                model.validate_step({"x": 10, "y": 10, key: top + 1})
        with self.assertRaises(ValueError):
            model.parse_profile({"defaults": {"delay_ms": top + 1}})

    def form(self, **kw):
        f = {
            "x": "100",
            "y": "200",
            "type": constants.CLICK_LABEL["left"],
            "repeat": "1",
            "delay_ms": "500",
            "delay_ms_unit": "ms",
            "hold_ms": "0",
            "hold_ms_unit": "ms",
            "gap_ms": "100",
            "gap_ms_unit": "ms",
        }
        f.update(kw)
        return f

    def test_step_from_form_converts_units(self):
        s = model.step_from_form(
            self.form(
                delay_ms="1.5",
                delay_ms_unit="วินาที",
                gap_ms="0.29",
                gap_ms_unit="วินาที",
                hold_ms="0.5",
                hold_ms_unit="นาที",
                repeat="3",
            )
        )
        self.assertEqual((s["delay_ms"], s["gap_ms"], s["hold_ms"], s["repeat"]), (1500, 290, 30000, 3))

    def test_step_from_form_errors_name_the_field(self):
        for kw, field in [
            ({"x": "1.5"}, "X"),
            ({"repeat": "abc"}, "จำนวนครั้ง"),
            ({"delay_ms": "abc"}, "รอหลังครั้งสุดท้าย"),
            ({"gap_ms": "-1"}, "เว้นระหว่างครั้ง"),
        ]:
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, field):
                model.step_from_form(self.form(**kw))

    def test_rules_still_apply_after_conversion(self):
        s = model.step_from_form(self.form(delay_ms="0.005", delay_ms_unit="วินาที"))  # = 5 ms
        with self.assertRaises(ValueError):
            model.validate_step(s)
        s = model.step_from_form(self.form(delay_ms="1441", delay_ms_unit="นาที"))  # > 24 ชม.
        with self.assertRaises(ValueError):
            model.validate_step(s)


class HoverSettingTests(unittest.TestCase):
    def test_old_profile_gets_default_hover(self):
        _, st, _ = model.parse_profile({"settings": {"mode": "loop", "jitter_px": 0}})
        self.assertEqual(st["hover_ms"], 50)

    def test_validate_range(self):
        for bad in (-1, 1001, 1.5, True, "50", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                model.parse_profile({"settings": {"hover_ms": bad}})
        for ok in (0, 1000):
            self.assertEqual(model.parse_profile({"settings": {"hover_ms": ok}})[1]["hover_ms"], ok)


class StartSettingTests(unittest.TestCase):
    """นับถอยหลัง / หยุดเมื่อสลับหน้าต่าง ใน settings ของโปรไฟล์"""

    def test_old_profile_gets_defaults(self):
        _, st, _ = model.parse_profile({"settings": {"mode": "loop", "hover_ms": 50}})
        self.assertEqual((st["countdown_s"], st["pause_on_switch"]), (3, True))
        _, st, _ = model.parse_profile({})
        self.assertEqual((st["countdown_s"], st["pause_on_switch"]), (3, True))

    def test_countdown_range(self):
        for bad in (-1, 31, 1.5, True, "3", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                model.parse_profile({"settings": {"countdown_s": bad}})
        for ok in (0, 30):
            self.assertEqual(model.parse_profile({"settings": {"countdown_s": ok}})[1]["countdown_s"], ok)

    def test_pause_on_switch_must_be_bool(self):
        for bad in ("yes", 1, 0, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                model.parse_profile({"settings": {"pause_on_switch": bad}})
        self.assertIs(
            model.parse_profile({"settings": {"pause_on_switch": False}})[1]["pause_on_switch"], False
        )


if __name__ == "__main__":
    unittest.main()
