"""Parser tests.

Fixtures come from `fixtures.py` and are the real reports, verbatim -- including the
「今日完成」 heading, which is what gives every unmarked line its default status.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402
from wreport import models, parser  # noqa: E402

D21, D22, D23 = fixtures.D21, fixtures.D22, fixtures.D23


def status_of(entry, text):
    for it in entry.items:
        if it.text == text:
            return it.status
    return None


class TestSectionDefaults(unittest.TestCase):
    def test_bare_item_under_done_section_is_done(self):
        text = "今日完成\n1. 服务器部署上线\n"
        e = parser.parse_report(text, date="2026-09-23")
        self.assertEqual(1, len(e.items))
        self.assertEqual(models.DONE, e.items[0].status)

    def test_plan_section_yields_todo_not_done(self):
        """'上线' inside a plan must not be read as finished."""
        text = "明日计划\n1. 上线新版本\n"
        e = parser.parse_report(text, date="2026-09-23")
        self.assertEqual(models.TODO, e.items[0].status)

    def test_no_section_falls_back_to_inline_verb(self):
        e = parser.parse_report("1. 服务器部署上线\n", date="2026-09-23")
        self.assertEqual(models.DONE, e.items[0].status)

    def test_inline_verb_does_not_apply_when_a_section_speaks(self):
        """同一句话在「今日完成」与「明日计划」下，结论必须不同。"""
        under_done = parser.parse_report("今日完成\n1. 上线新版本\n", date="2026-09-23")
        under_plan = parser.parse_report("明日计划\n1. 上线新版本\n", date="2026-09-23")
        self.assertEqual(models.DONE, under_done.items[0].status)
        self.assertEqual(models.TODO, under_plan.items[0].status)


class TestExplicitMarkers(unittest.TestCase):
    def test_marker_overrides_section_default(self):
        text = "今日完成\n1. 备注信息保留（未开始）\n"
        e = parser.parse_report(text, date="2026-09-21")
        self.assertEqual(models.TODO, e.items[0].status)
        self.assertEqual("未开始", e.items[0].raw_status)

    def test_marker_is_kept_out_of_text_but_raw_is_recorded(self):
        text = "今日完成\n1. 保留变更类型及模块（调试中）\n"
        e = parser.parse_report(text, date="2026-09-21")
        self.assertEqual("保留变更类型及模块", e.items[0].text)
        self.assertEqual("调试中", e.items[0].raw_status)
        self.assertEqual(models.DOING, e.items[0].status)

    def test_doing_checked_before_done(self):
        """'修复中' 不能因为含 '修复' 被当作已完成。"""
        e = parser.parse_report("今日完成\n1. 问题修复中（修复中）\n", date="2026-09-23")
        self.assertEqual(models.DOING, e.items[0].status)

    def test_ascii_and_cjk_brackets_both_work(self):
        for marker in ("（调试中）", "(调试中)", "【调试中】", "[调试中]"):
            e = parser.parse_report("今日完成\n1. 某事项%s\n" % marker,
                                    date="2026-09-23")
            self.assertEqual(models.DOING, e.items[0].status, marker)


class TestStructure(unittest.TestCase):
    def test_nesting_and_grouping(self):
        e = parser.parse_report(D21, date="2026-09-21")
        # 2 top-level group headers + 4 nested items
        self.assertEqual(6, len(e.items))
        groups = [i for i in e.items if i.is_group]
        self.assertEqual(2, len(groups))
        self.assertEqual(["Change-Pilot变更单提取工具修改几个需求", "代码门禁"],
                         [g.text for g in groups])

    def test_group_headers_carry_no_status(self):
        """分组标题是结构性标签；继承栏目默认值会渲染成「✅ 完成」，误导读者。"""
        e = parser.parse_report(D21, date="2026-09-21")
        for g in [i for i in e.items if i.is_group]:
            self.assertEqual(models.UNKNOWN, g.status, g.text)

    def test_nested_items_inherit_project(self):
        e = parser.parse_report(D21, date="2026-09-21")
        nested = [i for i in e.items if i.level == 1]
        self.assertEqual(4, len(nested))
        self.assertTrue(all(i.project for i in nested))
        self.assertEqual("代码门禁", nested[-1].project)

    def test_top_level_without_children_is_a_real_item(self):
        """9/23 的 '1. …服务器部署上线' 没有子项，它自己是事项；
        '2. 代码门禁' 只引出一组子项，是分组。"""
        e = parser.parse_report(D23, date="2026-09-23")
        top = [i for i in e.items if i.level == 0]
        self.assertEqual(2, len(top))
        self.assertFalse(top[0].is_group)
        self.assertTrue(top[1].is_group)
        self.assertEqual(models.DONE, top[0].status)
        self.assertEqual("代码门禁", top[1].text)

    def test_cjk_numbering(self):
        text = "今日完成\n一、服务器部署上线\n二、问题修复\n"
        e = parser.parse_report(text, date="2026-09-23")
        self.assertEqual(2, len(e.items))
        self.assertEqual(models.DONE, e.items[0].status)
        self.assertEqual(models.DONE, e.items[1].status)

    def test_section_is_recorded_on_item(self):
        e = parser.parse_report("明日计划\n1. 上线新版本\n", date="2026-09-23")
        self.assertEqual("todo", e.items[0].section)

    def test_heading_only_matches_standalone_labels(self):
        """含「问题」的普通条目不能被当成「问题与思考」栏目。"""
        self.assertIsNone(parser._match_section("a. AI Code Review问题修复"))
        self.assertIsNone(parser._match_section("c. 备注信息保留（未开始）"))
        self.assertIsNotNone(parser._match_section("今日完成"))
        self.assertIsNotNone(parser._match_section("## 明日计划"))
        self.assertIsNotNone(parser._match_section("一、本周小结"))


class TestRealReports(unittest.TestCase):
    def test_day21_three_requirements(self):
        d21 = parser.parse_report(D21, date="2026-09-21")
        self.assertEqual(models.DONE, status_of(d21, "版本变更信息前置"))
        self.assertEqual(models.DOING, status_of(d21, "保留变更类型及模块"))
        self.assertEqual(models.TODO, status_of(d21, "备注信息保留"))

    def test_day22_marker_wins_over_heading(self):
        d22 = parser.parse_report(D22, date="2026-09-22")
        self.assertEqual(models.DOING, status_of(d22, "备注信息保留"))

    def test_day23_top_level_line_is_work(self):
        d23 = parser.parse_report(D23, date="2026-09-23")
        self.assertEqual(models.DONE,
                         status_of(d23, "Change-Pilot变更单提取工具服务器部署上线"))

    def test_raw_text_preserved_byte_for_byte(self):
        for date, raw in fixtures.BY_DATE.items():
            e = parser.parse_report(raw, date=date)
            self.assertEqual(raw, e.raw_text)

    def test_summarize_counts_exclude_groups(self):
        e = parser.parse_report(D21, date="2026-09-21")
        counts = parser.summarize(e)
        self.assertEqual(4, sum(counts.values()))  # 6 lines - 2 group headers


if __name__ == "__main__":
    unittest.main(verbosity=2)