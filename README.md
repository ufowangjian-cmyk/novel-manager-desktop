# 小说管理器（Novel Manager）

把散落在硬盘各处的 TXT 小说，整理成一个能搜索、能打标签、能接着看的私人书库。

纯本地运行的网页应用：载入桌面后打开浏览器就能用，不联网、不上传任何数据、不需要数据库。

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

<!-- 建议在这里插一张首页截图（书库列表），视觉上比任何文字都直观 -->

---

## 它解决什么问题

TXT 小说下载下来通常是一堆文件名混乱的文本：`《某某》作者：某某.txt`、`某某完结.txt`、`新建文本文档.txt`。
想找一本书只能靠翻文件夹，看到哪一章也全靠记忆。

这个工具会扫描你指定的目录，从文件头部解析出书名、作者、标签、简介、章节，
整理成一个可以检索和筛选的书库；阅读进度自动保存，下次打开直接续上。

---

## 功能

**书库管理**

- 扫描指定目录下的 `.txt` / `.TXT` 文件，自动识别编码（UTF-8 / GBK / GB18030 / Big5 / UTF-16）
- 从文件头部解析书名、作者、来源站点、标签、简介、章节数、字数
- 按书名、作者、标签、站点、字数、日期排序与筛选
- 增量扫描：文件修改时间没变就复用缓存，不会重复解析

**阅读**

- 网页内分章阅读，自动切分章节（支持三级章节标题）
- 阅读进度自动保存，下次打开自动定位
- 需要改原文时，可调用外部编辑器打开文件

**标签**

- 关键词规则：正文或元数据命中关键词即打标签
- 别名映射：把不同写法归一到同一个主标签
- 派生规则：根据已有标签推导上级标签
- 规则支持导入、导出、重置

**其他**

- 配图 / 视频 / 音频文件夹的检测与关联
- 缓存健康检查、缺失文件检查
- 阅读记录与已读标记
- 运行日志查看

---

## 快速开始

### 1. 环境要求

- Python 3.9 或更高（开发测试使用 3.13 / 3.14）
- Windows / Linux / macOS 均可，Windows 上额外提供系统托盘图标
- 无需数据库

### 2. 获取并安装

```bash
git clone https://github.com/ufowangjian-cmyk/novel-manager-desktop.git
cd novel-manager-desktop
pip install -r requirements.txt
```

### 3. 配置小说目录

首次运行会自动生成 `data/config.json`，但默认路径只是占位。
把 `novel_dir` 改成你自己的小说文件夹（**绝对路径**）：

```json
{
  "novel_dir": "D:\\novels"
}
```

两种改法任选：

- 直接编辑 `data/config.json`
- 或者先启动，再在网页的「设置」页里改

> 配置项**不需要写全**，只写要覆盖的键即可，其余会自动用默认值补齐。
> 文件必须保存为 **UTF-8 无 BOM**，否则含中文的路径会读不出来。

### 4. 启动

**Windows**：双击 `start_novel_manager.vbs`，它会等服务器就绪后自动打开浏览器。

**命令行（任意平台）**：

```bash
python novel-manager.py
```

浏览器访问 <http://127.0.0.1:5000> 。首次扫描会读一遍所有文件的开头，之后都是增量。

---

## 界面概览

| 页面 | 用途 |
|---|---|
| 首页 `/` | 书库列表，支持多条件筛选与排序 |
| 详情页 `/novel/<id>` | 单本书的元数据、章节列表、标签管理 |
| 阅读页 `/read/<id>` | 分章阅读，字体、行距、主题可调 |
| 标签管理 `/tags` | 关键词规则、别名、派生规则 |
| 设置 `/config` | 目录、端口、主题、扫描策略等 |

---

## 配置项

| 键 | 默认值 | 说明 |
|---|---|---|
| `novel_dir` | `~/Documents/novels` | 小说所在文件夹，**必须改** |
| `editor_path` | 空 | 外部编辑器路径，留空则「用编辑器打开」不可用 |
| `exclude_patterns` | `["【废弃】","【备份】","temp_"]` | 文件名含这些串则跳过 |
| `app_host` | `127.0.0.1` | 监听地址 |
| `app_port` | `5000` | 监听端口 |
| `scan_subdirectories` | `false` | 是否扫描子目录 |
| `auto_scan_on_start` | `true` | 启动时自动扫描 |
| `scan_interval_hours` | `0` | 定时扫描间隔，0 为关闭 |
| `max_file_size_mb` | `100` | 超过此大小的文件跳过 |
| `per_page` | `100` | 列表每页条数 |
| `words_per_page` | `8000` | 阅读页每页字数 |
| `font_size` | `16` | 阅读页字号 |
| `line_height` | `1.8` | 阅读页行高 |
| `theme` | `auto` | `auto` / `light` / `dark` |
| `auto_save_progress` | `true` | 自动保存阅读进度 |
| `auto_tag_enabled` | `true` | 启用自动打标签 |
| `enable_derived_tags` | `true` | 启用标签派生 |
| `auto_backup_enabled` | `true` | 启用自动备份 |
| `debug_mode` | `false` | 输出 DEBUG 级日志 |

---

## 关于素材

本仓库**不包含** `static/emojis/`（表情包）和 `static/images/`（头图）——
这些素材来源网络、授权不明，不适合随代码分发。

缺了不影响使用：程序照常启动、扫描、检索、阅读，只是表情面板和头图不显示。

想恢复视觉效果，把文件放回对应目录即可：

```
static/emojis/    .gif / .png 表情文件，文件名需与 data/emoji_mapping.json 的键对应
static/images/    头图图片
```

---

## 常见问题

**扫描不出小说？**
检查 `novel_dir` 是否为绝对路径、目录是否存在、是否有读取权限。
另外确认 `exclude_patterns` 没有误伤你的文件名。

**中文书名显示乱码？**
`config.json` 必须保存为 UTF-8（无 BOM）编码。这是最常见的问题。

**端口 5000 被占用？**
改 `config.json` 里的 `app_port`，重启即可。

**首次扫描很慢？**
首次全量扫描要读每个文件开头并计算内容指纹，耗时与文件数量成正比。
实测 5000 本、约 2GB 正文，全量扫描约 40 秒；之后增量扫描通常 1–2 秒。

**数据会不会丢？**
所有状态都在 `data/` 目录下的 JSON 文件里，直接备份这个目录就行。
其中 `novel_cache.json` 是扫描缓存，可以重建，备份时可以排除。

**想局域网访问？**
把 `app_host` 改成 `0.0.0.0`。但要注意：**本程序没有登录鉴权**，
局域网内任何人都能访问和修改你的书库。需要多用户和登录功能请用 Docker 版。

---

## 目录结构

```
novel-manager/
├── novel-manager.py          # 主程序
├── requirements.txt          # 依赖
├── start_novel_manager.vbs   # Windows 启动脚本
├── emoji_editor_v2.py        # 表情映射编辑器（可选工具）
├── novel-icon.ico            # 图标
├── templates/                # 网页模板
├── static/                   # CSS / JS / 素材
└── data/                     # 运行时数据（自动创建，不进版本库）
```

运行时数据说明、架构细节、二次开发注意事项见 **[DEVELOPMENT.md](DEVELOPMENT.md)**。

---

## 相关项目

- **[novel-manager](https://github.com/ufowangjian-cmyk/novel-manager)** —— 同一套功能的 Docker 版，
  多用户、带登录鉴权，适合部署在 NAS 上让家人共用

---

## 许可

[MIT](LICENSE)
