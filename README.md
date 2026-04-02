# Excel to Markdown Wiki 自动化工具

将多张关联的 Excel 工作表（故障现象、定界手段、恢复方案）自动转换为标准化的 Markdown 运维预案文件。通过解析 Excel 外键关联，调用 LLM 生成结构化文档。

## 数据流

```
Excel (.xlsx)
  ├── Sheet1: 故障现象场景清单 (ID: UPxxx/APxxx)
  ├── Sheet2: 定界手段模板     (ID: Axxxx)
  └── Sheet3: 恢复方案模板     (ID: QRxxxx/Rxxxx)

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
- `requests` — LLM API 调用
- `pyyaml` — 配置文件解析

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
# 生成默认配置文件
python main.py --init

# 用示例数据验证解析逻辑（不需要 LLM）
python main.py --sample --dry-run

# 检查 LLM 服务是否可用
python main.py --check

# 用示例数据端到端生成 Markdown
python main.py --sample
```

## 配置 Excel 列名映射

运行 `python main.py --init` 会生成 `config.yaml`。你需要根据实际 Excel 文件的列名修改映射关系。

### 配置结构

```yaml
excel:
  file_path: "data/input.xlsx"
  id_separator: ","        # 多值 ID 的分隔符
  skip_empty_rows: true    # 跳过空行

  sheets:
    fault_phenomenon:                    # Sheet1: 故障现象场景清单
      sheet_name: "故障现象场景清单"       # Excel 中的 Sheet 标签名
      id_column: "故障ID"                # 故障ID 列名 (UPxxx/APxxx)
      name_column: "故障现象"            # 现象名称列名
      description_column: "描述"         # 描述列名
      diagnostic_ref_column: "定界手段ID" # 引用定界手段ID的列名（多个ID用逗号分隔）

    diagnostic_method:                   # Sheet2: 定界手段模板
      sheet_name: "定界手段模板"
      id_column: "定界ID"                # 定界ID 列名 (Axxxx)
      name_column: "定界手段"
      description_column: "描述"
      steps_column: "步骤"
      recovery_ref_column: "恢复方案ID"   # 引用恢复方案ID的列名

    recovery_plan:                       # Sheet3: 恢复方案模板
      sheet_name: "恢复方案模板"
      id_column: "方案ID"                # 方案ID 列名 (QRxxxx/Rxxxx)
      name_column: "恢复方案"
      type_column: "类型"                # 区分快恢/恢复
      steps_column: "执行步骤"
      description_column: "描述"
```

### 配置要点

1. **Sheet 标签名** (`sheet_name`)：必须与 Excel 底部的标签页名称完全一致
2. **列名映射** (`*_column`)：必须与 Excel 表头行的文字完全一致
3. **多值 ID 列** (`diagnostic_ref_column`、`recovery_ref_column`)：支持在一个单元格中用逗号分隔多个 ID（如 `A0001,A0002`）
4. **列名自动检测**：如果精确匹配失败，程序会尝试模糊匹配（如含 "ID"、"描述"、"步骤" 等关键词），匹配结果会输出警告日志

### 示例 Excel 结构

**Sheet1 — 故障现象场景清单：**

| 故障ID | 故障现象 | 描述 | 定界手段ID |
|--------|---------|------|-----------|
| UP001 | 核心网连接超时 | UE无法附着到核心网 | A0001,A0002 |

**Sheet2 — 定界手段模板：**

| 定界ID | 定界手段 | 描述 | 步骤 | 恢复方案ID |
|--------|---------|------|------|-----------|
| A0001 | MME信令追踪 | 分析MME附着流程 | 1. 登录MME... | QR0001 |

**Sheet3 — 恢复方案模板：**

| 方案ID | 恢复方案 | 类型 | 执行步骤 | 描述 |
|--------|---------|------|---------|------|
| QR0001 | MME进程重启 | 快恢 | 1. 确认影响... | 快速恢复MME服务 |

## 配置 LLM

```yaml
llm:
  base_url: "http://localhost:11434"  # Ollama 服务地址
  model: "qwen2.5:7b"                 # 模型名称
  timeout_seconds: 300                 # 单次请求超时（秒）
  max_retries: 3                       # 失败重试次数
  retry_delay_seconds: 5               # 重试间隔基数（指数退避）
  concurrency: 1                       # 并发数（本地 Ollama 建议 1）
  temperature: 0.3                     # 生成温度
  stream: false                        # 是否流式输出
```

也可以通过命令行覆盖：

```bash
python main.py --model qwen2.5:3b --excel data/my_data.xlsx --output result/
```

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--config PATH` | 配置文件路径（默认 `./config.yaml`） |
| `--excel PATH` | Excel 文件路径（覆盖配置） |
| `--output DIR` | 输出目录（覆盖配置） |
| `--model NAME` | LLM 模型名称（覆盖配置） |
| `--concurrency N` | 并发数 |
| `--init` | 生成默认配置文件并退出 |
| `--check` | 检查 LLM 服务可用性并退出 |
| `--dry-run` | 仅解析 Excel，不调用 LLM |
| `--sample` | 使用内置示例数据 |
| `-v, --verbose` | 详细日志输出 |

## 输出

生成的 Markdown 文件存放在 `output/` 目录，文件名格式为 `{故障ID}_{现象名称}.md`。

程序还会生成 `index.md` 索引文件，汇总所有生成结果。
