# Starling 网文续写工作台

独立的本地首版：导入原文 → 理解人物与伏笔 → 比较三个方向 → 编辑确认大纲 → 逐章续写和审核 → 人工审阅、修改、导出。

## 启动

本机已配置模型连接，直接运行：

```bash
./start.sh
```

打开 <http://127.0.0.1:8767>。启动脚本构建前端、应用 Alembic 迁移，再启动后端。数据保存在 `data/novel.db`，模型原始输出在 `data/raw/`。关闭后重新启动，未完成任务会显示“运行中断”，点击“从中断处继续”即可恢复。

首次在其他电脑运行需要 Python 3.11+、uv 和 Node.js。复制 `.env.example` 为 `.env`，填写自己的模型连接与密钥。`.env` 和数据目录均被忽略，不要提交凭据。

## 当前可用

- 粘贴正文，或上传 UTF-8 / GB18030 TXT、Markdown、DOCX；自动切章。
- StoryBible、逐章摘要、文风统计、原文证据核对；未核对成功的引用明确提示。
- 生成八个方向，按评审和差异化规则展示三个；支持选择、修改、手动输入、自动选择、换一批。手动方向整理后另需确认。
- 按目标字数计算章节数；可编辑章节内容、功能、爽点、结尾与新增人物；确认大纲后才能开始写作。
- 逐章细纲、写作、规则检查、模型审核、最多两次自动重写、档案增量更新；每一步产物落库。
- 失败节点重跑；正文已保存而档案更新失败时复用原稿；快照按正文修订链核对，避免改稿后误用旧状态。
- 逐章编辑和带意见重写、原稿/修订对照、后续章节衔接提醒；有审核问题的稿件须由编辑确认后才能提交。
- 一份原文可创建多个续写版本；持久化编辑记录、模型调用与提示词版本、SSE 进度；TXT / Word 导出。

默认续写目标 20,000 字、约 8 章，可在选方向前调整字数。字数按非空白字符计，包含标点。

## 模型配置

`.env` 的 `NOVEL_CONNECTIONS` 是命名连接，`NOVEL_MODELS` 为 extractor / planner / writer / judge 分配连接。接口地址使用完整 URL。支持 Chat Completions、Responses 和本机已有的 ModelHub 协议。模型名不写死在代码里。命名连接的 `parameters` 可传入服务支持的生成参数；本机连接设置为 `{"reasoning":{"effort":"low"}}`。可按角色配置不同连接和参数，具体支持范围见 [OpenRouter 推理参数文档](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)。

本机连接来自已有 NovelForge 配置，当前四种角色共用同一个模型。需要独立审核时，增加另一个连接并修改 `judge` 路由。网关保存实际 token 用量和耗时，不推算未经配置的金额。

`NOVEL_MODE=demo` 为固定样例演示，页面和导出均明确标识；演示样例为 `examples/雨夜账册.txt`。默认始终为真实模型模式。

## 开发与精简验证

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
.venv/bin/python -m alembic check
```

只保留一条集成冒烟测试，覆盖真实数据库/API、编辑卡点、JSON 修复和重试、持久化后故障恢复、改稿衔接提醒、提交和两种导出。测试不访问真实模型，也不替代文学质量评审。

前端单独开发：`npm --prefix frontend run dev`，页面位于 `http://127.0.0.1:5187`，API 转发到 8767。

生成一份运行指标快照，或比较两次提示词实验：

```bash
.venv/bin/python eval/run_eval.py --version-id 1 --output data/eval/current.json
.venv/bin/python eval/run_eval.py --compare data/eval/before.json data/eval/after.json
```

指标包括一致性问题密度、首稿通过率、规则问题率、平均重写次数、方向相似度、套路分布熵、token 和耗时，以及实际提示词版本。比较实验应使用相同原文、目标字数和模型；20 篇真实评测集和人工校准尚未完成。

## 交付边界

这是可运行的本地编辑首版，使用单个服务进程；不要设置多个 uvicorn worker。生产部署仍需用户身份与权限、外部任务队列、真实长篇质量验收和部署配置。当前无生产账户或上线数据接入。

人名检查采用分词和白名单，可能误报，称谓与限知视角依靠模型审核及人工确认。未启用完整关系推断或事实图谱。上下文按字符保守估算 token，超预算会提示调整，不静默截断上一章和本章细纲。

实施状态与原始方案见 [技术设计](docs/技术设计.md)，验收证据见 [首版验收](docs/首版验收.md)。原始输入文档保留不变。
