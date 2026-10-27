import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Alert,
  Button,
  Card,
  ConfigProvider,
  Empty,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Spin,
  Steps,
  Tabs,
  Tag,
  message,
} from "antd";
import zhCN from "antd/es/locale/zh_CN";
import {
  BookOutlined,
  PlusOutlined,
  ArrowRightOutlined,
  CheckOutlined,
  ReloadOutlined,
  DownloadOutlined,
  EditOutlined,
} from "@ant-design/icons";
import "antd/dist/antd.css";
import "./style.css";

type Json = Record<string, any>;
const labels: Record<string, string> = {
  created: "排队中",
  queued: "排队中",
  understanding: "正在理解原文",
  generating_directions: "正在构思方向",
  awaiting_direction: "选择续写方向",
  judging: "正在整理方向",
  awaiting_direction_confirmation: "确认你的方向",
  generating_outline: "正在生成大纲",
  awaiting_outline: "等待确认大纲",
  planning_chapters: "正在展开细纲",
  writing: "正在续写与审核",
  awaiting_review: "等待审阅",
  submitted: "已提交",
  failed: "运行中断",
  abandoned: "已放弃",
};
const active = new Set([
  "created",
  "queued",
  "understanding",
  "generating_directions",
  "judging",
  "generating_outline",
  "planning_chapters",
  "writing",
]);
async function api(path: string, method = "GET", body?: unknown) {
  const response = await fetch("/api" + path, {
    method,
    headers:
      body instanceof FormData ? {} : { "Content-Type": "application/json" },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      typeof error.detail === "string" ? error.detail : "请检查输入内容",
    );
  }
  return response.json();
}
function App() {
  const [health, setHealth] = useState<Json>({}),
    [projects, setProjects] = useState<Json[]>([]),
    [pid, setPid] = useState<number>(),
    [vid, setVid] = useState<number>();
  const [project, setProject] = useState<Json>(),
    [version, setVersion] = useState<Json>(),
    [page, setPage] = useState("upload"),
    [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false);
  const [title, setTitle] = useState(""),
    [text, setText] = useState(""),
    [tags, setTags] = useState(""),
    [file, setFile] = useState<File>(),
    [target, setTarget] = useState(20000);
  const [direction, setDirection] = useState<Json>(),
    [manual, setManual] = useState(false),
    [manualText, setManualText] = useState(""),
    [reason, setReason] = useState("");
  const [outline, setOutline] = useState<Json>(),
    [index, setIndex] = useState<number>(),
    [draftText, setDraftText] = useState(""),
    [edit, setEdit] = useState(false),
    [instruction, setInstruction] = useState(""),
    [rewrite, setRewrite] = useState(false);
  async function load() {
    setProjects(await api("/projects"));
    if (pid) setProject(await api(`/projects/${pid}`));
    if (vid) {
      const value = await api(`/versions/${vid}`);
      setVersion(value);
      if (!dirty) setOutline(value.outline?.data);
    }
  }
  useEffect(() => {
    api("/health")
      .then(setHealth)
      .catch((e) => message.error(e.message));
    api("/projects")
      .then(setProjects)
      .catch((e) => message.error(e.message));
  }, []);
  useEffect(() => {
    setDirty(false);
    setIndex(undefined);
    setEdit(false);
    setOutline(undefined);
    setVersion(undefined);
    if (vid)
      api(`/versions/${vid}`)
        .then((v) => {
          setVersion(v);
          setOutline(v.outline?.data);
        })
        .catch((e) => message.error(e.message));
  }, [vid]);
  useEffect(() => {
    if (pid)
      api(`/projects/${pid}`)
        .then(setProject)
        .catch((e) => message.error(e.message));
  }, [pid]);
  useEffect(() => {
    if (!pid) return;
    const stream = new EventSource(`/api/events?project_id=${pid}`);
    const refresh = () => {
      void load().catch(() => {});
    };
    stream.addEventListener("progress", refresh);
    const timer = window.setInterval(refresh, 5000);
    return () => {
      stream.close();
      window.clearInterval(timer);
    };
  }, [pid, vid, dirty]);
  const status = version?.version.status ?? project?.project.status,
    working = active.has(status);
  const chapters: Json[] = version?.chapters ?? [],
    current = chapters.find((d) => d.index === (index ?? chapters[0]?.index));
  const review = (version?.reviews ?? [])
    .filter((r: Json) => r.draft_id === current?.id)
    .at(-1);
  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    try {
      await work();
      await load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload() {
    await act(async () => {
      let p;
      if (file) {
        const form = new FormData();
        form.append("file", file);
        form.append("title", title);
        form.append("genre_tags", tags);
        p = await api("/projects/upload", "POST", form);
      } else
        p = await api("/projects", "POST", {
          title,
          text,
          genre_tags: tags.split(/[,，]/).filter(Boolean),
        });
      setPid(p.id);
      setVid(undefined);
      setVersion(undefined);
      setPage("directions");
      setProject(await api(`/projects/${p.id}`));
    });
  }
  async function choose(source: string, candidate?: Json, edited?: Json) {
    await act(async () => {
      const v = await api(`/projects/${pid}/versions`, "POST", {
        source,
        candidate_id: candidate?.id,
        direction: edited,
        manual_text: manualText,
        target_words: target,
        reason,
      });
      setVid(v.id);
      setDirection(undefined);
      setManual(false);
      setDirty(false);
      setPage("outline");
    });
  }
  function changeChapter(i: number, key: string, value: unknown) {
    if (!outline) return;
    setOutline({
      ...outline,
      chapters: outline.chapters.map((c: Json, j: number) =>
        i === j ? { ...c, [key]: value } : c,
      ),
    });
    setDirty(true);
  }
  function selectProject(p: Json) {
    setPid(p.id);
    setVid(undefined);
    setVersion(undefined);
    setPage("directions");
    setDirty(false);
  }
  const progress = version?.version.total_chapters
    ? Math.round((chapters.length / version.version.total_chapters) * 100)
    : 0;
  return (
    <ConfigProvider locale={zhCN}>
      <div className="shell">
        <aside>
          <div className="brand">
            <BookOutlined />
            <span>
              Starling<small>故事工坊</small>
            </span>
          </div>
          <Button
            block
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setPage("upload");
              setPid(undefined);
              setVid(undefined);
              setProject(undefined);
              setVersion(undefined);
              setTitle("");
              setText("");
              setFile(undefined);
            }}
          >
            新建续写
          </Button>
          <div className="aside-label">
            我的作品 <span>{projects.length}</span>
          </div>
          <nav>
            {projects.map((p) => (
              <button
                key={p.id}
                className={pid === p.id ? "selected" : ""}
                  aria-label={p.title}
                  title={p.title}
                onClick={() => selectProject(p)}
              >
                <BookOutlined />
                <span>
                  {p.title}
                  <small>
                    {labels[p.status]} · {p.source_word_count.toLocaleString()}{" "}
                    字
                  </small>
                </span>
              </button>
            ))}
          </nav>
          <div className="aside-foot">
            编辑确认 · 稳定续写
            <br />
            <small>原文理解 / 方向 / 大纲 / 正文</small>
          </div>
        </aside>
        <main>
          <header>
            <div>
              <span className="eyebrow">NOVEL CONTINUATION</span>
              <h1>{pid ? project?.project.title : "把故事，接着写下去"}</h1>
              <p>
                {pid
                  ? "让方向、节奏和人物始终在你的掌握中。"
                  : "从一个开头出发，找到值得读下去的故事。"}
              </p>
            </div>
            <Tag color={health.mode === "demo" ? "orange" : "green"}>
              {health.mode === "demo" ? "演示模式 · 固定数据" : "本机模型"}
            </Tag>
          </header>
          {health.mode === "demo" && (
            <Alert
              type="warning"
              showIcon
              message="演示模式：用于验证操作流程，内容由固定样例生成。"
            />
          )}
          {pid && (
            <>
              <Steps
                size="small"
                current={page === "directions" ? 1 : page === "outline" ? 2 : 3}
                items={[
                  { title: "导入原文" },
                  { title: "选择方向" },
                  { title: "确认大纲" },
                  { title: "审阅正文" },
                ]}
              />
              <div className="workspace-nav">
                <Space>
                  <Button
                    type={page === "directions" ? "primary" : "text"}
                    onClick={() => setPage("directions")}
                  >
                    原文与方向
                  </Button>
                  <Button
                    disabled={!vid}
                    type={page === "outline" ? "primary" : "text"}
                    onClick={() => setPage("outline")}
                  >
                    故事大纲
                  </Button>
                  <Button
                    disabled={!vid}
                    type={page === "review" ? "primary" : "text"}
                    onClick={() => setPage("review")}
                  >
                    正文审阅
                  </Button>
                </Space>
                <Tag
                  color={
                    status === "failed" ? "red" : working ? "blue" : "default"
                  }
                >
                  {labels[status] ?? status}
                </Tag>
              </div>
            </>
          )}
          {pid && project?.versions?.length > 0 && (
            <div className="versions">
              <span>续写版本</span>
              <Select
                placeholder="选择一个版本"
                value={vid}
                style={{ minWidth: 260 }}
                onChange={(v) => {
                  setVid(v);
                  setPage("outline");
                }}
                options={project?.versions.map((v: Json) => ({
                  value: v.id,
                  label: `版本 ${v.id} · ${v.direction.title ?? "整理手动方向"} · ${labels[v.status]}`,
                }))}
              />
              {vid && (
                <Button
                  type="text"
                  danger
                  disabled={
                    working || ["submitted", "abandoned"].includes(status)
                  }
                  onClick={() =>
                    Modal.confirm({
                      title: "放弃这个续写版本？",
                      content: "已生成的内容和历史会保留，仍可查看与导出。",
                      onOk: () =>
                        act(() => api(`/versions/${vid}/abandon`, "POST", {})),
                    })
                  }
                >
                  放弃此版本
                </Button>
              )}
            </div>
          )}
          {(version?.version.error || project?.project.error) && (
            <Alert
              type="error"
              showIcon
              message="运行中断，已完成的内容已保存"
              description={version?.version.error ?? project?.project.error}
              action={
                <Button
                  onClick={() =>
                    act(() =>
                      api(
                        vid
                          ? `/versions/${vid}/retry`
                          : `/projects/${pid}/retry`,
                        "POST",
                        {},
                      ),
                    )
                  }
                >
                  从中断处继续
                </Button>
              }
            />
          )}
          {page === "upload" && (
            <div className="upload-grid">
              <Card className="upload-card">
                <div className="section-title">
                  <span className="number">01</span>
                  <div>
                    <h2>导入故事开头</h2>
                    <p>建议约 10,000 字，系统会理解人物、伏笔与原文风格。</p>
                  </div>
                </div>
                <label>作品名称</label>
                <Input
                  size="large"
                  placeholder="给这个故事起个名字"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
                <label>
                  题材标签 <small>选填，用逗号分隔</small>
                </label>
                <Input
                  placeholder="如：都市，逆袭，悬疑"
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                />
                <label>原文正文</label>
                <Input.TextArea
                  rows={12}
                  placeholder="粘贴原文，或选择下方文件。原文章节标题会自动识别。"
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    setFile(undefined);
                  }}
                />
                <div className="file-row">
                  <label className="file-button">
                    选择 TXT / DOCX
                    <input
                      type="file"
                      accept=".txt,.md,.docx"
                      onChange={(e) => {
                        setFile(e.target.files?.[0]);
                        if (e.target.files?.[0]) setText("");
                      }}
                    />
                  </label>
                  <span>
                    {file?.name ??
                      `${text.replace(/\s/g, "").length.toLocaleString()} 字`}
                  </span>
                </div>
                <Button
                  size="large"
                  block
                  type="primary"
                  loading={busy}
                  disabled={!title.trim() || (!text.trim() && !file)}
                  onClick={upload}
                >
                  理解原文，生成续写方向 <ArrowRightOutlined />
                </Button>
              </Card>
              <div className="guide">
                <div className="guide-illustration">
                  <BookOutlined />
                </div>
                <h2>
                  创意交给模型
                  <br />
                  选择留给你
                </h2>
                <p>
                  先看懂原文，再构思不同的续写方向。你确认大纲后，系统才会开始逐章写作。
                </p>
                {[
                  "三种不同的剧情走向",
                  "人物与伏笔持续追踪",
                  "逐章审核，保留每次修改",
                ].map((t, i) => (
                  <div className="guide-item" key={t}>
                    <span>{String(i + 1).padStart(2, "0")}</span>
                    {t}
                  </div>
                ))}
              </div>
            </div>
          )}
          {page === "directions" && pid && (
            <>
              <div className="section-heading">
                <div>
                  <h2>下一步，让故事走向哪里？</h2>
                  <p>比较方向的冲突、爽点和结局，也可以写下你的想法。</p>
                </div>
                <Space>
                  <Button
                    disabled={
                      working ||
                      project?.project.status !== "awaiting_direction"
                    }
                    icon={<ReloadOutlined />}
                    onClick={() =>
                      act(() =>
                        api(`/projects/${pid}/directions/regenerate`, "POST", {
                          reason,
                        }),
                      )
                    }
                  >
                    换一批
                  </Button>
                  <Button
                    disabled={
                      working ||
                      project?.project.status !== "awaiting_direction"
                    }
                    onClick={() => choose("auto")}
                  >
                    自动选择
                  </Button>
                  <Button
                    disabled={
                      working ||
                      project?.project.status !== "awaiting_direction"
                    }
                    onClick={() => setManual(true)}
                  >
                    自己写方向
                  </Button>
                </Space>
              </div>
              {working && !vid && (
                <Card>
                  <Spin /> 正在理解原文、构思方向，完成后会显示在这里。
                </Card>
              )}
              <div className="direction-grid">
                {project?.directions.map((d: Json, i: number) => (
                  <Card key={d.id} className="direction-card">
                    <div className="direction-top">
                      <span>方向 {String(i + 1).padStart(2, "0")}</span>
                      <Tag>{d.data.main_trope}</Tag>
                    </div>
                    <h2>{d.data.title}</h2>
                    <p className="hook">{d.data.hook}</p>
                    <div className="card-label">核心冲突</div>
                    <p>{d.data.core_conflict}</p>
                    <div className="card-label">爽点路径</div>
                    <ol>
                      {d.data.payoff_plan.map((s: string) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ol>
                    <div className="card-label">结局落点</div>
                    <p>{d.data.ending}</p>
                    <details>
                      <summary>展开梗概与评审</summary>
                      <p>{d.data.synopsis}</p>
                      <p>{d.data.differentiation}</p>
                      {Object.entries(d.judge_scores).map(([k, v]) => (
                        <p key={k}>
                          <b>
                            {
                              (
                                {
                                  consistency: "一致性",
                                  payoff_strength: "爽点强度",
                                  capacity: "字数承载力",
                                  novelty: "新颖性",
                                  channel_fit: "渠道契合度",
                                } as Json
                              )[k]
                            }{" "}
                            · {(v as Json).score}/5
                          </b>
                          <br />
                          {(v as Json).reason}
                        </p>
                      ))}
                    </details>
                    <Space>
                      <Button
                        type="primary"
                        loading={busy}
                        disabled={working}
                        onClick={() => choose("candidate", d)}
                      >
                        采用这个方向
                      </Button>
                      <Button
                        icon={<EditOutlined />}
                        disabled={working}
                        onClick={() =>
                          setDirection({ ...d, edited: { ...d.data } })
                        }
                      >
                        修改
                      </Button>
                    </Space>
                  </Card>
                ))}
              </div>
              <div className="selection-note">
                <span>选择理由（选填）</span>
                <Input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="记录这次判断，帮助后续复盘"
                />
                <span>目标字数</span>
                <InputNumber
                  value={target}
                  min={1000}
                  max={100000}
                  step={1000}
                  onChange={(v) => setTarget(v ?? 20000)}
                />
              </div>
              <Card title="原文理解" className="bible">
                <Tabs
                  items={[
                    {
                      key: "bible",
                      label: "故事档案",
                      children: project?.bible ? (
                        <>
                          <p>{project.bible.data.logline}</p>
                          <Space wrap>
                            {project.bible.data.characters.map((c: Json) => (
                              <Card size="small" key={c.name} title={c.name}>
                                <p>{c.personality.join(" / ")}</p>
                                <p>{c.goal_now}</p>
                              </Card>
                            ))}
                          </Space>
                          {project.bible.warnings
                            .filter((w: Json) => w.type === "unverified")
                            .map((w: Json, i: number) => (
                              <Alert
                                key={i}
                                type="warning"
                                message={`待核对证据：${w.entry} · ${w.quote}`}
                              />
                            ))}
                        </>
                      ) : (
                        <Empty description="等待理解原文" />
                      ),
                    },
                    {
                      key: "source",
                      label: "原文",
                      children: (
                        <div className="manuscript">
                          {project?.source_chapters.map((c: Json) => (
                            <section key={c.id}>
                              <h3>{c.title}</h3>
                              {c.content}
                            </section>
                          ))}
                        </div>
                      ),
                    },
                  ]}
                />
              </Card>
            </>
          )}
          {page === "outline" && vid && (
            <>
              <div className="section-heading">
                <div>
                  <h2>先把故事的骨架定下来</h2>
                  <p>确认章节走向、爽点和伏笔回收，再开始正文创作。</p>
                </div>
                <Button
                  disabled={!chapters.length}
                  onClick={() => setPage("review")}
                >
                  前往正文审阅 <ArrowRightOutlined />
                </Button>
              </div>
              {status === "awaiting_direction_confirmation" && (
                <Card title="请确认整理后的方向">
                  <h3>{version?.version.direction.title}</h3>
                  <p>{version?.version.direction.synopsis}</p>
                  <Button
                    type="primary"
                    onClick={() =>
                      act(() =>
                        api(`/versions/${vid}/direction/confirm`, "POST", {}),
                      )
                    }
                  >
                    确认方向，生成大纲
                  </Button>
                </Card>
              )}
              {outline ? (
                <>
                  <Card>
                    <label>整体走向</label>
                    <Input.TextArea
                      rows={4}
                      value={outline.arc_summary}
                      disabled={status !== "awaiting_outline"}
                      onChange={(e) => {
                        setOutline({ ...outline, arc_summary: e.target.value });
                        setDirty(true);
                      }}
                    />
                    <label>新增角色（确认大纲时一并批准）</label>
                    {outline.new_characters.length ? (
                      outline.new_characters.map((c: Json, i: number) => (
                        <div key={i} className="new-character">
                          <Input
                            value={c.name}
                            disabled={status !== "awaiting_outline"}
                            onChange={(e) => {
                              setOutline({
                                ...outline,
                                new_characters: outline.new_characters.map(
                                  (x: Json, j: number) =>
                                    i === j
                                      ? { ...x, name: e.target.value }
                                      : x,
                                ),
                              });
                              setDirty(true);
                            }}
                          />
                          <Input
                            value={c.purpose}
                            disabled={status !== "awaiting_outline"}
                            onChange={(e) => {
                              setOutline({
                                ...outline,
                                new_characters: outline.new_characters.map(
                                  (x: Json, j: number) =>
                                    i === j
                                      ? { ...x, purpose: e.target.value }
                                      : x,
                                ),
                              });
                              setDirty(true);
                            }}
                          />
                          <Button
                            size="small"
                            danger
                            disabled={status !== "awaiting_outline"}
                            onClick={() => {
                              setOutline({
                                ...outline,
                                new_characters: outline.new_characters.filter(
                                  (_: Json, j: number) => j !== i,
                                ),
                              });
                              setDirty(true);
                            }}
                          >
                            移除
                          </Button>
                        </div>
                      ))
                    ) : (
                      <p className="muted">沿用原文人物，无新增角色</p>
                    )}
                    {status === "awaiting_outline" && (
                      <Button
                        size="small"
                        icon={<PlusOutlined />}
                        onClick={() => {
                          setOutline({
                            ...outline,
                            new_characters: [
                              ...outline.new_characters,
                              { name: "", purpose: "" },
                            ],
                          });
                          setDirty(true);
                        }}
                      >
                        新增角色
                      </Button>
                    )}
                    {version?.outline.warnings.map((w: string) => (
                      <Alert key={w} type="warning" message={w} />
                    ))}
                  </Card>
                  <div className="outline-list">
                    {outline.chapters.map((c: Json, i: number) => (
                      <Card key={c.index}>
                        <div className="outline-row">
                          <div className="chapter-index">
                            {String(c.index).padStart(2, "0")}
                            <small>章节</small>
                          </div>
                          <div className="outline-fields">
                            <Space>
                              <Input
                                value={c.title}
                                disabled={status !== "awaiting_outline"}
                                onChange={(e) =>
                                  changeChapter(i, "title", e.target.value)
                                }
                              />
                              <Select
                                value={c.function}
                                disabled={status !== "awaiting_outline"}
                                style={{ width: 115 }}
                                options={[
                                  "铺垫",
                                  "冲突升级",
                                  "爽点兑现",
                                  "反转",
                                  "高潮",
                                  "收束",
                                ].map((s) => ({ value: s, label: s }))}
                                onChange={(v) =>
                                  changeChapter(i, "function", v)
                                }
                              />
                            </Space>
                            {[
                              ["summary", "章节内容"],
                              ["payoff", "爽点兑现"],
                              ["hook", "章末钩子"],
                            ].map(([key, label]) => (
                              <div key={key}>
                                <label>{label}</label>
                                <Input.TextArea
                                  autoSize={{
                                    minRows: key === "summary" ? 3 : 1,
                                  }}
                                  disabled={status !== "awaiting_outline"}
                                  value={c[key] ?? ""}
                                  onChange={(e) =>
                                    changeChapter(
                                      i,
                                      key,
                                      key === "payoff"
                                        ? e.target.value || null
                                        : e.target.value,
                                    )
                                  }
                                />
                              </div>
                            ))}
                            {c.foreshadow_ops.length > 0 && (
                              <p className="muted">
                                伏笔：
                                {c.foreshadow_ops
                                  .map(
                                    (o: Json) =>
                                      `${o.id} · ${o.op === "payoff" ? "回收" : "埋设"}：${o.note}`,
                                  )
                                  .join("；")}
                              </p>
                            )}
                          </div>
                        </div>
                      </Card>
                    ))}
                  </div>
                  <div className="sticky-actions">
                    <span>
                      {outline.chapters.length} 章 · 目标{" "}
                      {version?.version.target_words.toLocaleString()} 字
                      {dirty ? " · 有未保存修改" : ""}
                    </span>
                    <Space>
                      <Button
                        disabled={!dirty || status !== "awaiting_outline"}
                        loading={busy}
                        onClick={() =>
                          act(async () => {
                            await api(`/versions/${vid}/outline`, "PUT", {
                              outline,
                            });
                            setDirty(false);
                            setOutline(
                              (await api(`/versions/${vid}`)).outline.data,
                            );
                          })
                        }
                      >
                        保存大纲
                      </Button>
                      <Button
                        type="primary"
                        disabled={dirty || status !== "awaiting_outline"}
                        loading={busy}
                        onClick={() =>
                          act(() =>
                            api(`/versions/${vid}/outline/confirm`, "POST", {}),
                          )
                        }
                      >
                        确认大纲，开始续写 <ArrowRightOutlined />
                      </Button>
                    </Space>
                  </div>
                </>
              ) : working ? (
                <Card>
                  <Spin /> 正在构思大纲，请稍候。
                </Card>
              ) : (
                <Empty description="大纲尚未生成" />
              )}
            </>
          )}
          {page === "review" && vid && (
            <>
              <div className="section-heading">
                <div>
                  <h2>逐章打磨，故事由你定稿</h2>
                  <p>查看审核意见、对照修改历史，确认后提交。</p>
                </div>
                <Space>
                  <Button
                    icon={<DownloadOutlined />}
                    href={`/api/versions/${vid}/export?format=txt`}
                  >
                    TXT
                  </Button>
                  <Button
                    icon={<DownloadOutlined />}
                    href={`/api/versions/${vid}/export?format=docx`}
                  >
                    Word
                  </Button>
                  <Button
                    type="primary"
                    disabled={status !== "awaiting_review"}
                    loading={busy}
                    onClick={() =>
                      act(() => api(`/versions/${vid}/submit`, "POST", {}))
                    }
                  >
                    确认提交
                  </Button>
                </Space>
              </div>
              <Card className="progress-card">
                <div>
                  {labels[status]}
                  <span>
                    {chapters.length} / {version?.version.total_chapters ?? 0}{" "}
                    章 ·{" "}
                    {chapters
                      .reduce((s: number, d: Json) => s + d.word_count, 0)
                      .toLocaleString()}{" "}
                    字
                  </span>
                </div>
                <Progress percent={progress} showInfo={false} />
              </Card>
              {current ? (
                <div className="review-grid">
                  <div className="chapter-nav">
                    {chapters.map((d) => (
                      <button
                        key={d.id}
                        className={current.index === d.index ? "selected" : ""}
                        onClick={() => {
                          setIndex(d.index);
                          setEdit(false);
                        }}
                      >
                        <span>第{d.index}章</span>
                        {d.title}
                        <small>
                          {d.word_count} 字 · 修订 {d.rev}
                          {version?.version.stale_chapters.includes(d.index)
                            ? " · 待核对"
                            : ""}
                        </small>
                      </button>
                    ))}
                  </div>
                  <Card className="reader">
                    <Tabs
                      items={[
                        {
                          key: "text",
                          label: "正文",
                          children: (
                            <>
                              {version?.version.stale_chapters.includes(
                                current.index,
                              ) && (
                                <Alert
                                  type="warning"
                                  message="前文已修改，这一章可能不连贯，请核对。"
                                />
                              )}
                              <div className="reader-tools">
                                <Tag
                                  color={
                                    review?.editor_accepted ||
                                    review?.verdict === "pass"
                                      ? "green"
                                      : "orange"
                                  }
                                >
                                  {review?.editor_accepted
                                    ? "编辑已确认"
                                    : review?.verdict === "pass"
                                      ? "审核通过"
                                      : review
                                        ? "有修改意见"
                                        : "等待审核"}
                                </Tag>
                                <Space>
                                  <Button
                                    disabled={status !== "awaiting_review"}
                                    size="small"
                                    onClick={() => {
                                      setDraftText(current.content);
                                      setEdit(!edit);
                                    }}
                                  >
                                    {edit ? "取消修改" : "直接修改"}
                                  </Button>
                                  <Button
                                    disabled={status !== "awaiting_review"}
                                    size="small"
                                    onClick={() => {
                                      setRewrite(true);
                                      setInstruction("");
                                    }}
                                  >
                                    提出意见重写
                                  </Button>
                                </Space>
                              </div>
                              {edit ? (
                                <>
                                  <Input.TextArea
                                    rows={24}
                                    value={draftText}
                                    onChange={(e) =>
                                      setDraftText(e.target.value)
                                    }
                                  />
                                  <Button
                                    type="primary"
                                    loading={busy}
                                    onClick={() =>
                                      act(async () => {
                                        await api(
                                          `/versions/${vid}/chapters/${current.index}`,
                                          "PUT",
                                          { content: draftText },
                                        );
                                        setEdit(false);
                                      })
                                    }
                                  >
                                    保存并重新审核
                                  </Button>
                                </>
                              ) : (
                                <article className="manuscript">
                                  {current.content}
                                </article>
                              )}
                            </>
                          ),
                        },
                        {
                          key: "plan",
                          label: "本章细纲",
                          children: (
                            <>
                              {version?.plans
                                .filter((p: Json) => p.index === current.index)
                                .map((p: Json) => (
                                  <div key={p.id}>
                                    <p>视角人物：{p.data.pov_character}</p>
                                    {p.data.scenes.map((s: Json, i: number) => (
                                      <Card
                                        key={i}
                                        size="small"
                                        title={`场景 ${i + 1} · ${s.location}`}
                                      >
                                        <p>{s.characters.join("、")}</p>
                                        <ol>
                                          {s.beats.map((b: string) => (
                                            <li key={b}>{b}</li>
                                          ))}
                                        </ol>
                                      </Card>
                                    ))}
                                    <p>结尾：{p.data.ending_beat}</p>
                                  </div>
                                ))}
                            </>
                          ),
                        },
                        {
                          key: "history",
                          label: "修改对比",
                          children: (
                            <div className="history">
                              {version?.draft_history
                                .filter((d: Json) => d.index === current.index)
                                .sort((a: Json, b: Json) => b.rev - a.rev)
                                .map((d: Json) => (
                                  <section key={d.id}>
                                    <h4>
                                      修订 {d.rev} ·{" "}
                                      {d.author === "ai" ? "AI" : d.author}
                                      {d.is_current ? " · 当前稿" : ""}
                                    </h4>
                                    <div className="manuscript">
                                      {d.content
                                        .split("\n")
                                        .map((line: string, i: number) => {
                                          const prev =
                                            version.draft_history.find(
                                              (h: Json) =>
                                                h.index === d.index &&
                                                h.rev === d.rev - 1,
                                            );
                                          return (
                                            <div
                                              key={i}
                                              className={
                                                prev &&
                                                !prev.content
                                                  .split("\n")
                                                  .includes(line)
                                                  ? "changed"
                                                  : ""
                                              }
                                            >
                                              {line || "\u00a0"}
                                            </div>
                                          );
                                        })}
                                    </div>
                                  </section>
                                ))}
                            </div>
                          ),
                        },
                      ]}
                    />
                  </Card>
                  <Card size="small" title="审阅意见" className="review-notes">
                    {review ? (
                      <>
                        {review.rule_issues.map((r: Json, i: number) => (
                          <Alert
                            key={i}
                            type={r.verdict === "block" ? "error" : "warning"}
                            message={r.detail}
                          />
                        ))}
                        {[
                          "consistency_issues",
                          "plan_deviation",
                          "pacing_issues",
                          "ai_flavor_issues",
                        ].flatMap((k) =>
                          (review.llm_review[k] ?? []).map(
                            (r: Json, i: number) => (
                              <div className="issue" key={k + i}>
                                <Tag>
                                  {r.severity === "high"
                                    ? "高风险"
                                    : "建议修改"}
                                </Tag>
                                <blockquote>{r.quote}</blockquote>
                                <p>{r.reason}</p>
                              </div>
                            ),
                          ),
                        )}
                        <ol>
                          {review.llm_review.fix_suggestions?.map(
                            (s: string) => (
                              <li key={s}>{s}</li>
                            ),
                          )}
                        </ol>
                        {review.verdict === "pass" &&
                          !review.rule_issues.length && (
                            <p>未发现需拦截的问题。</p>
                          )}
                        <Button
                          block
                          disabled={status !== "awaiting_review"}
                          icon={<CheckOutlined />}
                          onClick={() =>
                            act(() =>
                              api(
                                `/versions/${vid}/chapters/${current.index}/accept`,
                                "POST",
                                { reason: "编辑已查看审核意见并确认本章" },
                              ),
                            )
                          }
                        >
                          已核对，确认采用
                        </Button>
                      </>
                    ) : (
                      <Spin />
                    )}
                  </Card>
                </div>
              ) : (
                <Empty
                  description={
                    working
                      ? "正文正在逐章生成，完成的章节将出现在这里"
                      : "还没有生成正文"
                  }
                />
              )}
            </>
          )}
          <Modal
            title="修改续写方向"
            open={!!direction}
            onCancel={() => setDirection(undefined)}
            onOk={() => choose("edited", direction, direction?.edited)}
            confirmLoading={busy}
            width={680}
          >
            {direction && (
              <>
                {[
                  ["title", "方向名称"],
                  ["hook", "一句话卖点"],
                  ["core_conflict", "核心冲突"],
                  ["synopsis", "剧情梗概"],
                  ["ending", "结局"],
                ].map(([key, label]) => (
                  <div key={key}>
                    <label>{label}</label>
                    <Input.TextArea
                      autoSize={{ minRows: key === "synopsis" ? 5 : 1 }}
                      value={direction.edited[key]}
                      onChange={(e) =>
                        setDirection({
                          ...direction,
                          edited: {
                            ...direction.edited,
                            [key]: e.target.value,
                          },
                        })
                      }
                    />
                  </div>
                ))}
                <label>爽点路径（每行一个，按顺序）</label>
                <Input.TextArea
                  rows={4}
                  value={direction.edited.payoff_plan.join("\n")}
                  onChange={(e) =>
                    setDirection({
                      ...direction,
                      edited: {
                        ...direction.edited,
                        payoff_plan: e.target.value.split("\n"),
                      },
                    })
                  }
                />
                <label>计划回收的伏笔</label>
                <Select
                  mode="multiple"
                  style={{ width: "100%" }}
                  value={direction.edited.uses_foreshadows}
                  options={(project?.bible?.data.foreshadows ?? []).map(
                    (f: Json) => ({
                      value: f.id,
                      label: `${f.id} · ${f.content}`,
                    }),
                  )}
                  onChange={(v) =>
                    setDirection({
                      ...direction,
                      edited: { ...direction.edited, uses_foreshadows: v },
                    })
                  }
                />
              </>
            )}
          </Modal>
          <Modal
            title="写下你的续写方向"
            open={manual}
            onCancel={() => setManual(false)}
            onOk={() => choose("manual")}
            confirmLoading={busy}
            okButtonProps={{ disabled: !manualText.trim() }}
          >
            <p>模型会保留你的想法，整理成方向卡供你再次确认。</p>
            <Input.TextArea
              rows={7}
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              placeholder="希望发生什么冲突，主角如何行动，结局走向哪里？"
            />
          </Modal>
          <Modal
            title={`重写第${current?.index ?? ""}章`}
            open={rewrite}
            onCancel={() => setRewrite(false)}
            onOk={() =>
              act(async () => {
                await api(
                  `/versions/${vid}/chapters/${current?.index}/regenerate`,
                  "POST",
                  { instruction },
                );
                setRewrite(false);
              })
            }
            confirmLoading={busy}
            okButtonProps={{ disabled: !instruction.trim() }}
          >
            <p>只重写这一章，后续章节会提示你检查衔接。</p>
            <Input.TextArea
              rows={5}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="例如：减少解释，让冲突通过对话推进。"
            />
          </Modal>
          <footer>
            Starling 故事工坊 <span>每个好故事，都值得一个好结尾。</span>
          </footer>
        </main>
      </div>
    </ConfigProvider>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
