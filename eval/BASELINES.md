# 隔离基线与分阶段重放

`baseline.py` 不调用本机正在运行的工作台，不修改其数据库。样本、数据库、原始模型输出与指标全部放在被 Git 忽略的 `data/` 中。

## 留存改前状态

```bash
.venv/bin/python eval/baseline.py capture \
  --code . --output data/baselines/新的实验目录
```

保留 SQLite 一致性备份、当前提交的源码归档和提交身份。若工作区有未提交改动，请先明确要比较的源码快照；`capture` 的代码归档来自 HEAD，而数据库来自当前运行状态。

本次改动的快照：`data/baselines/20261027/180120-e463db5/`。它还包含当前所有版本的 `existing-version-metrics.json`、不含密钥的连接身份、三份私有原文及其来源说明。该目录不上传 GitHub。

## 跑完整旧版基线

样本清单为 JSON 数组，每项至少包含 `id`、`title`、`text_path`，可附 `genre_tags` 和来源说明。只填写原文；不要把已有模型续写补进原文凑字数。

```bash
.venv/bin/python eval/baseline.py run \
  --code data/baselines/20261027/180120-e463db5/source \
  --samples data/baselines/20261027/180120-e463db5/samples.json \
  --output data/baselines/20261027/180120-e463db5/old-full \
  --env-file .env --target-words 20000
```

工具以 `baseline-eval` 身份自动推进方向和大纲卡点，生成到待审阅即停止，不自动提交或代替编辑验收。失败会保留节点、错误、已有产物与指标。`--mode demo` 仅用于验证工具本身，不作为文学质量数据。

## 比较单条改动

先固定父实验，然后只改一项再运行。父实验中已有的方向、大纲、细纲可以复用，避免无关的模型随机性和重复调用。

```bash
.venv/bin/python eval/baseline.py run \
  --code . \
  --samples data/baselines/20261027/180120-e463db5/samples.json \
  --output data/experiments/rewrite-only \
  --env-file .env \
  --reuse-from data/baselines/20261027/180120-e463db5/old-full \
  --from-stage write
```

`--from-stage` 支持：

- `directions`：复用原文和档案，从方向生成重新运行。
- `outline`：复用父实验选定方向，重新生成大纲及后续。
- `plans`：复用父实验方向与大纲，从细纲开始。
- `write`：复用父实验方向、大纲、细纲和原文后的初始档案，从正文写作开始。

父实验对应阶段未产出时，局部重放会明确报错，不编造缺失产物。源数据库会复制到新目录；父实验本身不变。每次比较使用新输出目录，已有运行数据库不会被覆盖。

```bash
.venv/bin/python eval/baseline.py compare \
  data/baselines/20261027/180120-e463db5/old-full/results.json \
  data/experiments/rewrite-only/results.json \
  --output data/experiments/rewrite-only/comparison.json
```

比较记录原文哈希、代码哈希、模型参数、状态、首稿通过率、规则问题、重写次数，以及每个节点的调用、token 和耗时。完整流程与局部重放的总成本不直接相减，只按对应节点比较。合并多项改动的比较只能说明总体效果，不能归因到某一项改动；不同模型抽样仍可能带来波动。


N1 单节点检查使用 `run --stage understand`，不自动调用方向生成，也不创建续写版本。
`--model-settings-from 旧实验/identity.json` 可固定旧实验的模型路由和生成参数；密钥仍从本机 `.env` 读取。

只比较方向生成/批量打分或细纲节点，可使用 `replay_nodes.py --stage directions|plans`。
该工具需要父数据库的 `--project-id`；细纲另需 `--version-id`。它复制父数据库后仅调用指定节点，
固定已有 bible / outline，不继续写正文，输出实际调用与 token 差异以及输入材料哈希。
