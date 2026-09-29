# weekly-report

把每日报告归档，并从中生成周报。

- **确定性优先**：采集、解析、汇总、渲染全部是普通 Python，不依赖模型。LLM 只用于可选的
  文字润色，且失败会自动回落到确定性输出——**它永远不是生成报告的必要条件**。
- **零硬依赖**：核心路径只用标准库。`rich` / `questionary` 是可选的终端增强。
- **原文永久保留**：每份日报的逐字原文随档案一起存下，随时可以重解析、重生成任意一周。
- **输出确定**：报告里不含生成时间戳，同样的输入逐字节一致——重生成同一周不会产生无意义的
  git 差异，报告文件适合纳入版本控制。

## 快速开始

```bash
git clone git@github.com:huangrong1995/weekly-report.git
cd weekly-report

./wreport init                      # 交互式初始化（也可 --yes 用默认值）
./wreport daily add < 今日日报.txt   # 录入并归档（默认读 stdin）
./wreport daily add --date 2026-09-23 --text "今日完成
1. 某事项（调试中）"
./wreport weekly build --week 2026-W39
./wreport weekly build --week 2026-W39 --stdout   # 只看不落盘
./wreport status                    # 总览
./wreport sync                      # 提交并推送
```

无需安装即可运行（`./wreport` 会把 `src/` 加进 `sys.path`）。也可以 `pip install -e .`
后用 `wreport` 命令，或 `python3 -m wreport`。

## 命令

| 命令 | 说明 |
|---|---|
| `init` | 交互式建立 `data/config.json` |
| `daily add` | 录入日报：读 stdin，或 `--file` / `--text` / `--date` |
| `daily list` | 列日报，可 `--week 2026-W39` |
| `daily show DATE` | 显示某天归档后的日报 |
| `weekly build` | 生成周报：`--week` / `--date` / `--polish` / `--force` / `--stdout` |
| `weekly list` | 列已有周报 |
| `ledger` | 进展台账（跨周汇总，`--weeks N`） |
| `status` | 总览与状态分布 |
| `sync` | `git add` + commit + push（`--no-push` 只提交） |
| `lint` | 自检：数据、归档文件、周报三者是否一致 |

每个子命令都有 `--help`，并支持 `--json` 便于脚本/cron 消费。出错返回非零退出码。

## 状态是怎么来的

状态是**写下来的**，不是猜出来的。优先级：

1. **作者写的标记** —— `（调试中）`、`（未开始）`、`(完成)`，中英文括号都认。
2. **所在栏目的默认值** —— `今日完成` 下的未标记条目 = 完成；`明日计划` 下的 = 未开始。
3. **行内动词**（仅当既无栏目也无标记时）—— `已上线`、`已完成`。

回到第 2 条的原因：`明日计划：上线新版本` 里的「上线」是计划，不是战绩，所以**有栏目时行内动词不参与判断**。

### 这个工具**不做**什么

**不会**因为一个事项在后一天的日报里没出现，就把它推断成"已完成"。缺失只表示作者那天
没写它，报告里保留作者最后写下的状态。这是刻意的选择：跨日推断太定制化，也会让报告
与实际记录脱节。同一事项跨日出现时，只做**合并**——取作者最后一次写下的状态，并把
每日状态变化以时间线形式展示出来：

```
- 🔧 备注信息保留  `09/21 ⏸️ → 09/22 🔧`
```

## 目录结构

```
weekly-report/
├── wreport                  # 免安装启动器
├── src/wreport/
│   ├── models.py            # 数据类 + 状态词表
│   ├── weeks.py             # ISO 周运算
│   ├── parser.py            # 纯文本 -> 结构化条目（规则显式、可测）
│   ├── store.py             # data/*.json 读写（原子写）
│   ├── archive.py           # 日报归档（排版 + 逐字原文）
│   ├── weekly.py            # 周报聚合与渲染
│   ├── llm.py               # 可选润色
│   ├── render.py            # 终端输出（rich 可选）
│   ├── gitutil.py           # git 集成
│   └── cli.py               # 统一入口
├── templates/               # 可选的外层模板（见 templates/README.md）
├── data/                    # entries.json / index.json / config.json
├── reports/daily/           # YYYY-MM-DD.md
├── reports/weekly/          # YYYY-Www.md
└── tests/                   # 用真实日报做夹具
```

## 数据层

`data/entries.json` 是唯一的事实来源，结构稳定、可直接读改：

```json
{
  "version": 1,
  "entries": [
    {
      "date": "2026-09-21",
      "week": "2026-W39",
      "raw_text": "今日完成\n1. …",
      "items": [
        {"text": "保留变更类型及模块", "status": "doing", "raw_status": "调试中",
         "level": 1, "project": "Change-Pilot变更单提取工具修改几个需求",
         "section": "done", "is_group": false, "order": 3}
      ],
      "sections": {"done": [], "todo": [], "notes": []},
      "source": "feishu",
      "archived_at": "2026-09-29T09:34:27"
    }
  ]
}
```

因为 `raw_text` 随记录保存，改了解析规则之后可以对历史数据重新解析，不需要重新找作者要原始消息。
`data/index.json` 是从 `entries.json` 派生的快速索引（周 → 日期、条数），可随时重建。

## 配置

`data/config.json`：

| 键 | 默认 | 说明 |
|---|---|---|
| `owner` | `""` | 汇报人，写进周报 |
| `week_start` | `monday` | 周起始日 |
| `reports_dir` | `reports` | 报告输出目录 |
| `llm.enabled` | `false` | 是否启用润色 |
| `llm.base_url` / `llm.model` | `""` | OpenAI 兼容端点 |
| `llm.api_key_env` | `WREPORT_API_KEY` | **只存环境变量名**，密钥本身绝不落盘 |

## 自动化（可选）

`sync` 与 `--yes` / `--json` 可以无交互运行，适合放 cron：

```bash
# 每个工作日 17:30 把当天日报（先由提醒流程写入文件）归档并推送
30 17 * * 1-5  cd /path/to/weekly-report && ./wreport daily add --file /tmp/today.txt --yes && ./wreport sync --yes

# 每周四 15:00 生成当周周报草稿，不推送，留给你审阅
0 15 * * 4     cd /path/to/weekly-report && ./wreport weekly build --yes
```

## 测试

```bash
python3 -m unittest discover -s tests -t tests -v
```

夹具是真实日报的逐字副本——包括 `今日完成` 这个标题行，因为它决定了其下每一条未标记条目
的默认状态；少了它，测试就会跑在一个与真实输入不符的前提上。

## 许可

MIT