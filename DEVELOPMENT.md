# 开发与维护说明

面向想改代码、二次开发，或者让 AI 助手帮你部署的人。
只想用起来的话看 [README.md](README.md) 就够了。

---

## 技术栈

- **Flask** 提供 Web 服务与模板渲染，无前端构建流程（原生 HTML/CSS/JS）
- **单文件主程序** `novel-manager.py`，不拆包、不依赖安装
- **纯 JSON 存储**，无数据库、无 ORM、无迁移脚本
- 服务端渲染 + 少量 fetch 接口，没有 SPA

选择这个形态的原因：单文件便于携带和备份，JSON 便于手改和 grep，
对单人本地使用（几千本书）完全够用，不需要引入更重的基础设施。

---

## 依赖

`requirements.txt` 里五个包，**全部是硬依赖**：

| 包 | 用途 | 移除后果 |
|---|---|---|
| `flask` | Web 框架 | 无法启动 |
| `chardet` | txt 编码探测 | 无法启动 |
| `psutil` | CPU / 内存占用采集 | 无法启动 |
| `pystray` | 系统托盘图标 | 无法启动 |
| `Pillow` | 绘制托盘图标（pystray 依赖） | 无法启动 |

主程序在顶层无条件 `import` 这五个，没有 try/except 降级。
要做无托盘环境（如服务器）的移植，必须改这里，不是改配置能解决的。

---

## 运行形态的约束

这是**桌面单机应用**，几个设计决定都基于这个前提：

| 机制 | 作用 | 影响移植 |
|---|---|---|
| pystray 托盘图标 | 常驻后台，右键菜单退出 | 无 GUI 环境会失败 |
| socket 单实例锁 | 防止重复启动多个实例 | 容器内多副本会冲突 |
| 默认监听 `127.0.0.1` | 不对外暴露 | 局域网访问需改 `app_host` |
| 无登录鉴权 | 单人使用，不需要 | 多用户场景必须用 Docker 版 |

所以它**不适合**直接部署到服务器 / 容器 / 多用户环境。
需要那种形态请用 [Docker 版](https://github.com/ufowangjian-cmyk/novel-manager)。

---

## data/ 目录

程序启动时按需自动创建，全部是 JSON（除日志）：

| 文件 | 内容 | 缺失时 | 能否随代码分发 |
|---|---|---|---|
| `config.json` | 用户配置 | 用内置默认值，正常启动 | ❌ 含个人路径 |
| `novel_cache.json` | 扫描缓存（可达 10MB+） | 重新扫描生成 | ❌ 可重建，体积大 |
| `reading_records.json` | 阅读进度、已读标记 | 视为空记录 | ❌ 隐私 |
| `novel_manager.log` | 运行日志 | 自动创建 | ❌ |
| `tag_rules.json` | 标签规则（关键词 / 别名 / 派生） | 视为空规则 | ⭕ 属个性化积累 |
| `image_mapping.json` | 配图映射 | 视为空映射 | ⭕ |
| `media_ignore.json` | 媒体忽略清单 | 视为空清单 | ⭕ |
| `emoji_mapping.json` | 表情映射 | 视为空映射 | ⭕ 需配合 `static/emojis/` |

所有 JSON 都通过 `load_json_file()` 读取，**文件不存在时返回默认值而不抛异常**，
所以空 `data/` 目录也能正常启动，运行中会按需重新写入。

例外：`emoji_mapping.json` 由可选的 `emoji_editor_v2.py` 维护，主程序只读不写。

---

## 扫描机制

1. 遍历 `novel_dir`（可选递归 `scan_subdirectories`）
2. 跳过命中 `exclude_patterns` 的文件、超过 `max_file_size_mb` 的文件
3. 用 `chardet` 探测编码后读取文件头部，解析书名 / 作者 / 站点 / 标签 / 简介
4. 计算内容指纹，与 `novel_cache.json` 比对
5. mtime 未变的文件直接复用缓存项（增量）

`scan.lock` 用于互斥，避免并发扫描。首次全量扫描是 IO 密集型，
耗时与文件数量成正比，之后增量通常 1–2 秒。

---

## 阅读页渲染

**规则与 Docker 版同源，不在本文重复。** 本版阅读页的用途是「校验内容对不对」——
它拿同一份文本、按同一套规则渲染，一旦 Docker 版的高亮错位、括号没配上、缩进跑偏，
在这里用同一章就能看出来。所以引号括号高亮、跨行配对、正文缩进这些**必须保持一致**，
分岔就等于放弃这层校验。细则见 Docker 版仓库 `DEVELOPMENT.md` 的「阅读页渲染」一节。

**列表状态必须一路透传**：页码、筛选（`search` `author` `tag` `site`）、排序（`sort` `order`）
从首页卡片一路带到详情页和阅读页。返回按钮统一调 Jinja 全局函数 `list_back_url()`
（本版与 Docker 版同名同行为），别在模板里手拼 `/?page=xx&search=yy` —— 会漏参数，
中文和 `&` 不做编码还会被截断。随机推荐卡片这种「入口本身没状态」的地方用
`detail_url_with_state()` / `read_url_with_state()` 生成链接，「换一本」时前端会把
当前 `location.search` 一起发给接口。

本版的差异只在体验层和接入方式上：

| 项目 | 本版 | Docker 版 |
|---|---|---|
| 画廊阈值 | `CONFIG.gallery_min_images`（配置页，全局） | `user_prefs.gallery_min_images`（每用户） |
| 画廊按钮 | 纯文字「竖向展开 / 收起为画廊」 | `icon()` sprite（`list` / `layout-grid`） |
| 图标体系 | 配置页 / 标签页用 emoji，没有 `_icons.html` | 全部走 sprite，照抄 `{{ icon() }}` 会白屏 |
| 静态资源版本号 | 模板里**手写** `?v={{ css_version }}` | `url_for` 已全局替换，**绝不手写** |
| 移动端适配 | 不做（桌面工具） | 做 |
| 阅读主题 / 翻页动效 / 进度记忆 | 不追（校验用不上） | 沉浸阅读的组成部分 |

---

## 简介与预览提取

`extract_intro_clean()`：从「简介：」行（没有就取元数据之后）到**第一个章节标题**为止。
空行保留（用于分段），图片行原样保留，纯符号行与元数据行剔除；整段超过 3000 字就判为
「无简介」——那说明已经截到正文了。预览用 `extract_preview_clean()`，上限 6 行 / 300 字。

边界判定用 `is_chapter_line_strict()`，比 `LEVEL*_PATTERN` 更严：裸词
（楔子 / 引子 / 引言 / 前言 / 序言 / 正文 / 番外 / 后记 / 尾声）后面必须真的像标题——

- 整行就是这个裸词；或
- 裸词 + **冒号** + 短标题（≤30 字、不带句读）；或
- 裸词 + 短标签（≤8 字，如「正文 第一章」）

第三条以前也管着冒号式写法，结果「楔子：老婆的出轨使我发现自己的淫妻癖」（冒号后 17 字）
被判成正文，整章被吃进简介（2026-11-10 修）。没冒号的分支保持 8 字上限，避免把
「正文部分是…」这类句子吃成标题。

## 标签提取

规则与 Docker 版同源（关键词 655 条、四路信号打分、否定上下文、派生标签），
细则见 Docker 版 `DEVELOPMENT.md` 的「标签提取」一节。本版**已经补齐 `score_tags()`**
（2026-11-08）：以前只有 `derive_tags` + `clean_tags`，标签顺序来自 `set` 迭代，
每次重启都可能变；现在与 Docker 一样按权重稳定排序。

改完提取规则同样要重扫才生效（缓存按 mtime + 文件哈希复用，旧书不会自动重算）。

---

## 自测

- 语法检查：`python -m py_compile novel-manager.py`；前端脚本 `node --check`
- 用**系统 Python**（3.13，依赖齐全），别用 IDE 或助手自带的解释器——可能缺 `chardet`，
  启动一秒即挂，容易误判成代码有问题
- 模板/视图改动可以不起服务：`spec_from_file_location` 载入主程序 +
  `app.test_request_context()` 调视图函数，直接看渲染出的 HTML
- 程序**由你手动启动**（双击 `start_novel_manager.vbs`）。改 Python 要重启；
  改模板和静态文件刷新即可（静态资源有 30 天强缓存，必要时 Ctrl+F5）

---

## 常见的二次开发点

| 想改什么 | 位置 |
|---|---|
| 端口 / 监听地址 | `data/config.json` 的 `app_host` / `app_port` |
| 默认配置 | `DEFAULT_CONFIG` 字典 |
| 文件扫描过滤规则 | `exclude_patterns` 及各扫描函数中的后缀判断 |
| 章节切分正则 | 查找章节解析相关的正则常量 |
| 阅读页排版 | `templates/read_chapter.html` + `static/css/reader.css` |
| 主题色 | `static/css/` 下的 CSS 变量 |
| 标签匹配逻辑 | 标签规则加载与匹配函数 |

改完 Python 代码**重启程序**生效；改模板和静态资源刷新页面即可（静态文件有缓存，必要时 Ctrl+F5）。

---

## 自动化部署（给 AI 助手）

如果你是被要求部署这个项目的 AI 助手，按下面顺序执行：

**前提判断**：本项目面向 Windows 桌面、单人本地使用。
如果用户要求在服务器 / 容器 / NAS 上部署，直接说明这不被支持
（托盘图标和单实例锁是为桌面设计的），并引导他用
[Docker 版](https://github.com/ufowangjian-cmyk/novel-manager)，不要尝试改造本版。

1. **确认 Python 版本** —— 需要 3.9+
   ```bash
   python --version
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```
   五个包都不能省，尤其别漏 `Pillow` 和 `pystray`。

3. **确认小说目录** —— 问用户要**绝对路径**并验证存在，不要沿用占位默认值。

4. **写配置** —— `data/config.json` 只需写要覆盖的键：
   ```json
   {
     "novel_dir": "<用户的小说目录绝对路径>",
     "editor_path": "notepad.exe"
   }
   ```
   编码必须是 UTF-8 无 BOM。

5. **启动**
   ```bash
   python novel-manager.py
   ```
   程序会补齐其余配置、创建缺失的数据文件、后台扫描并打开浏览器。
   启动后常驻系统托盘，右键可退出。

6. **验证**
   - `http://127.0.0.1:5000` 能打开
   - `data/novel_manager.log` 里有扫描进度
   - 失败时日志有具体原因

**注意**：不要删除 `data/` 目录（含阅读记录和标签规则）；
修改 `config.json` 后需重启，或在 `/config` 页面保存以触发热重载。
