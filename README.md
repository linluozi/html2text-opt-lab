# html2text-opt-lab — reference-link anchor dedup: Θ(n²) → Θ(n)

`html2text` turns HTML into Markdown. This lab removes the quadratic rescan inside
`HTML2Text.previousIndex()`, which is called once per emitted reference link when
`inline_links=False` ("reference link" style). Upstream rescans the whole anchor list
each time; the patch keeps an incremental `href -> indices` map.

Upstream: https://github.com/Alir3z4/html2text

- Upstream commit: `5cf85510a2498546d5b48ad1bf7d75b146aac591` (latest tag `2025.4.15`)
- Patch: `patch.diff`, **55 insertions / 11 deletions in one file** (`git diff --stat`
  reports 66 changed lines, ≤ 80). Public API, return values and the upstream tests are
  untouched.
- Only the `inline_links=False` path changes. The default inline-link path is not on
  the patched code path at all.

## 本轮创新

**新在哪 / 和谁不一样 / 凭什么。** 之前的 `-opt-lab` 只报“合成负载上快了多少”。
本仓库给出的是**标度指数证书 + 真实语料对照**，结论是负面的、可证伪的：
`previousIndex()` 在**互异 href 数**上是货真价实的二次（每翻倍标度指数 = log2 相邻比
1.40→1.62→1.72→1.88，顶段逼近 2.0；原始相邻比见下表 2.65→3.68），改后整体指数 1.004；**但真实 HTML 文档几乎拿不到收益**
（Node.js API 文档 0.977×–1.001×，上游 74 个真实 fixture 0.993×）。
即：这是一个**渐进保险（asymptotic insurance）**，不是日常提速。台账里 7 个 algo
lab 没有一个给出过“修完了但真实语料没收益”的量化结论；本仓库把“差异在哪个维度上
是真二次、哪个维度上不是”测了出来，别人可以直接用同一份 bench 复现或推翻。

## 复现（3 条命令）

```bash
git clone https://github.com/linluozi/html2text-opt-lab.git && cd html2text-opt-lab
python3 -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/python tests/test_diff.py && .venv/bin/python benchmark/bench.py --impl optimized --sweep --real-dir test
```

## 基准结果（实测，非预测）

同一份 `benchmark/bench.py`，同一台机器、同一 CPython，改动前后各跑一次。
每规模先 warmup 3 次再计时 7 次；报告**中位数 + p25/p75**。原始样本在
`benchmark/raw/`（baseline 与 optimized 各 66 个文件，共 132 个），聚合值在
`benchmark/baseline.json` / `benchmark/optimized.json`。

合成负载：N 个 `<a>`，每个 href 互异，全部在一个段落内（不触发刷写），
`inline_links=False`：

| N (anchors) | baseline 中位 (s) | optimized 中位 (s) | 加速比 |
| --- | --- | --- | --- |
| 300 | 0.013154 | 0.009280 | **1.42×** |
| 900 | 0.069961 | 0.027730 | **2.52×** |
| 2700 | 0.483915 | 0.084904 | **5.70×** |

三个规模加速比的**中位数 = 2.52×**。相对标准差 baseline 0.005–0.011、optimized
0.011–0.023，均 < 10%，无噪声规模。

### 标度指数证书（每次 5 次计时，warmup 2）

| N | baseline (s) | optimized (s) | baseline 相邻倍率 | optimized 相邻倍率 |
| --- | --- | --- | --- | --- |
| 250 | 0.010419 | 0.007806 | — | — |
| 500 | 0.027561 | 0.015757 | 2.65 | 2.02 |
| 1000 | 0.084447 | 0.031449 | 3.06 | 2.00 |
| 2000 | 0.278542 | 0.063402 | 3.30 | 2.02 |
| 4000 | 1.024325 | 0.126404 | 3.68 | 1.99 |

- baseline 最小二乘 log–log 斜率 = **1.658**；每翻倍标度指数（= log2 相邻比）
  1.40→1.62→1.72→1.88 单调上升，顶段逼近 2.0 —— 即二次项在 n 较大时才主导
  （文档解析是线性的，会摊薄整体指数）。注意上表的“相邻倍率”是原始比值（2.65→3.68），
  本行的 1.40→1.88 是它们的 log2，两者不是一个量纲。
  按昨晚计划“整体指数 ≥1.80 才准写超线性”的口径：**整体 1.658 < 1.80，所以本 README
  不声称“超线性”**，只报告相邻倍率与每翻倍指数证据。
- optimized 斜率 = **1.004**（每个区间都在 1.99–2.02，即线性）。

### 真实语料（同一 bench，`--real` / `--real-dir`）

| 语料 | 锚点数 | 字节 | baseline (s) | optimized (s) | 加速比 |
| --- | --- | --- | --- | --- | --- |
| `/usr/share/doc/nodejs/api/fs.html` | 2059 | 498323 | 0.297004 | 0.303835 | **0.977×** |
| `/usr/share/doc/nodejs/api/crypto.html` | 1462 | 369239 | 0.193410 | 0.193136 | **1.001×** |
| `/usr/share/doc/nodejs/api/n-api.html` | 1288 | 368724 | 0.167344 | 0.169411 | **0.988×** |
| 上游自带 `test/*.html`（74 个真实 fixture） | 43 | 42407 | 0.027574 | 0.027775 | **0.993×** |

**结论（必须明写）**：真实 HTML 语料上加速比 < 1.15×，**本优化只在“合成互异
href 高重复扫描”负载下有效**。原因已定位：真实文档的 href 大量重复，线性扫描通常
在前几个元素就命中（平均扫描长度 ≈ 重复度，而不是锚点总数），而文档解析本身是线性
且占大头。这是一条 asymptotic insurance，不是真实文档的日常提速。

## 差分测试（G2）

`tests/test_diff.py` 现场用 `patch -p1 -R` 把 `patch.diff` 反向应用到一个副本，
得到**上游原版**，再与打补丁版本逐字节比较 `HTML2Text.handle()` 的输出。

- **独立样本数 N = 2600**（去重方式：`sha256(html + json(options))`，重复输入不计入）。
  另有 400 组直接对 `previousIndex()` 的随机 `self.a` 状态机对比（同 0 差异）。
- **0 处不一致**，逐字节相等（字符串 `!=` 比较，无近似）。
- 覆盖：空文档、无锚点、单锚点、重复 href、`title` 四种存在组合、`#frag`、
  `mailto:`、`<img src>`、3000 字符超长 href、非 ASCII href/文本、嵌套 `<a>`、
  表格内锚点，以及 `inline_links` / `ignore_links` / `protect_links` /
  `images_to_alt` / `links_each_paragraph` / `body_width` 各选项组合。

## 质量闸门（逐条 + 复现命令）

| 闸门 | 结论 | 复现命令 |
| --- | --- | --- |
| G1 上游测试全绿 | ✅ `196 passed`（改动后重跑原命令） | `python -m pytest test -q -p no:cacheprovider` |
| G2 差分一致 | ✅ 2600 独立样本，0 差异 | `python tests/test_diff.py` |
| G3 中位加速 ≥1.15× | ✅ **2.52×**（300/900/2700 的中位） | `python benchmark/bench.py --impl optimized --sweep --real-dir test` |
| G3b 真实语料加速 | ⚠️ 0.977–1.001×（上游 fixture 0.993×）→ 已按上文明写“仅合成负载有效” | 同上（`--real /usr/share/doc/nodejs/api/fs.html` 等） |
| G4 最大规模不退化 | ✅ 5.70× ≥ 0.95× | 同上 |
| G5 内存不变差 | ✅ 峰值 RSS 15232 KB → 15616 KB = **1.025×** ≤ 1.10×（`/usr/bin/time -v`） | `PYTHONPATH=<tree> /usr/bin/time -v python -c "..."` |

baseline 数字来自未打补丁的上游快照（本仓库第一个 commit，或 `patch -p1 -R` 反向应用）。

## 环境

- CPU: AMD EPYC 7K62 48-Core Processor（容器 4 核）
- 内存: 3723 MB total
- 运行时: **CPython 3.12.3**（GCC 13.3.0）；本机只有这一个解释器，无法给出多解释器交叉
- 种子: `20261102`（`benchmark/bench.py` 中固定，写入产物）
- 计时: `time.perf_counter()`；每规模 warmup 3 + 计时 7（sweep 为 warmup 2 + 计时 5）

## 上游回馈

本改动是 `previousIndex` 的一次局部 memo，未改变公开 API；但真实语料收益 ≈1.0×，
不满足 `state/upstream-pr.json` 契约里 `realistic_input` 上站得住的收益要求，
**因此交 0 个 PR**。

## 目录

```
benchmark/bench.py        基准 + 标度指数证书（可跑 baseline/optimized 两版）
benchmark/baseline.json   基线与上游测试命令、环境
benchmark/optimized.json  改动后同一份 bench 的结果
benchmark/raw/*.json      每个采样一份原始文件
tests/test_diff.py        反向补丁构造上游原版 + 2600 组逐字节差分
patch.diff                相对上游 5cf85510 的改动（55+/11-）
LICENSE                   上游 GPL-3.0-or-later 原文 + 来源与改动范围说明
README.upstream.md        上游原始 README（保留）
```
