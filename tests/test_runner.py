"""เทสต์ Runner ด้วย FakeMouse (stub แค่ pynput.mouse.Button ไม่ต้องมีจอ)"""

import ctypes
import sys
import threading
import time
import unittest

import support  # ตั้ง sys.path ให้ import autoclicker ได้

support.install_stubs()  # ต้องมาก่อน import module ที่ใช้ tkinter/pynput

from autoclicker import (
    constants,
    screen,
    win32,
)
from autoclicker import runner as runner_mod
from support import FakeMouse, cfg, step


class RunnerHarness:
    def __init__(self, steps, config, mouse=None, origin=(0, 0), nudge=None):
        self.mouse = mouse or FakeMouse()
        self.done = threading.Event()
        self.reason = None
        self.statuses = []  # (รอบ, จุด, ครั้งที่, repeat)
        # ต้อง inject nudge เสมอ ไม่งั้นรันเทสต์บน Windows จะไปขยับเมาส์จริงของเครื่อง
        self.runner = runner_mod.Runner(
            steps,
            config,
            self.mouse,
            on_status=lambda *a: self.statuses.append(a),
            on_done=self._on_done,
            origin=origin,
            nudge=nudge or self.mouse.nudge,
        )

    def _on_done(self, reason):
        self.reason = reason
        self.done.set()

    def start(self):
        self.runner.start()
        return self

    def wait_for(self, cond, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.005)
        return False

    def finish(self, timeout=5.0):
        self.runner.join(timeout)
        assert not self.runner.is_alive(), "runner ไม่ยอมจบ"
        return self.reason


class RunnerTests(unittest.TestCase):
    def test_count_three_rounds_clicks_in_order(self):
        steps = [step(100, 100, "left"), step(200, 150, "right"), step(300, 250, "double")]
        h = RunnerHarness(steps, cfg(mode="count", rounds=3)).start()
        self.assertEqual(h.finish(), "ครบ 3 รอบ")
        expected = [
            ("click", "left", 1, (100, 100)),
            ("click", "right", 1, (200, 150)),
            ("click", "left", 2, (300, 250)),
        ] * 3
        self.assertEqual(h.mouse.clicks(), expected)

    def test_long_delay_stops_fast(self):
        h = RunnerHarness([step(100, 100, delay_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")

    def test_hold_released_when_stopped(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.pressed))
        h.runner.stop("หยุดโดยผู้ใช้")
        h.finish(timeout=0.3)
        actions = [e[0] for e in h.mouse.log]
        self.assertEqual(actions, ["press", "release"])
        self.assertEqual(h.mouse.pressed, set())

    def test_time_mode_stops_after_deadline(self):
        t0 = time.monotonic()
        h = RunnerHarness([step(100, 100)], cfg(mode="time", minutes=0.5 / 60)).start()
        reason = h.finish()
        elapsed = time.monotonic() - t0
        self.assertEqual(reason, "ครบเวลาที่ตั้งไว้")
        self.assertGreaterEqual(elapsed, 0.45)
        self.assertLess(elapsed, 0.8)

    def test_kill_switch_stops(self):
        h = RunnerHarness([step(100, 100, delay_ms=5000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), constants.KILL_REASON)

    def test_jitter_never_lands_in_kill_zone(self):
        h = RunnerHarness([step(4, 4)], cfg(mode="count", rounds=50, jitter_px=10)).start()
        self.assertEqual(h.finish(timeout=10), "ครบ 50 รอบ")
        clicks = h.mouse.clicks()
        self.assertEqual(len(clicks), 50)
        for _, _, _, (x, y) in clicks:
            self.assertFalse(screen.in_corner(x, y), (x, y))

    def test_jitter_respects_negative_origin(self):
        origin = (-1920, 0)
        h = RunnerHarness([step(-1916, 4)], cfg(mode="count", rounds=50, jitter_px=10), origin=origin).start()
        self.assertEqual(h.finish(timeout=10), "ครบ 50 รอบ")
        for _, _, _, (x, y) in h.mouse.clicks():
            self.assertFalse(screen.in_corner(x, y, origin), (x, y))

    def test_negative_origin_zero_is_not_kill_zone(self):
        # จอเสริมอยู่ทางซ้าย: (0,0) เป็นแค่มุมของจอหลัก ไม่ใช่ขอบจริง ต้องไม่หยุด
        h = RunnerHarness([step(0, 0)], cfg(mode="count", rounds=2), origin=(-1920, 0)).start()
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        self.assertEqual(len(h.mouse.clicks()), 2)

    def test_negative_origin_real_corner_stops(self):
        h = RunnerHarness([step(100, 100, delay_ms=5000)], cfg(), origin=(-1920, 0)).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        h.mouse.position = (-1920, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), constants.KILL_REASON)

    def test_exception_reported_as_error(self):
        class BrokenMouse(FakeMouse):
            def click(self, button, count=1):
                raise RuntimeError("boom")

        h = RunnerHarness([step(100, 100)], cfg(), mouse=BrokenMouse()).start()
        self.assertEqual(h.finish(), "error: boom")

    def test_empty_steps_reports_error_instead_of_spinning(self):
        h = RunnerHarness([], cfg()).start()
        self.assertTrue(h.finish(timeout=1).startswith("error:"))


class RepeatRunnerTests(unittest.TestCase):
    def test_three_clicks_per_step_in_order(self):
        steps = [step(100, 100, repeat=3, gap_ms=10), step(200, 200, "right", repeat=3, gap_ms=10)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=1)).start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(
            h.mouse.clicks(), [("click", "left", 1, (100, 100))] * 3 + [("click", "right", 1, (200, 200))] * 3
        )
        self.assertEqual(
            h.statuses, [(1, 1, 1, 3), (1, 1, 2, 3), (1, 1, 3, 3), (1, 2, 1, 3), (1, 2, 2, 3), (1, 2, 3, 3)]
        )

    def test_two_steps_repeat_2_and_3_two_rounds(self):
        steps = [step(100, 100, repeat=2, gap_ms=10), step(200, 200, repeat=3, gap_ms=10)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=2)).start()
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        xs = [e[3][0] for e in h.mouse.clicks()]
        self.assertEqual(xs, [100, 100, 200, 200, 200] * 2)  # รวม 10 คลิก

    def test_stop_during_long_gap(self):
        h = RunnerHarness([step(100, 100, repeat=5, gap_ms=30000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")
        self.assertEqual(len(h.mouse.clicks()), 1)  # ไม่รอให้ครบ repeat

    def test_hold_repeat_stopped_midway_releases(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=30000, repeat=2, gap_ms=10)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.pressed))
        h.runner.stop("หยุดโดยผู้ใช้")
        h.finish(timeout=0.3)
        self.assertEqual([e[0] for e in h.mouse.log], ["press", "release"])  # ไม่ไปกดครั้งที่ 2
        self.assertEqual(h.mouse.pressed, set())

    def test_hold_repeat_releases_every_time(self):
        h = RunnerHarness(
            [step(100, 100, "hold", hold_ms=10, repeat=3, gap_ms=10)], cfg(mode="count", rounds=1)
        ).start()
        h.finish()
        self.assertEqual([e[0] for e in h.mouse.log], ["press", "release"] * 3)
        self.assertEqual(h.mouse.pressed, set())

    def test_double_repeat(self):
        h = RunnerHarness(
            [step(100, 100, "double", repeat=2, gap_ms=10)], cfg(mode="count", rounds=1)
        ).start()
        h.finish()
        self.assertEqual(h.mouse.clicks(), [("click", "left", 2, (100, 100))] * 2)

    def test_jitter_px_rerolled_every_click(self):
        h = RunnerHarness(
            [step(500, 500, repeat=40, gap_ms=10)], cfg(mode="count", rounds=1, jitter_px=10)
        ).start()
        h.finish(timeout=10)
        pos = [e[3] for e in h.mouse.clicks()]
        self.assertEqual(len(pos), 40)
        self.assertGreater(len(set(pos)), 1)  # ถ้าสุ่มครั้งเดียวต่อจุด ทุกคลิกจะตรงกันหมด
        for x, y in pos:
            self.assertTrue(490 <= x <= 510 and 490 <= y <= 510, (x, y))

    def test_gap_respects_kill_switch(self):
        h = RunnerHarness([step(100, 100, repeat=5, gap_ms=5000)], cfg()).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), constants.KILL_REASON)

    def test_time_deadline_inside_repeat(self):
        t0 = time.monotonic()
        h = RunnerHarness(
            [step(100, 100, repeat=1000, gap_ms=50)], cfg(mode="time", minutes=0.3 / 60)
        ).start()
        self.assertEqual(h.finish(), "ครบเวลาที่ตั้งไว้")
        self.assertLess(time.monotonic() - t0, 0.6)


def kinds(mouse, keep=("move", "nudge", "click", "press", "release")):
    return [e[0] for e in mouse.events if e[0] in keep]


class HoverNudgeTests(unittest.TestCase):
    def test_nudge_after_move_before_click_every_time(self):
        steps = [step(100, 100, repeat=2, gap_ms=10), step(200, 200, "hold", hold_ms=10)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=1)).start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertEqual(
            kinds(h.mouse),
            [
                "move",
                "nudge",
                "click",
                "move",
                "nudge",
                "click",  # repeat ครั้งที่ 2 ก็ต้อง nudge
                "move",
                "nudge",
                "press",
                "release",
            ],
        )
        for kind, pos, _ in h.mouse.events:
            if kind == "nudge":
                self.assertIn(pos, [(100, 100), (200, 200)])  # nudge ตอนเมาส์อยู่ที่จุดแล้ว

    def test_hover_waited_before_click(self):
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1, hover_ms=200)).start()
        h.finish()
        t = {kind: ts for kind, _, ts in h.mouse.events}
        self.assertGreaterEqual(t["click"] - t["nudge"], 0.19)

    def test_hover_applies_to_each_repeat(self):
        h = RunnerHarness(
            [step(100, 100, repeat=3, gap_ms=10)], cfg(mode="count", rounds=1, hover_ms=100)
        ).start()
        h.finish()
        nudges = [ts for kind, _, ts in h.mouse.events if kind == "nudge"]
        clicks = [ts for kind, _, ts in h.mouse.events if kind == "click"]
        self.assertEqual(len(clicks), 3)
        for n, c in zip(nudges, clicks):
            self.assertGreaterEqual(c - n, 0.09)

    def test_stop_during_long_hover(self):
        h = RunnerHarness([step(100, 100)], cfg(hover_ms=30000)).start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(h.mouse)))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")
        self.assertEqual(h.mouse.clicks(), [])  # ยังไม่ทันคลิก

    def test_kill_switch_during_hover(self):
        h = RunnerHarness([step(100, 100)], cfg(hover_ms=30000)).start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(h.mouse)))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), constants.KILL_REASON)
        self.assertEqual(h.mouse.clicks(), [])

    def test_hold_not_pressed_if_stopped_during_hover(self):
        h = RunnerHarness([step(100, 100, "hold", hold_ms=10)], cfg(hover_ms=30000)).start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(h.mouse)))
        h.runner.stop()
        h.finish(timeout=0.3)
        self.assertEqual(h.mouse.log, [])
        self.assertEqual(h.mouse.pressed, set())

    def test_nudge_error_does_not_kill_runner(self):
        def broken():
            raise OSError("SendInput failed")

        steps = [step(100, 100), step(200, 200)]
        h = RunnerHarness(steps, cfg(mode="count", rounds=2), nudge=broken).start()
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        self.assertEqual(len(h.mouse.clicks()), 4)

    def test_position_restored_if_nudge_drifts(self):
        mouse = FakeMouse()

        def drifting():  # จำลอง Enhance pointer precision: +1 ไป 2px แต่ -1 กลับแค่ 1px
            x, y = mouse.position
            mouse.position = (x + 1, y)

        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1), mouse=mouse, nudge=drifting).start()
        h.finish()
        self.assertEqual(h.mouse.clicks(), [("click", "left", 1, (100, 100))])

    def test_late_drift_during_hover_is_corrected(self):
        # SendInput เข้าคิวแบบ async: ตำแหน่งอาจเพี้ยนทีหลัง ระหว่างที่รอ hover อยู่
        mouse = FakeMouse()
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1, hover_ms=200), mouse=mouse)
        h.start()
        self.assertTrue(h.wait_for(lambda: "nudge" in kinds(mouse)))
        mouse.position = (101, 100)
        h.finish()
        self.assertEqual(mouse.clicks(), [("click", "left", 1, (100, 100))])

    def test_default_nudge_is_sendinput(self):
        r = runner_mod.Runner([step(1, 1)], cfg(), FakeMouse(), lambda *a: None, lambda r: None)
        self.assertIs(r.nudge, runner_mod.nudge_mouse)

    def test_nudge_mouse_skips_on_non_windows(self):
        orig = sys.platform
        sys.platform = "linux"
        try:
            self.assertIsNone(runner_mod.nudge_mouse())  # ไม่ raise และไม่แตะ ctypes.windll
        finally:
            sys.platform = orig

    def test_input_struct_size_matches_win32(self):
        # SendInput ต้องได้ cbSize ตรงกับ sizeof(INPUT) ของ Windows ไม่งั้นจะ fail เงียบๆ
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(win32._INPUT), expected)


if __name__ == "__main__":
    unittest.main()
