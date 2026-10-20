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
