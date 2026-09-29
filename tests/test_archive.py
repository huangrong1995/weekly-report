"""Daily archiving: format only, never invent.

The rules under test are the ones that keep the archive trustworthy:

* a heading the author did not write must not appear in the file;
* re-archiving identical input produces identical bytes (no volatile timestamp);
* the verbatim original is always carried along.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402
from wreport import archive, models, parser  # noqa: E402


class TestNoInventedHeadings(unittest.TestCase):
    def test_report_without_a_heading_gets_no_heading(self):
        """9/28 的原文没有「今日完成」；归档文件里不能凭空多出这个标题。"""
        raw = ("1. 代码门禁\n"
               "a. 完成md转html功能，可以直接在网页查看AI Code Review生成的检查报告\n"
               "2. EMV流水线问题定位\n"
               "a. 添加调试日志，定位EMV相关问题\n")
        e = parser.parse_report(raw, date="2026-09-28")
        md = archive.render_daily(e)
        self.assertNotIn("## 今日完成", md)
        self.assertIn("## 事项（原文未分栏目）", md)

    def test_report_with_a_heading_keeps_it(self):
        e = parser.parse_report(fixtures.D21, date="2026-09-21")
        md = archive.render_daily(e)
        self.assertIn("## 今日完成", md)
        self.assertNotIn("事项（原文未分栏目）", md)

    def test_plan_section_is_separated(self):
        raw = "今日完成\n1. 甲事项\n\n明日计划\n1. 乙事项\n"
        md = archive.render_daily(parser.parse_report(raw, date="2026-09-28"))
        self.assertIn("## 今日完成", md)
        self.assertIn("## 明日计划", md)
        self.assertLess(md.index("## 今日完成"), md.index("## 明日计划"))


class TestDeterminism(unittest.TestCase):
    def test_render_is_byte_identical(self):
        a = archive.render_daily(parser.parse_report(fixtures.D21, date="2026-09-21"))
        b = archive.render_daily(parser.parse_report(fixtures.D21, date="2026-09-21"))
        self.assertEqual(a, b)

    def test_no_volatile_timestamp_in_output(self):
        md = archive.render_daily(parser.parse_report(fixtures.D21, date="2026-09-21"))
        self.assertNotIn("归档时间", md)
        # the metadata still exists on the entry itself
        e = parser.parse_report(fixtures.D21, date="2026-09-21")
        self.assertTrue(e.archived_at)


class TestVerbatimPreserved(unittest.TestCase):
    def test_original_is_carried_verbatim(self):
        for date, raw in fixtures.BY_DATE.items():
            md = archive.render_daily(parser.parse_report(raw, date=date))
            self.assertIn(raw.rstrip("\n"), md)
            self.assertIn("逐字原文（备查）", md)

    def test_marker_survives_in_the_text(self):
        """作者写的「（调试中）」在归档里必须原样保留。"""
        e = parser.parse_report(fixtures.D21, date="2026-09-21")
        md = archive.render_daily(e)
        self.assertIn("调试中", md)
        self.assertIn("未开始", md)


class TestCounts(unittest.TestCase):
    def test_groups_excluded_from_counts(self):
        e = parser.parse_report(fixtures.D21, date="2026-09-21")
        counts = archive.status_counts(e)
        self.assertEqual(4, sum(counts.values()))
        self.assertEqual(2, counts.get(models.DONE, 0))

    def test_describe_counts(self):
        e = parser.parse_report(fixtures.D21, date="2026-09-21")
        s = archive.describe_counts(archive.status_counts(e))
        self.assertIn("完成", s)
        self.assertIn("2", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)