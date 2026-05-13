import unittest
from pathlib import Path

import yaml

from src.coder import (
    get_refresh_interval,
    get_subscription_period_label,
    is_ready_purchase_text,
    is_retry_limited_text,
)


class PurchaseStrategyTests(unittest.TestCase):
    def test_special_offer_is_clickable_but_refresh_retry_is_not(self):
        self.assertTrue(is_ready_purchase_text("特惠订购"))
        self.assertFalse(is_ready_purchase_text("抢购人数过多，请刷新再试"))
        self.assertTrue(is_retry_limited_text("抢购人数过多，请刷新再试"))

    def test_config_targets_quarterly_lite_with_08s_refresh(self):
        config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))

        self.assertEqual(config["purchase"]["plan_type"], "quarterly")
        self.assertEqual(get_subscription_period_label("quarterly"), "连续包季")
        self.assertEqual(get_refresh_interval(config), 0.8)


if __name__ == "__main__":
    unittest.main()
