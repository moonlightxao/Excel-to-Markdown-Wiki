# Excel to Markdown Wiki 自动化工具

将多张关联的 Excel 工作表（故障现象、定界手段、恢复方案）自动转换为标准化的 Markdown 运维预案文件。通过解析 Excel 外键关联，调用 LLM 生成结构化文档。

当故障现象缺少对应的定界手段或恢复方案时，可由 LLM 生成参考建议并标注在文档末尾。

## 数据流

```
Excel (.xlsx)
  ├── Sheet1: 故障现象场景清单模版 (ID: UPxxx/APxxx)
  ├── Sheet2: 定界手段模板         (ID: Axxxx)
  └── Sheet3: 恢复方案模板         (ID: QRxxxx/Rxxxx)

       ↓ 外键关联解析

故障现象 → 定界手段 → 恢复方案

       ↓ 逐一调用 LLM

output/
  ├── UP001_核心网连接超时.md
  ├── UP002_数据吞吐量下降.md
  └── index.md
```

## 安装

### 1. Python 依赖

```bash
pip install -r requirements.txt
```

依赖清单：
- `pandas` — Excel 读取与数据处理
- `openpyxl` — .xlsx 文件引擎
- `pyyaml` — 配置文件解析
- `requests` — OpenAI 兼容 API HTTP 客户端（使用 OpenAI 后端时需要）

> Ollama 模式使用 Python 标准库 `urllib`，无需额外依赖。OpenAI 模式依赖 `requests` 库。

### 2. Ollama（LLM 推理服务）

```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 启动服务
ollama serve

# 拉取模型（根据你的硬件选择）
ollama pull qwen2.5:7b      # 推荐，需 ~5GB 内存
ollama pull qwen2.5:3b      # 低配机器可选，需 ~2GB 内存
```

如果 Ollama 运行在另一台机器上，修改 `config.yaml` 中的 `base_url` 即可：

```yaml
llm:
  base_url: "http://192.168.1.100:11434"
```

## 快速开始

```bash
# 1. 复制并编辑配置文件（设置 Excel 路径、LLM 参数等）
cp config.example.yaml config.yaml

# 2. 生成故障现象、定界手段、恢复方案 Markdown（不需要 LLM）
python main.py --sheets

# 3. 全量生成：上述三个 + LLM 恢复预案
python main.py --full
```

## 配置 Excel 列名映射

首次使用前需创建 `config.yaml`（可参考 `config.example.yaml` 模板），并根据实际 Excel 文件的列名修改映射关系。

### 配置结构

```yaml
excel:
  file_path: "data/input.xlsx"
  id_separator: ","        # 多值 ID 的分隔符
  skip_empty_rows: true    # 跳过空行

  sheets:
    fault_phenomenon:                          # Sheet1: 故障现象场景清单
      sheet_name: "故障现象场景清单模版"         # Excel 中的 Sheet 标签名
      id_column: "编号"                        # 编号列名 (UPxxx/APxxx)
      name_column: "故障现象"                  # 现象名称列名
      description_column: "现象描述"           # 描述列名
      diagnostic_ref_column: "定界方法"        # 引用定界手段ID的列名（多个ID用逗号分隔）
      category_column: "分类"                  # 故障分类
      perception_method_column: "故障感知手段"  # 感知手段
      has_perception_column: "是否已有感知手段" # 是否已有感知手段

    diagnostic_method:                         # Sheet2: 定界手段模板
      sheet_name: "定界手段模板"
      id_column: "编号"                        # 编号列名 (Axxxx)
      name_column: "定界方法名称"
      steps_column: "详细定界方法"
      recovery_ref_column: "恢复方案建议"       # 引用恢复方案ID的列名
      tool_column: "定界工具"                  # 定界使用的工具/平台
      result_column: "定界结果"                # 定界结果描述

    recovery_plan:                             # Sheet3: 恢复方案模板
      sheet_name: "恢复方案模板"
      id_column: "编号"                        # 编号列名 (QRxxxx/Rxxxx)
      name_column: "应对方案名"
      steps_column: "方案概述"
      tool_column: "恢复工具"                  # 恢复使用的工具/平台
```

### 配置要点

1. **Sheet 标签名** (`sheet_name`)：必须与 Excel 底部的标签页名称完全一致
2. **列名映射** (`*_column`)：必须与 Excel 表头行的文字完全一致
3. **多值 ID 列** (`diagnostic_ref_column`、`recovery_ref_column`)：支持在一个单元格中用逗号分隔多个 ID（如 `A0001,A0002`）
4. **列名自动检测**：如果精确匹配失败，程序会尝试模糊匹配（如含 "编号"、"描述"、"步骤" 等关键词），匹配结果会输出警告日志

### 示例 Excel 结构

**Sheet1 — 故障现象场景清单模版：**

| 编号 | 故障现象 | 现象描述 | 定界方法 | 分类 | 故障感知手段 | 是否已有感知手段 |
|------|---------|---------|---------|------|------------|----------------|
| UP001 | 核心网连接超时 | UE无法附着到核心网 | A0001,A0002 | 核心网 | 告警监控 | 是 |

**Sheet2 — 定界手段模板：**

| 编号 | 定界方法名称 | 详细定界方法 | 恢复方案建议 | 定界工具 | 定界结果 |
|------|------------|------------|------------|---------|---------|
| A0001 | MME信令追踪 | 1. 登录MME... | QR0001 | Wireshark | 定界完成 |

**Sheet3 — 恢复方案模板：**

| 编号 | 应对方案名 | 方案概述 | 恢复工具 |
|------|----------|---------|---------|
| QR0001 | MME进程重启 | 1. 确认影响... | OSS平台 |

## 配置 LLM

支持两种 LLM 后端：**Ollama**（默认）和 **OpenAI 兼容 API**，通过 `provider` 字段切换。

### Ollama 模式（默认）

```yaml
llm:
  provider: ollama                      # 后端类型：ollama 或 openai
  base_url: "http://localhost:11434"    # Ollama 服务地址
  model: "qwen2.5:7b"                  # 模型名称
  timeout_seconds: 300
  max_retries: 3
  retry_delay_seconds: 5
  concurrency: 1
  temperature: 0.3
  stream: false
  generate_missing_suggestions: true
```

### OpenAI 兼容模式

适用于 OpenAI、DeepSeek、通义千问等任何兼容 OpenAI Chat Completions API 的服务：

```yaml
llm:
  provider: openai                          # 切换为 OpenAI 后端
  base_url: "https://api.openai.com/v1"    # API 地址（可替换为兼容服务的地址）
  api_key: "sk-xxx"                         # API Key
  model: "gpt-4"                            # 模型名称
  timeout_seconds: 300
  max_retries: 3
  retry_delay_seconds: 5
  temperature: 0.3
```

常用兼容服务的 `base_url` 示例：
- DeepSeek：`https://api.deepseek.com/v1`
- 通义千问（DashScope）：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- 本地 Ollama（OpenAI 兼容模式）：`http://localhost:11434/v1`

也可以通过修改 `config.yaml` 切换配置：

```yaml
llm:
  model: "qwen2.5:3b"

excel:
  file_path: "data/my_data.xlsx"

output:
  directory: "result/"
```

## LLM 参考建议（缺失数据）

当故障现象没有对应的定界手段或恢复方案时（外键关联缺失），程序会指示 LLM 在生成的 Markdown 文档末尾添加参考建议。

建议内容以专门的章节呈现：

```markdown
## 参考建议（LLM 生成）

> [!NOTE]
> 以下为 LLM 参考建议，请根据实际情况调整。

### 定界手段建议
...
### 恢复方案建议
...
```

通过 `config.yaml` 中的 `generate_missing_suggestions` 控制此功能（默认开启）。设置为 `false` 可关闭。

## 命令行参数

程序支持两种互斥的运行模式：

| 参数 | 说明 |
|------|------|
| `--sheets` | 生成故障现象、定界手段、恢复方案 Markdown（不需要 LLM） |
| `--full` | 全量生成：故障现象、定界手段、恢复方案 + LLM 恢复预案 |

所有配置（Excel 路径、LLM 模型、输出目录等）均在 `config.yaml` 中设置。

## 输出

生成的 Markdown 文件存放在 `output/` 目录，文件名格式为 `{故障ID}_{现象名称}.md`。

程序还会生成 `index.md` 索引文件，汇总所有生成结果。

### 按 Sheet 行生成独立 Markdown（`--sheets`）

使用 `--sheets` 可直接从 Excel 每个 Sheet 的每一行生成独立的 Markdown 文件，**不需要 LLM 服务**：

```bash
python main.py --sheets
```

输出目录结构：

```
result/
  故障现象/
    UP0001_页面大量接口报错.md
    AP0002_MQS消息重复.md
  定界手段/
    A0001_排查关键依赖平台是否异常.md
    A0002_排查数据库CPU使用率是否异常.md
    ...
  恢复方案/
    R0001_联系关键依赖平台支持人员协助处理.md
    QR0002_数据库CPU异常恢复方案.md
    ...
```

每个文件的标题格式为 `{编号}-{名称}`，内容包含该行数据的所有字段。多次运行采用增量覆盖策略（已有文件会被覆盖，未涉及的文件不会被删除）。
