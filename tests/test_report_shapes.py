"""Report shapes and the no-content-loss invariant.

Daily reports arrive in more than one layout. Whatever the layout, the archive must
account for every line the author wrote -- a line vanishing because it matched no
pattern is the failure mode this file exists to prevent.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402
from wreport import archive, models, parser  # noqa: E402

# The 2026-09-29 report: a bare label line per project, numbered items beneath.
D29 = """代码门禁
1. 语言Jenkins Code Review分级评分功能，目前插件不支持分级评分，暂且搁置
2. 代码检视报告md转html功能优化，优化模板显示效果
3. 流水线集成 Change-Pilot 变更点提炼功能
EMV自动化流水线
1. 定位并修复部分问题中
"""

# A layout mixing a section heading with a nested project.
MIXED = """今日完成
1. 代码门禁
a. 甲事项（调试中）
b. 乙事项
明日计划
1. 丙事项
"""


class TestBareLabelProjects(unittest.TestCase):
    def setUp(self):
        self.e = parser.parse_report(D29, date="2026-09-29")

    def test_labels_become_groups(self):
        groups = [i.text for i in self.e.items if i.is_group]
        self.assertEqual(["代码门禁", "EMV自动化流水线"], groups)

    def test_numbered_items_inherit_the_label(self):
        by_project = self.e.items_by_project()
        self.assertEqual(3, len(by_project["代码门禁"]))
        self.assertEqual(1, len(by_project["EMV自动化流水线"]))

    def test_nothing_is_dropped(self):
        """裸行标题曾经被整行丢弃——这是最严重的失败模式。"""
        rendered = archive.render_daily(self.e)
        for token in ("代码门禁", "EMV自动化流水线", "暂且搁置", "优化模板显示效果",
                      "变更点提炼功能", "定位并修复部分问题中"):
            self.assertIn(token, rendered, token)

    def test_group_labels_carry_no_status(self):
        for g in [i for i in self.e.items if i.is_group]:
            self.assertEqual(models.UNKNOWN, g.status, g.text)

    def test_items_are_indented_under_their_label(self):
        """编号条目在裸行标题下仍应缩进，否则看不出从属关系。"""
        rendered = archive.render_daily(self.e)
        self.assertIn("- **代码门禁**\n  - ⏸️", rendered)
        self.assertIn("- **EMV自动化流水线**\n  - 🔧", rendered)


class TestNoContentLoss(unittest.TestCase):
    def _tokens(self, raw):
        """Meaningful content of each line, with numbering and markers removed."""
        out = []
        for line in raw.split("\n"):
            body = line.strip()
            for pat in (parser._TOP_RE, parser._SUB_FLUSH_RE):
                m = pat.match(body)
                if m:
                    body = m.group(1).strip()
                    break
            body = parser._MARKER_RE.sub("", body).strip().rstrip("。.,，;；")
            if body:
                out.append(body)
        return out

    def test_every_fixture_line_is_accounted_for(self):
        for date, raw in list(fixtures.BY_DATE.items()) + [("2026-09-29", D29),
                                                           ("mixed", MIXED)]:
            e = parser.parse_report(raw, date="2026-09-29" if len(date) < 9 else date)
            rendered = archive.render_daily(e)
            missing = [t for t in self._tokens(raw) if t not in rendered]
            self.assertEqual([], missing, "%s 丢了这些行: %s" % (date, missing))

    def test_plain_prose_is_kept(self):
        raw = "今日完成\n1. 甲事项\n今天整体进度慢于预期。\n"
        body = archive.render_daily(parser.parse_report(raw, date="2026-09-29"))
        body = body.split("## 逐字原文")[0]
        self.assertIn("今天整体进度慢于预期。", body)

    def test_prose_with_no_section_is_kept(self):
        """没有栏目打开时，散文也不能被丢掉。"""
        raw = "这是一句没有栏目的说明文字，比较长所以不会被当成项目标题。\n1. 甲事项\n"
        e = parser.parse_report(raw, date="2026-09-29")
        self.assertIn("这是一句没有栏目的说明文字",
                      archive.render_daily(e).split("## 逐字原文")[0])

    def test_long_bare_line_is_not_a_project_label(self):
        long_line = "这一行虽然没有任何编号但它明显是一整句话而不是项目标题所以不能当成分组标签"
        e = parser.parse_report(long_line + "\n1. 甲\n", date="2026-09-29")
        self.assertFalse(any(i.is_group and i.text == long_line for i in e.items))


class TestMixedLayout(unittest.TestCase):
    def test_sections_and_nested_projects_coexist(self):
        e = parser.parse_report(MIXED, date="2026-09-29")
        self.assertEqual(models.DOING,
                         [i for i in e.items if i.text == "甲事项"][0].status)
        self.assertEqual(models.DONE,
                         [i for i in e.items if i.text == "乙事项"][0].status)
        self.assertEqual(models.TODO,
                         [i for i in e.items if i.text == "丙事项"][0].status)


class TestStatusVocabulary(unittest.TestCase):
    def test_shelved_reads_as_not_done(self):
        e = parser.parse_report(D29, date="2026-09-29")
        row = [i for i in e.items if i.text.startswith("语言Jenkins")][0]
        self.assertEqual(models.TODO, row.status)

    def test_trailing_progressive_marks_in_progress(self):
        e = parser.parse_report(D29, date="2026-09-29")
        row = [i for i in e.items if i.text == "定位并修复部分问题中"][0]
        self.assertEqual(models.DOING, row.status)

    def test_progressive_suffix_does_not_fire_mid_word(self):
        """「支持中文」不以中结尾，不能被当成进行中。"""
        e = parser.parse_report("1. 支持中文显示\n", date="2026-09-29")
        self.assertEqual(models.UNKNOWN, e.items[0].status)


class TestUnmarkedFallback(unittest.TestCase):
    def test_default_is_unknown(self):
        e = parser.parse_report(D29, date="2026-09-29")
        row = [i for i in e.items if i.text.startswith("流水线集成")][0]
        self.assertEqual(models.UNKNOWN, row.status)

    def test_opt_in_fallback_applies_only_to_unmarked_lines(self):
        """配置成 done 之后：无标记的算完成，但作者写的状态仍然优先。"""
        e = parser.parse_report(D29, date="2026-09-29", unmarked=models.DONE)
        rows = {i.text: i.status for i in e.items}
        self.assertEqual(models.DONE, rows["流水线集成 Change-Pilot 变更点提炼功能"])
        self.assertEqual(models.DONE, rows["代码检视报告md转html功能优化，优化模板显示效果"])
        # explicit evidence still wins
        self.assertEqual(models.TODO, rows["语言Jenkins Code Review分级评分功能，目前插件不支持分级评分，暂且搁置"])
        self.assertEqual(models.DOING, rows["定位并修复部分问题中"])

    def test_section_default_beats_the_fallback(self):
        e = parser.parse_report("今日完成\n1. 甲\n", date="2026-09-29",
                                unmarked=models.TODO)
        self.assertEqual(models.DONE, e.items[0].status)


if __name__ == "__main__":
    unittest.main(verbosity=2)