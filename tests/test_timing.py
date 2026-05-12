import unittest
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from src.coder import calculate_click_window
from src.scheduler import Scheduler, format_remaining_for_log


class TimingTests(unittest.TestCase):
    def test_click_window_runs_from_0958_until_1020(self):
        target_time = datetime(2026, 5, 9, 10, 0, 0)

        start_time, deadline = calculate_click_window(
            target_time=target_time,
            click_buffer=120,
            end_after=1200,
        )

        self.assertEqual(start_time, datetime(2026, 5, 9, 9, 58, 0))
        self.assertEqual(deadline, datetime(2026, 5, 9, 10, 20, 0))
        self.assertEqual(deadline - start_time, timedelta(minutes=22))

    def test_config_sets_0958_detection_window(self):
        config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))

        self.assertEqual(config["preheat"]["click_time"], "09:58:00")
        self.assertEqual(config["preheat"]["click_buffer"], 120)
        self.assertEqual(config["purchase"]["end_after"], 1200)

    def test_scheduler_reads_click_time_from_config(self):
        scheduler = Scheduler(
            {"purchase": {}, "preheat": {"click_time": "09:58:00"}},
            lambda *_args, **_kwargs: None,
        )

        self.assertEqual(scheduler._get_preheat_time("click_time", "09:59:55"), (9, 58, 0))

    def test_wait_log_uses_whole_minutes(self):
        self.assertEqual(format_remaining_for_log(1023), "等待 18 分钟...")
        self.assertEqual(format_remaining_for_log(243), "等待 243 秒...")

    def test_scheduler_parses_seconds(self):
        scheduler = Scheduler({"purchase": {}}, lambda *_args, **_kwargs: None)

        self.assertEqual(scheduler._parse_time("09:59:55"), (9, 59, 55))


if __name__ == "__main__":
    unittest.main()
