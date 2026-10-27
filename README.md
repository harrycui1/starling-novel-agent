# Starling 网文续写工作台

导入约一万字开头，编辑选择续写方向、确认大纲，生成约两万字续写，再查看批注、修改和导出。

## 启动

```bash
./start.sh
```

打开 <http://127.0.0.1:8767>。首次运行需 Python 3.11+、uv 和 Node.js；复制 `.env.example` 为 `.env` 并配置模型。启动脚本构建前端并执行 Alembic 迁移。使用单个服务进程，不要设置多个 uvicorn worker。

正文和操作保存在 `data/novel.db`，模型原始输出保存在 `data/raw/`。`.env`、本地数据和构建产物不提交。关闭后重新启动，未完成任务显示“运行中断”，点击继续会复用已保存章节。

## 当前流程

1. 一次读完原文，输出给编辑看的梗概、人物表和原文结束处境。
2. 一次生成三个主套路不同的方向，明确从原文结尾哪里接起。支持选择、修改、换批和手动方向；保留候选、理由和修改前后的操作记录。手动方向整理后由编辑再次确认。
3. 一次合并生成大纲和逐章细纲。每章可编辑事件、爽点、停止点与目标字数，确认后才写作。
4. 逐章写作，每章输入完整原文、已完成的全部前章、确认的大纲与本章要求；不裁剪前文、不维护故事档案、不自动重写。
5. 全文写完后一次审核，按章显示批注。字数、禁用结尾和高频表达检查也只是提示。审核错误会显示“批注暂不可用”，正文保留；可重新审核或继续编辑、提交。

默认目标为续写 20,000 字、8 章，正常路径为 **12 次模型调用**：理解 1 + 方向 1 + 大纲 1 + 写作 8 + 审核 1。网络/结构重试、换批、手动方向和编辑要求的重写会增加调用。字数按非空白字符计算，包含标点；模型输出不足只提示，不自动补写。

保留一份原文多个版本、逐章修订历史、带意见重写、改稿后后章衔接提醒、SSE 进度、TXT / Word 导出。审核严重度和衔接提醒不阻止提交，由编辑决定。

跨电脑继续开发或迁移稿件，按 [跨电脑接力](docs/跨电脑接力.md) 操作。

## 模型配置

`NOVEL_CONNECTIONS` 配置命名连接，`NOVEL_MODELS` 把 extractor / planner / writer / judge 路由到连接；支持 Chat Completions、Responses、ModelHub，接口地址填写完整 URL。连接 `parameters` 原样传给服务。模型需要容纳完整原文、续写和大纲；服务容量不足时不会偷偷截断前文。

调用记录保留实际模型、提示词版本、token、耗时和原始输出。不配置单价，不估算金额。`NOVEL_MODE=demo` 使用固定演示数据，页面和导出均明确标识；默认使用真实模型。

## 开发与验证

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
.venv/bin/python -m alembic check
```

测试使用独立临时数据库，不访问真实模型。覆盖默认12次调用、完整上下文、方向操作、确认大纲、持久化后故障恢复、非阻断审核、编辑重写与导出。前端可用 `npm --prefix frontend run dev`，位于 <http://127.0.0.1:5187>，API 转发到8767。

记录一次真实流程实验（独立数据库，不自动提交；由评测驱动选择首个方向并确认大纲，不表示编辑认可）：

```bash
.venv/bin/python eval/run_workflow.py --samples samples.json --output data/experiments/run-1 --env-file .env --target-words 20000
```

`samples.json` 为 `[{"id":"sample-1","title":"作品名","text_path":"原文.txt","genre_tags":[]}]`，路径相对该清单。输出包括输入哈希、模型参数、调用明细、梗概、方向、大纲、全文、续写和批注。已有实验数据库拒绝覆盖。

单版本指标和两个快照的差异：

```bash
.venv/bin/python eval/run_eval.py --version-id 1 --output data/eval/current.json
.venv/bin/python eval/run_eval.py --compare data/eval/before.json data/eval/after.json
```

成本比较须使用相同原文、目标字数和模型参数；审核建议不等于人工质量评分。需请编辑盲看旧、新流程稿件，比较一致性、爽点和可提交程度。

当前设计与验收见 [全文精简流程](docs/全文精简流程.md)，三份真实样本的调用、篇幅及对照边界见 [精简流程实测](docs/精简流程实测.md)。[原技术设计](docs/技术设计.md) 和 [首版验收](docs/首版验收.md) 保留为历史记录。生产身份权限、外部任务队列、长期质量验收和部署配置仍待单独建设。
