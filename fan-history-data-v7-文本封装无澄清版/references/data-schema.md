# 数据字段与查询说明

## `history-records.jsonl.xz.b64`

结构化记录以单个 Base64 文本文件保存；Base64 内部是 XZ 无损压缩数据，解码后的逻辑内容仍为标准 JSONL。必须由 `query_history.py` 直接查询，无需手工解码或解压。采用文本封装是为了兼容 Skill 导入器，不改变数据内容，也不拆分数据集。

关键字段：

- `record_id`：历史参数记录唯一标识。
- `case_id`：项目—供应商—风机类型案例标识。
- `source_id`、`source_file`、`sheet`、`row`、`cell`、`location`：包内历史证据的来源定位。
- `source_batch`：历史资料构建批次的名称标签，仅用于溯源；不是外部文件路径或运行依赖。
- `source_project`：当前清标文件所属项目。
- `project`：该条历史值对应项目；对标列会尽量使用对标项目名。
- `fan_type`：归一后的风机类型。
- `supplier_raw`、`supplier_canonical`：供应商原称与归一名。
- `record_role`：`bid_history` 或 `history_reference`。
- `parameter_raw`、`parameter_canonical`：参数原称与归一名。
- `tender_requirement_raw`：历史清标表中的招标要求原文。
- `historical_value_raw`：历史供应商/对标列原文。
- `numeric_value`、`normalized_unit`：仅用于分析的标准化数值和单位。
- `operating_condition`：TB、MCR 等工况。
- `value_provenance`：`supplier_submission` 或 `internal_calculation`。
- `analysis_eligible`：是否默认允许进入数值历史分析。
- `evidence_raw`：整行原文，便于复核上下文。
- `source_status`、`extraction_confidence`：证据质量提示。

## `history-cases.jsonl.xz.b64`

每条案例汇总同一来源、项目、供应商和风机类型的历史记录，并在 `project_conditions` 中保留设计流量、工况流量、静压、全压、温度、转速和电机功率等条件，用于相似性筛选。

`raw-clear-corpus.jsonl.xz.b64` 与 `raw-agreement-corpus.jsonl.xz.b64` 同样各自只有一个 Base64 文本文件，内部为 XZ 无损数据，分别保留清标表逐行原文和技术协议逐段、逐表、逐页原文。检索程序会透明读取，不需要手工解码或解压。

## 查询命令

```powershell
python scripts/query_history.py coverage
python scripts/query_history.py sources --project 清远 --limit 20
python scripts/query_history.py records --fan-type 一次风机 --parameter 轴功率 --supplier 新乡西玛 --condition TB --numeric-only --deduplicate --limit 20
python scripts/query_history.py search --corpus agreement --query 轴承冷却方式 --limit 20
python scripts/query_history.py analyze --fan-type 一次风机 --parameter 轴功率 --value 230 --unit kW --supplier 新乡西玛 --condition TB工况 --design-flow 101400 --static-pressure 5200 --limit 8
```

命令输出 JSON，便于智能体引用项目、设备、供应商、原文、文件和位置。`analyze` 的统计异常方法只是筛查方法，输出中的强制边界必须保留。
