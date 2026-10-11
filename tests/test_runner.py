"""เทสต์ Runner ด้วย FakeMouse (stub แค่ pynput.mouse.Button ไม่ต้องมีจอ)"""

import ctypes
import os
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
from support import FakeKeys, FakeMouse, FakeWindows, cfg, step


class RunnerHarness:
    def __init__(self, steps, config, mouse=None, origin=(0, 0), nudge=None, win=None, keys=None):
        self.mouse = mouse or FakeMouse()
        self.keys = keys or FakeKeys()  # inject เสมอ ไม่งั้นรันเทสต์บน Windows จะไปกดปุ่มจริง
        self.done = threading.Event()
        self.reason = None
        self.statuses = []  # (รอบ, จุด, ครั้งที่, repeat)
        self.notices = []  # ข้อความนับถอยหลัง / หยุดชั่วคราว
        # ต้อง inject nudge และ foreground เสมอ ไม่งั้นรันเทสต์บน Windows จะไปขยับเมาส์/อ่านหน้าต่างจริง
        # win=None: ไม่มีหน้าต่างข้างหน้า (เหมือนไม่ใช่ Windows) ฟีเจอร์หยุดเมื่อสลับหน้าต่างจะปิด
        win = win or FakeWindows(foreground=None)
        self.runner = runner_mod.Runner(
            steps,
            config,
            self.mouse,
            on_status=lambda *a: self.statuses.append(a),
            on_done=self._on_done,
            origin=origin,
            nudge=nudge or self.mouse.nudge,
            on_notice=self.notices.append,
            foreground=win.foreground_window,
            is_window=win.is_window,
            window_pid=win.window_pid,
            key_sender=self.keys.send,
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


class FormatStatusTests(unittest.TestCase):
    """ย้ายมาจาก test_model: format_status อยู่ใน runner (import pynput) เทสต์ model จะได้ไม่ต้อง stub"""

    def test_format_status(self):
        self.assertEqual(runner_mod.format_status(4, 2, 1, 1), "รอบ 4 · จุด #2")
        self.assertEqual(runner_mod.format_status(4, 2, 2, 3), "รอบ 4 · จุด #2 (2/3)")


# ------------------------------------------------- countdown / pause on switch
class CountdownTests(unittest.TestCase):
    def test_countdown_text(self):
        self.assertEqual(runner_mod.countdown_text(3), "เริ่มใน 3…")

    def test_countdown_then_clicks(self):
        t0 = time.monotonic()
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1, countdown_s=1)).start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        click_t = [ts for kind, _, ts in h.mouse.events if kind == "click"]
        self.assertEqual(len(click_t), 1)
        self.assertGreaterEqual(click_t[0] - t0, 0.95)  # คลิกหลังนับถอยหลังจบ
        self.assertEqual(h.notices, ["เริ่มใน 1…"])

    def test_notices_count_down(self):
        h = RunnerHarness([step(100, 100)], cfg(countdown_s=3)).start()
        self.assertTrue(h.wait_for(lambda: len(h.notices) >= 2, timeout=3))
        h.runner.stop()
        h.finish()
        self.assertEqual(h.notices[:2], ["เริ่มใน 3…", "เริ่มใน 2…"])

    def test_stop_during_countdown_no_clicks(self):
        h = RunnerHarness([step(100, 100)], cfg(countdown_s=30)).start()
        self.assertTrue(h.wait_for(lambda: h.notices))
        t0 = time.monotonic()
        h.runner.stop("หยุดโดยผู้ใช้")
        h.runner.join(0.3)
        self.assertFalse(h.runner.is_alive())
        self.assertLess(time.monotonic() - t0, 0.3)
        self.assertEqual(h.finish(), "หยุดโดยผู้ใช้")
        self.assertEqual(h.mouse.log, [])

    def test_kill_switch_during_countdown(self):
        h = RunnerHarness([step(100, 100)], cfg(countdown_s=30)).start()
        self.assertTrue(h.wait_for(lambda: h.notices))
        h.mouse.position = (0, 0)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), constants.KILL_REASON)
        self.assertEqual(h.mouse.log, [])

    def test_time_mode_deadline_starts_after_countdown(self):
        t0 = time.monotonic()
        h = RunnerHarness([step(100, 100)], cfg(mode="time", minutes=0.5 / 60, countdown_s=1)).start()
        self.assertEqual(h.finish(), "ครบเวลาที่ตั้งไว้")
        self.assertGreaterEqual(time.monotonic() - t0, 1.45)  # 1 วินับถอยหลัง + 0.5 วิทำงาน
        self.assertTrue(h.mouse.clicks())


def switching(win, mouse, at_x, back_after):
    """nudge ปลอม: พอเมาส์ไปถึง x == at_x (ก่อนคลิก) สลับหน้าต่างเป้าหมายออก
    แล้วสลับกลับหลัง back_after วิ (None = ไม่กลับ) คืน (nudge, [เวลาที่สลับกลับ])"""
    back_at = []

    def nudge():
        mouse.nudge()
        if mouse.position[0] == at_x and win.foreground == FakeWindows.GAME and not back_at:
            win.foreground = FakeWindows.OTHER
            back_at.append(None)
            if back_after is not None:

                def back():
                    time.sleep(back_after)
                    back_at[0] = time.monotonic()
                    win.foreground = FakeWindows.GAME

                threading.Thread(target=back, daemon=True).start()

    return nudge, back_at


class PauseOnSwitchTests(unittest.TestCase):
    def cfg(self, **kw):
        return cfg(pause_on_switch=True, **kw)

    def test_target_is_foreground_when_countdown_ends(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100)], self.cfg(mode="count", rounds=1), win=win).start()
        h.finish()
        self.assertEqual(h.runner.target, FakeWindows.GAME)

    def test_own_window_stops_immediately(self):
        win = FakeWindows(pids={FakeWindows.GAME: os.getpid()})
        h = RunnerHarness([step(100, 100)], self.cfg(), win=win).start()
        self.assertEqual(h.finish(), constants.OWN_WINDOW_REASON)
        self.assertEqual(h.mouse.log, [])

    def test_feature_off_when_no_foreground_api(self):
        h = RunnerHarness([step(100, 100)], self.cfg(mode="count", rounds=2)).start()  # foreground=None
        self.assertEqual(h.finish(), "ครบ 2 รอบ")
        self.assertIsNone(h.runner.target)
        self.assertEqual(len(h.mouse.clicks()), 2)

    def test_feature_off_when_unchecked(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100)], cfg(mode="count", rounds=1, pause_on_switch=False), win=win)
        win.foreground = FakeWindows.OTHER
        h.start()
        self.assertEqual(h.finish(), "ครบ 1 รอบ")
        self.assertIsNone(h.runner.target)

    def test_switch_away_pauses_without_clicking(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100, delay_ms=20)], self.cfg(), win=win).start()
        self.assertTrue(h.wait_for(lambda: len(h.mouse.clicks()) >= 2))
        win.foreground = FakeWindows.OTHER
        self.assertTrue(h.wait_for(lambda: constants.PAUSED_TEXT in h.notices))
        time.sleep(0.15)  # เผื่อคลิกที่กำลังทำอยู่ให้จบ
        n = len(h.mouse.clicks())
        time.sleep(0.4)
        self.assertEqual(len(h.mouse.clicks()), n)  # หยุดชั่วคราว = ไม่คลิกเลย
        self.assertTrue(h.runner.is_alive())
        h.runner.stop()
        h.finish()

    def test_resume_continues_from_same_step(self):
        win, mouse = FakeWindows(), FakeMouse()
        nudge, back_at = switching(win, mouse, at_x=200, back_after=0.3)
        steps = [step(100, 100, delay_ms=10), step(200, 200, delay_ms=10), step(300, 300, delay_ms=10)]
        h = RunnerHarness(steps, self.cfg(mode="count", rounds=1), mouse=mouse, nudge=nudge, win=win)
        h.start()
        self.assertEqual(h.finish(timeout=5), "ครบ 1 รอบ")
        xs = [e[3][0] for e in mouse.clicks()]
        self.assertEqual(xs, [100, 200, 300])  # จุด 2 ไม่ถูกข้าม และไม่คลิกซ้ำจุด 1
        click2 = [ts for kind, pos, ts in mouse.events if kind == "click" and pos[0] == 200][0]
        self.assertGreaterEqual(click2 - back_at[0], 0.45)  # กลับมาแล้วรอ 500ms ก่อนทำต่อ
        self.assertIn(constants.PAUSED_TEXT, h.notices)
        self.assertEqual(h.statuses.count((1, 2, 1, 1)), 2)  # ส่ง status จุดเดิมซ้ำตอนทำต่อ

    def test_flapping_during_resume_restarts_delay(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100, delay_ms=20)], self.cfg(), win=win).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        win.foreground = FakeWindows.OTHER
        self.assertTrue(h.wait_for(lambda: constants.PAUSED_TEXT in h.notices))
        time.sleep(0.1)
        n = len(h.mouse.clicks())
        win.foreground = FakeWindows.GAME
        time.sleep(0.3)
        win.foreground = FakeWindows.OTHER  # หลุดอีกรอบก่อนครบ 500ms
        time.sleep(0.4)
        self.assertEqual(len(h.mouse.clicks()), n)
        h.runner.stop()
        h.finish()

    def test_target_closed_stops(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100, delay_ms=20)], self.cfg(), win=win).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        win.closed.add(FakeWindows.GAME)
        self.assertTrue(h.done.wait(0.5))
        self.assertEqual(h.finish(), constants.TARGET_CLOSED_REASON)

    def test_target_closed_while_paused_stops(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100, delay_ms=20)], self.cfg(), win=win).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
        win.foreground = FakeWindows.OTHER
        self.assertTrue(h.wait_for(lambda: constants.PAUSED_TEXT in h.notices))
        win.closed.add(FakeWindows.GAME)
        self.assertTrue(h.done.wait(0.3))
        self.assertEqual(h.finish(), constants.TARGET_CLOSED_REASON)

    def test_stop_and_kill_switch_work_while_paused(self):
        for how in ("stop", "kill"):
            with self.subTest(how=how):
                win = FakeWindows()
                h = RunnerHarness([step(100, 100, delay_ms=20)], self.cfg(), win=win).start()
                self.assertTrue(h.wait_for(lambda: h.mouse.clicks()))
                win.foreground = FakeWindows.OTHER
                self.assertTrue(h.wait_for(lambda: constants.PAUSED_TEXT in h.notices))
                if how == "stop":
                    h.runner.stop("หยุดโดยผู้ใช้")
                else:
                    h.mouse.position = (0, 0)
                self.assertTrue(h.done.wait(0.3))
                expect = "หยุดโดยผู้ใช้" if how == "stop" else constants.KILL_REASON
                self.assertEqual(h.finish(), expect)

    def test_deadline_keeps_running_while_paused(self):
        win, mouse = FakeWindows(), FakeMouse()
        nudge, _ = switching(win, mouse, at_x=100, back_after=None)  # หลุดตั้งแต่คลิกแรก ไม่กลับมาอีก
        t0 = time.monotonic()
        h = RunnerHarness(
            [step(100, 100)], self.cfg(mode="time", minutes=0.5 / 60), mouse=mouse, nudge=nudge, win=win
        ).start()
        self.assertEqual(h.finish(), "ครบเวลาที่ตั้งไว้")
        self.assertLess(time.monotonic() - t0, 0.9)
        self.assertEqual(mouse.clicks(), [])

    def test_hold_released_when_switching_away_then_redone(self):
        win = FakeWindows()
        h = RunnerHarness([step(100, 100, "hold", hold_ms=30000)], self.cfg(), win=win).start()
        self.assertTrue(h.wait_for(lambda: h.mouse.pressed))
        win.foreground = FakeWindows.OTHER
        self.assertTrue(h.wait_for(lambda: not h.mouse.pressed))  # ปล่อยปุ่มทันทีที่หน้าต่างหลุด
        time.sleep(0.3)
        self.assertEqual([e[0] for e in h.mouse.log], ["press", "release"])  # ไม่กดค้างระหว่างหยุด
        win.foreground = FakeWindows.GAME
        self.assertTrue(h.wait_for(lambda: h.mouse.pressed, timeout=2))  # กลับมาแล้วกดใหม่ทั้งครั้ง
        h.runner.stop()
        h.finish()
        self.assertEqual([e[0] for e in h.mouse.log], ["press", "release", "press", "release"])
        self.assertEqual(h.mouse.pressed, set())


if __name__ == "__main__":
    unittest.main()
