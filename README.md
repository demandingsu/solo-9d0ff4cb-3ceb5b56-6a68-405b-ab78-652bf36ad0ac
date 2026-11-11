# 市政工程投标公告采集 API

面向投标专员核对各标段**实际投标截止时间**的采集服务：接收公告目录 URL，沿分页抓取与内置样例结构一致的详情页，按招标编号归集**原公告 / 改期公告 / 撤回公告**，沿有效公告链计算当前截止时间；并行改期时间不一致时如实返回冲突，不猜测结果。

## 业务规则

1. **归集**：以招标编号分组。原公告为链根；每条改期公告通过“依据公告”注明其依据的公告（原公告或上一条改期）；撤回公告通过“撤回公告”字段指定被撤回的改期。
2. **撤回级联失效**：撤回指定改期后，该改期及其全部后续改期（沿依据链传递依赖）标记为失效并注明原因；失效公告不参与截止时间计算。
3. **有效链与截止时间**：从原公告出发，沿有效改期逐级下行，链末端公告的投标截止时间即当前有效截止时间，返回结果同时给出该公告的来源链接。
4. **并行改期冲突**：同一有效依据下存在多条有效并行改期时：
   - 截止时间一致 → 取该时间并在 `notes` 说明；
   - 截止时间不一致 → `status=conflict`，`current_deadline=null`，`conflict` 列出全部冲突公告及其时间与来源链接，**不猜结果**。
5. **重新采集**：再次采集成功时用完整新结果**整体替换**旧结果（临时文件 + 原子 rename）；抓取或解析任一页面失败时返回 502 且**不触碰存储**，旧结果完整保留。

## 目录结构

```
app/                 FastAPI 应用
  main.py            路由：采集、查询、离线样例静态挂载
  crawler.py         分页抓取（httpx 异步 + 并发限制 + 上限/循环保护）
  parser.py          目录页/详情页 HTML 解析
  chain.py           归集、撤回级联失效、并行冲突判定
  storage.py         JSON 文件存储（异步锁、原子替换）
  models.py          Pydantic 模型
sample_site/         可离线访问的分页 HTML 公告样例（相对链接、无外部资源）
  index.html
  catalog/page_1..3.html
  detail/A001..A018.html
scripts/generate_samples.py  样例站点生成脚本（结构即解析契约）
tests/               12 项单元 + 集成测试
Dockerfile / docker-compose.yml
```

## 快速开始（Docker Compose）

```bash
docker compose up --build
# API:      http://localhost:8000
# 交互文档:  http://localhost:8000/docs
# 离线样例:  http://localhost:8000/sample  （也可直接用浏览器打开 sample_site/index.html）
```

采集结果持久化在 `tender-data` 卷内（`/data/store.json`）。

## 本地无 Docker 运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_samples.py          # 已随仓库提供，修改样例后重新生成
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 接口

### `POST /api/collect` 触发采集

```json
// 请求
{ "catalog_url": "http://localhost:8000/sample/catalog/page_1.html" }
// 成功响应 200
{
  "status": "collected",
  "catalog_url": "...",
  "total_pages": 3,
  "total_announcements": 18,
  "collected_at": "2026-11-11T10:46:32.894225+00:00",
  "replaced_previous": true
}
// 失败响应 502（旧结果保留）
{ "detail": { "error": "抓取失败 ...", "previous_result_retained": true,
              "message": "采集失败，已保留上一次成功采集的结果" } }
```

### `GET /api/tenders` 各标段截止时间汇总

```json
[
  { "tender_code": "ZG-2026-001", "project_name": "市政道路改造工程",
    "status": "ok", "current_deadline": "2026-12-04 09:30",
    "conflict": null, "notes": ["当前截止时间依据有效公告链末端公告 A018（改期公告）"] },
  { "tender_code": "ZG-2026-003", "status": "conflict", "current_deadline": null,
    "conflict": [ {"announcement_id": "A012", "deadline": "2026-12-05 09:30",
                   "published_at": "2026-11-12 09:00", "source_url": "..."},
                  {"announcement_id": "A013", "deadline": "2026-12-08 09:30", ...} ] }
]
```

### `GET /api/tenders/{招标编号}` 单标段完整公告链

每条公告带 `valid` / `invalid_reason` / `source_url`，可直接核对来源。例：

```
A011 改期公告 valid=False 被撤回公告直接撤回
A017 改期公告 valid=False 所依据的改期公告 A011 已失效（撤回级联）
```

其他：`GET /api/raw`（最近一次采集原始数据）、`GET /health`。

## 内置样例覆盖的场景

| 招标编号 | 场景 | 预期结果 |
|---|---|---|
| ZG-2026-001 | 原公告 + 4 次串行改期 | 截止时间取末次改期 `2026-12-04 09:30` |
| ZG-2026-002 | 第二次改期被撤回，第三次改期依赖它 | 撤回 + 级联失效，回退到第一次改期 `2026-11-26 09:30` |
| ZG-2026-003 | 同一依据下两条并行改期、时间不同 | `conflict`，列出 A012/A013 两个时间与来源 |
| ZG-2026-004 | 第一次改期被撤回、第二次级联失效 | 回退到原公告 `2026-11-21 09:30` |

## 页面结构约定（采集目标需与样例一致）

- 目录页：`<ul class="catalog">` 内每条一个详情 `<a href>`；分页用 `<a rel="next" href="...">`，无该链接即末页。
- 详情页：`<table id="announcement-meta">` 内 `th/td` 键值对，字段为
  公告编号、招标编号、公告类型（招标公告/改期公告/撤回公告）、项目名称、发布时间、
  投标截止时间、依据公告（改期必填）、撤回公告（撤回必填）。

## 测试

```bash
pip install -r requirements.txt
pytest -q
# 12 passed：链路规则 7 项（含撤回级联、并行冲突、部分撤回），API 全流程 5 项
# （含采集失败保留旧结果、重新采集整体替换、离线样例可访问）
```

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `./data` | 采集结果存储目录 |
| `REQUEST_TIMEOUT` | `10` | 单次 HTTP 超时秒数 |
| `MAX_PAGES` | `100` | 目录分页上限（防循环/异常） |
| `MAX_CONCURRENCY` | `8` | 详情页抓取并发数 |
