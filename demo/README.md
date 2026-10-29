# 续写 Agent 生成段演示

跑通 S1 原文理解 → S2 方向 → 编辑介入① → S3 大纲 → S4 细纲 → 编辑介入② → S5a 伏笔回填 → S5b 正文，每个阶段的输入、prompt、输出和代码检查都存下来，最后生成一个展示页面。

只依赖 Python 3.9+ 标准库，不需要装包。

## 运行

1. 在本目录的 `.env` 里填写（已被 git 忽略，不要提交）：

   ```
   OPENROUTER_API_KEY=sk-or-...
   MODEL=deepseek/deepseek-v4.1-flash
   # 可选：按阶段换模型，例如 MODEL_S5B=anthropic/claude-sonnet-4.5
   # 可选：推理模型的思考预算（默认 8000），思考 token 不挤占正式输出
   # LLM_REASONING_TOKENS=8000
   ```

2. 跑流水线（约 25 次模型调用，正文 20 章）：

   ```bash
   python3 run.py "../../测试小说_TXT合集/01_穿成全网群嘲明星，看我大心脏力挽狂澜.txt" --out output/01_明星
   ```

   常用参数：

   | 参数 | 作用 |
   |---|---|
   | `--target 20000` | 续写目标字数 |
   | `--free 4` | 免费章数，伏笔只能补在这之后 |
   | `--direction steady` | 演示中编辑介入①自动选的方向：steady / deepen / alternate |
   | `--note "……"` | 编辑补充要求，会传给方向和大纲 |
   | `--max-chapters 3` | 正文只写前 3 章，先快速看效果 |
   | `--start s3` | 从某个阶段起重跑（之前的结果保留） |
   | `--only s2` | 只重跑某个阶段 |

   已有结果的阶段会自动跳过，中断后重跑会接着写。

3. 生成展示页面：

   ```bash
   python3 build_viewer.py output/01_明星
   ```

   用浏览器打开 `output/01_明星/demo.html`。

## 工作台

```bash
python3 workbench.py
```

浏览器打开 http://127.0.0.1:8765。流程：

1. **上传**：选 TXT，看解析出的章节，点「开始分析」。原文理解和三个方向在后台生成，不展示给用户。
2. **选方向**：三个方向里选一个；或写一句想法（自定义，AI 补成完整方向）；或「让 AI 选」。确认后大纲在后台生成，不需要确认。
3. **细纲**：逐章可改（标题、核心冲突、事件、章尾），确认后先补伏笔，再开始写正文。
4. **正文**：一章接一章连续写，可随时停止、继续。每章写完由代码查和前文原样重复的句子、用滥的口头禅（`run.py` 的 `TICS`）、超字数，结果显示在右栏；左栏开关打开时，检查没通过会自动按检查结果改一次（直出稿留在 `draft`），默认关闭即直出。每章还可手改、按意见修改（可恢复修改前）、整章重写，或做**多模型对比**：2～4 个模型用同样的前文和细纲同时写这一章，并排显示（标出重复句和口头禅），选一版「采用」（原版本可恢复），候选稿存在 `s5b_compare/chNN/`。全部写完后「确认全文，导出」下载成稿。

每一步都是三栏：左边参数和输入，中间 AI 输出（可编辑），右边检查结果和确认。左栏「各阶段模型」可以按阶段换 OpenRouter 上的模型，留空用 `.env` 的 `MODEL`。

项目存在 `output/wb_<编号>/`，文件结构与 `run.py` 输出一致，`build_viewer.py` 也能直接用。重做前面的步骤会清掉后面的结果。

## 文件

| 文件 | 内容 |
|---|---|
| `prompts/s1_understand.md` … `s5b_write.md` | 各阶段 prompt，头部有版本号和温度 |
| `run.py` | 流水线、代码检查 |
| `workbench.py`、`workbench.html` | 工作台（本地服务 + 页面） |
| `prompts/s2_custom.md`、`s2_select.md` | 工作台用：自定义方向、自动选方向 |
| `prompts/s5c_revise.md` | 正文按意见修改（自动修改也用它） |
| `moves/<情感基调>.json` | 招式库：方向由「对手、交锋方式、反转、结局」组合，选项从这里取 |
| `breakdown.py`、`prompts/x_breakdown.md` | 拆书：从成稿里拆出四类招式，结果在 `output/breakdown/` |
| `build_viewer.py`、`viewer_template.html` | 展示页面 |
| `output/<书名>/` | 每个阶段一个 JSON；`s5b/` 逐章正文；`manuscript.txt` 成稿 |

输出里含有版权原文，只放本地，不进公开仓库。
