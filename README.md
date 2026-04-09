# Excel to Markdown Wiki 自动化工具

## 功能概述

将多张关联的 Excel 工作表（故障现象、定界手段、恢复方案）自动转换为结构化的 Markdown 运维预案文件。

核心能力：
- **Excel 解析** — 读取 3 张工作表，通过外键关联（故障现象 → 定界手段 → 恢复方案）组合数据
- **双模式运行** — `--sheets` 仅生成 Markdown（无需 LLM），`--full` 额外调用 LLM 生成恢复预案
- **双 LLM 后端** — 支持 Ollama（本地）和 OpenAI 兼容 API（DeepSeek、通义千问等）
- **缺失数据建议** — 外键关联缺失时，可由 LLM 生成参考建议
- **故障相似性分析** — LLM 识别相似故障现象，按层级规则自动合并定界手段和恢复方案到预案中
- **增量覆盖** — 多次运行仅覆盖相关文件，不影响已有文件

## 数据流

```
Excel (.xlsx)
  ├── Sheet1: 故障现象场景清单模版 (ID: UPxxx/APxxx)
  ├── Sheet2: 定界手段模板         (ID: Axxxx)
  └── Sheet3: 恢复方案模板         (ID: QRxxxx/Rxxxx)

       ↓ 外键关联解析

故障现象 → 定界手段 → 恢复方案

       ↓ 逐一调用 LLM（仅 --full 模式）

result/
  ├── 故障现象/          ← 每个 Sheet 行对应一个 .md
  ├── 定界手段/
  ├── 恢复方案/
  ├── UP001_核心网连接超时.md   ← LLM 生成的恢复预案
  └── index.md
```

## 前置准备

### Python 依赖

```bash
pip install -r requirements.txt
```

依赖：`pandas`、`openpyxl`、`requests`（OpenAI 模式）

### LLM 服务

**Ollama（默认，本地运行）：**

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
ollama pull qwen2.5:7b
```

**OpenAI 兼容 API：** 修改 `config.py` 中的 `DEFAULT_CONFIG` 的 `llm` 部分即可切换。

## 使用方法

```bash
# 生成故障现象、定界手段、恢复方案 Markdown（不需要 LLM）
python main.py --sheets

# 指定 Excel 文件路径
python main.py --sheets --excel path/to/data.xlsx

# 全量生成：上述三个 + LLM 恢复预案
python main.py --full

# 全量生成 + 指定 Excel 和输出目录
python main.py --full --excel path/to/data.xlsx --output path/to/output
```

> Excel 路径和输出目录等配置可在 `config.py` 的 `DEFAULT_CONFIG` 中修改，`--excel`、`--output` 参数优先级高于配置。

## Agent 调用

本项目已封装为 Agent Skill，详见 `SKILL.MD`。Agent 可通过以下命令调用：

```bash
python main.py --full --excel <用户提供的Excel路径> --output <用户提供的输出路径>
```

### 输出目录

```
result/
  故障现象/
    UP0001_页面大量接口报错.md
    AP0002_MQS消息重复.md
  定界手段/
    A0001_排查关键依赖平台是否异常.md
    ...
  恢复方案/
    R0001_联系关键依赖平台支持人员协助处理.md
    ...
  UP0001_页面大量接口报错.md    ← LLM 恢复预案（仅 --full）
  index.md                       ← 汇总索引（仅 --full）
```

## 故障相似性分析

### 功能说明

当多个故障现象的描述存在相似性时（例如都包含"网关超时"），说明它们可能有相同的根因。开启相似性分析后，系统会：

1. 调用 LLM 分析所有故障现象之间的描述相似性
2. 根据故障表现层级自动判断合并方向
3. 将低层级故障的定界手段和恢复方案合并到高层级故障的预案中

### 故障表现层级

在故障现象 Excel sheet 中新增 **「故障表现层级」** 列，为每行故障现象人工标注层级：

| 层级 | 说明 |
|------|------|
| 用户界面层 | 面向用户的表现（如页面报错） |
| 接入层 | 网关/负载均衡层 |
| 服务层 | 应用服务层 |
| 平台层 | 中间件/平台层 |
| 资源层 | 基础设施层（数据库、服务器等） |

层级从高到低：`用户界面层 → 接入层 → (服务层, 平台层) → 资源层`

### 合并规则

- **规则一**：低层级故障的定界手段和恢复方案合入高层级故障的预案
- **规则二**：同层级的故障现象不合并
- **规则三**：不能将高层级的合入低层级（避免循环依赖）

### 配置

```python
# config.py — DEFAULT_CONFIG 中修改
"similarity_analysis": {
    "enabled": True,              # 开启相似性分析（仅 --full 模式生效）
    "timeout_seconds": 300,       # 分析调用超时时间
    "max_phenomena": 50,          # 最大分析数量
},
```
