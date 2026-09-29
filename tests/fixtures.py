"""Real reports used as test fixtures, kept verbatim.

These are the three daily reports this tool was first built against, byte-for-byte as
the author wrote them -- including the 「今日完成」 heading, because that heading is what
sets the default status of every unmarked line beneath it. Dropping it would make the
tests pass on a premise that does not match the real input.
"""

D21 = """今日完成
1. Change-Pilot变更单提取工具修改几个需求
a. 版本变更信息前置
b. 保留变更类型及模块（调试中）
c. 备注信息保留（未开始）
2. 代码门禁
a. AI Code Review全量上线，开放所有仓库扫描
"""

D22 = """今日完成
1. Change-Pilot变更单提取工具修改几个需求
a. 备注信息保留（调试中）
2. 代码门禁
a. AI Code Review部署服务器上线
"""

D23 = """今日完成
1. Change-Pilot变更单提取工具服务器部署上线
2. 代码门禁
a. AI Code Review问题修复
"""

BY_DATE = {"2026-09-21": D21, "2026-09-22": D22, "2026-09-23": D23}