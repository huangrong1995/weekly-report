"""Weekly rollup and rendering.

The behaviour worth guarding here is negative: status must NOT be inferred from an item
stopping being written down. The last status the author actually wrote is what stands.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402
from wreport import models, parser, weekly  # noqa: E402


def week_entries():
    return [parser.parse_report(fixtures.BY_DATE[d], date=d)
            for d in sorted(fixtures.BY_DATE)]


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.rows = weekly.aggregate(week_entries())

    def find(self, text):
        for r in self.rows:
            if r.text == text:
                return r
        return None

    def test_groups_are_not_rows(self):
        self.assertIsNone(self.find("代码门禁"))
        self.assertIsNone(self.find("Change-Pilot变更单提取工具修改几个需求"))

    def test_repeated_item_merges_into_one_row(self):
        row = self.find("备注信息保留")
        self.assertIsNotNone(row)
        self.assertEqual(2, row.days)
        self.assertEqual("2026-09-21", row.first_date)
        self.assertEqual("2026-09-22", row.last_date)

    def test_latest_explicit_status_wins(self):
        """9/21 写「（未开始）」、9/22 写「（调试中）」 -> 结果必须是 调试中。"""
        self.assertEqual(models.DOING, self.find("备注信息保留").status)

    def test_absent_item_keeps_last_written_status(self):
        """9/23 没有列「备注信息保留」——绝不能因此把它算成已完成。"""
        row = self.find("备注信息保留")
        self.assertNotEqual(models.DONE, row.status)
        self.assertEqual("2026-09-22", row.last_date)

    def test_timeline_only_when_status_moved(self):
        self.assertEqual("09/21 ⏸️ → 09/22 🔧", self.find("备注信息保留").timeline)
        # a single-day item has no timeline
        self.assertEqual("", self.find("AI Code Review问题修复").timeline)

    def test_items_seen_once_dated_correctly(self):
        self.assertEqual("2026-09-23", self.find("AI Code Review问题修复").last_date)
        self.assertEqual(1, self.find("AI Code Review问题修复").days)


class TestCoverage(unittest.TestCase):
    def test_missing_days_are_reported(self):
        cov = weekly.coverage(week_entries(), "2026-W39")
        self.assertEqual(["2026-09-21", "2026-09-22", "2026-09-23"], cov["covered"])
        self.assertEqual(["2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"],
                         cov["missing"])


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.md = weekly.build_weekly(week_entries(), "2026-W39", owner="测试")

    def test_has_all_sections(self):
        for heading in ("## 一、本周完成", "## 二、进行中", "## 三、待推进",
                        "## 四、下周计划", "## 五、本周小结"):
            self.assertIn(heading, self.md)

    def test_header_names_the_week_and_owner(self):
        self.assertIn("2026 W39（09/21 – 09/27）", self.md)
        self.assertIn("测试", self.md)

    def test_uncovered_days_are_flagged_not_silently_empty(self):
        self.assertIn("未覆盖日期", self.md)
        self.assertIn("09/24", self.md)

    def test_completed_items_are_listed(self):
        self.assertIn("AI Code Review问题修复", self.md)
        self.assertIn("Change-Pilot变更单提取工具服务器部署上线", self.md)

    def test_incomplete_item_is_not_in_the_done_section(self):
        done_part = self.md.split("## 二、进行中")[0]
        self.assertNotIn("备注信息保留", done_part)

    def test_empty_week_fails_loudly_at_cli_not_here(self):
        """build_weekly 本身只渲染；空数据应由 CLI 拦下。"""
        md = weekly.build_weekly([], "2026-W39")
        self.assertIn("_（无）_", md)

    def test_regeneration_is_byte_identical(self):
        """输出不含生成时间；同样输入必须得到同样字节，否则每次重生成都会产生 git 差异。"""
        a = weekly.build_weekly(week_entries(), "2026-W39", owner="测试")
        b = weekly.build_weekly(week_entries(), "2026-W39", owner="测试")
        self.assertEqual(a, b)
        self.assertNotIn("生成时间", a)


class TestTemplate(unittest.TestCase):
    def _root_with(self, content):
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "templates"))
        with open(os.path.join(d, "templates", "weekly.md"), "w", encoding="utf-8") as fh:
            fh.write(content)
        return d

    def test_no_template_returns_body_unchanged(self):
        import tempfile
        md = "## 一、本周完成\n- x\n"
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(md, weekly.apply_template(md, d, {}, "2026-W39"))

    def test_template_with_placeholders_wraps_body(self):
        md = "# 标题\n\n> meta\n\n## 一、本周完成\n\n- x\n"
        d = self._root_with("# {{week}}\n\n{{body}}\n")
        out = weekly.apply_template(md, d, {}, "2026-W39")
        self.assertTrue(out.startswith("# 2026-W39"))
        self.assertIn("## 一、本周完成", out)
        # the generated H1/meta are replaced by the template's own
        self.assertNotIn("> meta", out)

    def test_template_without_placeholders_is_ignored(self):
        md = "## 一、本周完成\n"
        d = self._root_with("plain text, no placeholders\n")
        self.assertEqual(md, weekly.apply_template(md, d, {}, "2026-W39"))


if __name__ == "__main__":
    unittest.main(verbosity=2)