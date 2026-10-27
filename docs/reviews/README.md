# docs/reviews 索引与布局约定

本文件是 `docs/reviews/` 的索引：新审阅会话按下方最小布局约定落盘，历史会话不回改、在本页注明其布局差异。

## 最小布局约定（新会话起适用）

- 会话目录：`docs/reviews/review_<YYYYMMDD>_<HHMMSS>/`，名称只含起始时间，不带主题后缀。
- 元数据：统一放会话目录下的 `_meta/` 子目录，必备 `_meta/_meta.json`（只保留 target/sha/phase/计数等可复核字段，运行时字段入库前剥离，时间戳统一 +08:00）；`units.json`、`progress.log` 同置于 `_meta/`。注：`.gitignore` 已忽略 `docs/reviews/review_*/_meta/`，新会话的 `_meta/` 默认不入库；个别历史会话的 `_meta/` 系早期强制入库，保留原样。
- 必备文件：`review_intensive.md`（聚合报告，finding 全文的单一权威）、`review_summary.md`（只保留计数、Verdict 与指向 `review_intensive.md` 对应节的链接，不复写 finding 全文）、`bundle_*.md`（每输入单元一份）；`bundles` 计数指输入单元数，即 `bundle_*.md` 的文件数（交叉验证、回归等中央探针文件不计入单元数时须在 `_meta` 或 summary 中注明口径）。
- 可选文件：`adoption_decision.md`（采纳处置，处置以此为准）、`validation.md`、`regression.md`。
- bundle 命名：`bundle_<unit>.md`，`<unit>` 用单元主题或序号，全会话内保持一种风格。

## 历史会话布局差异（入库口径，不回改）

|会话|与最小布局的差异|
|---|---|
|`review_20261021_011116`|`_meta.json` 为会话根目录下的单文件（无 `_meta/` 子目录）；bundle 按视角合并命名（`bundle_v1_*.md` 等及 `bundle_zz_findings_machine.md`）；无 `review_summary.md`、无 `adoption_decision.md`|
|`review_20261021_034329`|`_meta/` 内除 `_meta.json` 外另有 `rubric.md`；该会话超时终止（phase=timeout），仅 `bundle_pkg_root.md` 一份 bundle 入库，无 `review_intensive.md` / `review_summary.md`|
|`review_20261021_040521`|`_meta/` 内只有 `_meta.json`；无 `review_intensive.md` / `review_summary.md`，代之以 `summary_verification_report.md` 与 `validation_read_only.md`；另有根目录 `scope.json`、`bundle.json`|
|`review_20261021_064335`|入库文件仅 `review_da57df7_findings_and_decisions.md` 一份（其余产物未入库），无可对照的包内布局|
|`review_20261022_052842`|无 `_meta/`（根目录 `bundle.json`）；bundle 按视角命名（`bundle_v1_*.md` 等）；无 `review_summary.md`，有 `adoption_decision.md`|
|`review_20261022_071448`|无 `_meta/`（根目录 `bundle.json`）；bundle 按被审目录命名（`bundle_dir_*.md`，百余份）；无 `review_summary.md`，有 `adoption_decision.md`|
|`review_20261025_020805`|`_meta/` 在本地磁盘存在但按 `.gitignore` 未入库；bundle 按单元主题命名（`bundle_mc_*.md`、`bundle_frontend_*.md` 等，含中央探针 `bundle_privacy_history.md` 与回归 `bundle_regression*.md`）；`review_summary.md` 与 `adoption_decision.md` 齐全|
|`review_20261026_005019_full_repository`|目录名带主题后缀（`_full_repository`）；非 bundle 布局，文件为 `review_report.md`、`review_evidence.md`、`execution_log.md`、`repair_plan.md`、`repair_results.md`、`technical_design.md`；无 `_meta/`、无 `review_intensive.md`|
|`review_20261026_180800_current_repository`|目录名带主题后缀（`_current_repository`）；仅 `review_report.md` 一份|
|`review_20261026_commits`|目录名无时间戳、仅主题（`_commits`）；仅 `review_report.md`、`repair_design.md` 两份|
|`review_20261027_021416`|`_meta/` 在本地磁盘存在但按 `.gitignore` 未入库（另含 `_meta.log` 与 `unit01_files.txt`…`unit13_files.txt`）；bundle 按序号命名（`bundle_unit01.md`…`bundle_unit13.md`）；另有 `validation.md`、`regression.md`、`bundle_cross_validation_regression.md`|
