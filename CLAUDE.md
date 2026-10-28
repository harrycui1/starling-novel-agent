# Starling 网文续写 Agent

编辑工作台：输入一篇约 1 万字、已写完结局的短篇，保留前约 80%，从切点起续写约 2 万字。编辑在方向、大纲、正文三处介入。

## 当前状态

- 工作分支：`codex/full-text-workflow`。`main` 是第一版（故事档案 + 逐章阻断审核），`fix/continuation-review-and-planning` 是在它上面继续加机制的分支，两者都只作历史记录，不合并、不在上面开发。
- 已证明：流程能稳定跑完 8 章，正常 12 次调用。
- 未证明：写得好。编辑盲评（4 本书 × 2 版本）结论是不能用。
- 三个根因，都还没修：没有切点（从原文结尾直接接）、类型跑偏（爽文写成成长文）、单章太长（写死 2500 字，原文约 1000 字）。
- 方向节点的新策略（原文理解 → 三条续写路线）已定方案，提示词草案在 `docs/提示词草案/`，尚未接入代码。
- 产品讨论与决策记录：2026-10-28 起在 `docs/讨论记录/`；更早的一份在仓库外 `../【讨论记录】网文续写：从技术方案到编辑反馈.md`。改流程前先读最新一份。

## 产品原则

所有改动都要能回到这几条。和这几条冲突的需求，先改这一节，再改代码。

1. 续写，不是扩写。切点之前的原文是既成事实，不改。
2. 类型不能变。「爽」按书定义（打脸、追悔、甜宠……），由原文理解产出的类型契约约束。
3. 切点必须落在「门关上」（故事宣告尘埃落定）之前。切点属于每个方向，不是整本书只有一个。
4. 不丢：切点之后被删掉的原作高光（爽点、情感、反转都算），在新稿里只能保留或加码，可以挪位置。
5. 新高：续写的终局高光至少与原作最强高光持平，目标是超过。（持平是否达标，待定）
6. 2 万字靠第二个冲突撑起来，冲突必须来自原作的剩余势能，不拖着原矛盾写。
7. 形式贴近原作：章长、对话占比、章尾落在事件上，三项都用代码对照原文量化。
8. 若非必要，勿增实体。故事档案、多方向打分、逐章自动重写先不做，等编辑反馈证明需要再加。
9. 质量结论只来自编辑评价。"跑通了""token 下降了"不等于"写得更好"，文档和提交说明里不得这样写。

## 架构

FastAPI + SQLModel + SQLite + Alembic；前端 Vite + React + antd，单文件 `frontend/src/main.tsx`。

流水线：`app/pipeline/runner.py` 是状态机，按 `current_node` 执行节点；状态进入 `STOPS` 时停下，等编辑操作。

| 节点 | 文件 | 作用 | 调用次数 |
|---|---|---|---|
| N1 | `nodes/n1_understand.py` | 读全文，产出 `SourceSummary`，存 `SourceUnderstanding` | 1 |
| N2 | `nodes/n2_directions.py` | 生成 3 个方向 → 编辑选择 | 1 |
| N3 | `nodes/n3_select.py` | 只在编辑手写方向时整理方向卡 → 编辑确认 | 0–1 |
| N4 | `nodes/n4_outline.py` | 一次生成大纲 + 逐章细纲，`allocate_words` 均分字数 → 编辑确认 | 1 |
| N6 | `nodes/n6_write.py` | 逐章写作，输入全部原文 + 全部已写前章 | 每章 1 |
| N7 | `nodes/n7_review.py` | 全文审核，按章批注，不拦截、不自动重写 | 1 |

- 上下文拼装都在 `app/pipeline/context.py`（`source_context` / `manuscript_context` / `build_write_context`）。改"模型看到什么原文"只改这里，不在节点里各自拼。
- 模型调用：`app/llm/gateway.py`，按 prompt 头部的 `model_role` 路由到 `.env` 里的连接；`app/llm/structured.py` 负责 JSON 解析、修复和带错误重试。
- 代码规则：`app/checks/__init__.py`，只出提示（`verdict: info`），不做门禁。
- 旧表（`StoryBibleSnapshot`、`ChapterPlanRow` 等）保留用于读历史，不再写入，也不要恢复使用。

## 约定

- **Prompt**：`app/prompts/<节点>_<用途>.md`，YAML 头含 `name`、`version`、`model_role`、`output`。改任何 prompt 内容都必须更新 `version`（格式 `YYYY-MM-DD.<分支标签>.<序号>`），否则 `LLMCall.prompt_version` 无法区分实验。
- **Schema**：`app/schemas.py` 一律 `extra="forbid"`。新增字段给默认值，保证旧数据能读。
- **数据库**：表结构变化只通过新的 Alembic 迁移（`alembic/versions/000N_*.py`），不改已有迁移。优先用 JSON 字段加键，不加新表。
- **字数**：按非空白字符计，含标点，用 `checks.count_words`。
- **Demo 模式**：`NOVEL_MODE=demo` 走 `app/llm/demo.py` 的固定输出。新增或改动 prompt 的输入输出时同步更新 demo，否则测试会挂。
- **代码风格**：跟随现有代码，函数短、注释少，只在不显然的地方写一行英文注释。用户可见文本用中文。
- **文档**：当前实现写在 `docs/全文精简流程.md`，实测写在 `docs/精简流程实测.md`；`docs/技术设计.md`、`docs/首版验收.md` 是历史记录，不更新。改流程时同步改 `docs/全文精简流程.md` 和本文件。
- **讨论记录**：`docs/讨论记录/YYYY-MM-DD-<主题>.md`，每次讨论一份，只新建不改写。结论变化时写新记录，并写明推翻了哪条旧结论；定下的产品原则同步到本文件「产品原则」。
- **提示词草案**：`docs/提示词草案/<主题>.md`，接入代码前在这里迭代；接入后以 `app/prompts/` 为准，草案注明已接入的版本号。
- **公开仓库**：本仓库在 GitHub 上公开。讨论记录和草案里不写内部链接、编辑评分明细、内部产品对比和原文段落；原文情节只写概括。

## 验证

改完必须跑：

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
.venv/bin/python -m alembic check
```

首次运行先 `./start.sh`（会建 `.venv`、装依赖、构建前端）。测试用 demo 模式和临时数据库，不访问真实模型，也不代表文学质量。

环境坑：

- `alembic check` 要求本地数据库已在最新版本；新环境先跑 `.venv/bin/python -m alembic upgrade head`（`data/novel.db` 不存在时会自动创建）。
- `frontend/package-lock.json` 的下载地址是公司内网镜像 `bnpm.byted.org`。不在内网时 `npm ci` 会报 ECONNRESET 或 "Exit handler never called"，用 `npm --prefix frontend ci --replace-registry-host=bnpm.byted.org` 改走公共源安装，不要改 lockfile。

改 prompt 或流程后的质量验证：

1. 代码初筛：章长、对话占比、段落平均长度、章尾类型，与原文对照。
2. 真实样本跑通：`eval/run_workflow.py`，结果放在 `data/comparison/<实验名>/`。
3. 编辑盲评：同一本书的所有版本用同一个切点，由同一位编辑看完。

前两步只能筛掉明显不合格的稿子，只有第 3 步能说明质量。

## 数据与密钥

- `.env`、`data/` 已被 git 忽略。原文、稿件、模型原始输出、评测结果都在 `data/` 下，不提交、不贴进文档。
- 模型名和接口地址不写死在代码里，只放在 `.env`。

## Git 协作

- 每个对话使用独立的 git worktree，从 `codex/full-text-workflow` 切新分支开发代码。只改文档（讨论记录、草案、本文件）时可以直接提交到 `codex/full-text-workflow`。
- 跨 worktree、跨对话的交接通过 commit 完成。commit message 用英文，标题写变更意图；正文写三件事：
  - 改了什么、为什么；
  - 跑了哪些验证、结果如何；
  - 还没做或没验证的部分。
- 不自动 `git push`，push 只用于跨设备同步，等用户明确指示。
