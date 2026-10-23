import sys
import os
import random
import logging
import json
import traceback
import hashlib
import time
import threading
import queue
import re
import secrets
import mimetypes
import codecs
import tempfile
import chardet
import subprocess
from bisect import bisect_left
from collections import OrderedDict, Counter
from datetime import datetime
from html import escape as html_escape
from flask import Flask, render_template, render_template_string, request, redirect, url_for, jsonify, session, send_file, g
import psutil

image_cache = OrderedDict()
_JSON_WRITE_LOCK = threading.Lock()

# ===================== 彩色输出支持 =====================
class Colors:
    """控制台颜色代码"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def cprint(text, color='GREEN', bold=False, end='\n'):
    """彩色打印（自动检测终端支持）"""
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            use_color = True
        except:
            use_color = False
    else:
        use_color = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    
    if use_color:
        color_code = getattr(Colors, color, Colors.GREEN)
        bold_code = Colors.BOLD if bold else ''
        print(f"{bold_code}{color_code}{text}{Colors.ENDC}", end=end)
    else:
        print(text, end=end)

# ===================== 数据目录配置 =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"✅ 已创建数据目录: {DATA_DIR}")

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
TAG_RULES_FILE = os.path.join(DATA_DIR, 'tag_rules.json')
READING_RECORD_FILE = os.path.join(DATA_DIR, 'reading_records.json')
CACHE_FILE = os.path.join(DATA_DIR, 'novel_cache.json')
SCAN_STATS_FILE = os.path.join(DATA_DIR, 'scan_stats.json')
LOG_FILE = os.path.join(DATA_DIR, 'novel_manager.log')
EMOJI_MAPPING_FILE = os.path.join(DATA_DIR, 'emoji_mapping.json')
IMAGE_MAPPING_FILE = os.path.join(DATA_DIR, 'image_mapping.json')
MEDIA_IGNORE_FILE = os.path.join(DATA_DIR, 'media_ignore.json')


# ===================== 通用 JSON 文件操作 =====================
def load_json_file(file_path, default=None):
    """通用 JSON 文件加载"""
    if default is None:
        default = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 加载文件失败 {file_path}: {e}")
            return default
    return default


def save_json_file(file_path, data, indent=2):
    """通用 JSON 文件保存（原子写入，避免中断产生半截文件）"""
    tmp_path = f"{file_path}.tmp"
    try:
        parent = os.path.dirname(os.path.abspath(file_path))
        os.makedirs(parent, exist_ok=True)
        with _JSON_WRITE_LOCK:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        print(f"❌ 保存文件失败 {file_path}: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def is_path_within(base_dir, target_path):
    """判断 target_path 是否位于 base_dir 内（防止 ../ 越界）。"""
    try:
        base = os.path.normcase(os.path.realpath(str(base_dir)))
        target = os.path.normcase(os.path.realpath(str(target_path)))
        return os.path.commonpath([base, target]) == base
    except (TypeError, ValueError):
        return False


def safe_join(base_dir, *paths):
    """在 base_dir 下安全拼接路径，越界时抛出 ValueError。"""
    target = os.path.join(base_dir, *paths)
    if not is_path_within(base_dir, target):
        raise ValueError(f"路径越界: {target}")
    return os.path.realpath(target)


def safe_basename(name):
    """只取文件名，兼容 URL/Windows 路径中的反斜杠。"""
    return os.path.basename(str(name or '').replace('\\', '/'))


# ===================== 配置加载 =====================
DEFAULT_CONFIG = {
        "novel_dir": os.path.join(os.path.expanduser("~"), "Documents", "novels"),
        "editor_path": "",
        "exclude_patterns": ["【废弃】", "【备份】", "temp_"],
        "app_host": "127.0.0.1",
        "app_port": 5000,
        "font_size": 16,
        "line_height": 1.8,
        "theme": "auto",
        "indent_paragraph": True,
        "auto_save_progress": True,
        "show_word_count": True,
        "scan_interval_hours": 0,
        "max_file_size_mb": 100,
        "scan_subdirectories": False,
        "per_page": 100,
        "words_per_page": 8000,
        "max_tags_display": 3,
        "date_format": "YYYY-MM-DD",
        "auto_scan_on_start": True,
        # 启动时预加载最近阅读的书（桌面版专属：内存充裕，开机即续读）
        "preload_recent_enabled": True,
        "preload_recent_count": 5,
        "auto_backup_enabled": True,
        "backup_interval_days": 7,
        "max_backups": 5,
        "debug_mode": False,
        "auto_tag_enabled": True,
        "enable_derived_tags": True,
        "custom_tags": [],
        "default_sort_by": "title",
        "default_sort_order": "asc",
        # —— 分元素字体：正文 + 标题 + 阅读器高亮标点（空字符串 = 跟随正文 / 沿用 CSS 默认）——
        # 对齐 Docker 版「自定义高亮标点符号字体」：每种高亮类型可单独配字体。
        "body_font_family": "",              # 正文字体（空 = 系统默认）
        "title_font_family": "'HYWenHei-55W', '汉仪文黑-55W', '汉仪文黑内置', 'Segoe UI', '微软雅黑', serif",
        "double_quote_font_family": "",   # 双引号 "「」
        "single_quote_font_family": "",   # 单引号 '『』
        "bracket_font_family": "",        # 圆括号 （）()
        "square_bracket_font_family": "", # 方头括号 【】
        "square_bracket_1_font_family": "",  # 方括号 [] ［］
        "hollow_bracket_font_family": "", # 空心括号 〖〗
        "book_font_family": "",           # 书名号 《》
        # —— 分元素 加粗/斜体：阅读页 applyHlStyle() 始终按生效值注入 font-weight / font-style（!important），
        #    由配置页 / 阅读抽屉 / localStorage 全权驱动；reader.css 高亮类不再写死字重与字形，避免两者互相打架。
        "body_bold": False,            "body_italic": False,          # 正文默认不加粗/不斜体
        "title_bold": True,            "title_italic": False,
        "double_quote_bold": False,    "double_quote_italic": False,
        "single_quote_bold": False,    "single_quote_italic": False,
        "bracket_bold": True,          "bracket_italic": False,           # 圆括号（CSS 不再写死，由配置驱动）
        "square_bracket_bold": False,  "square_bracket_italic": False,    # 方头括号（由配置驱动）
        "square_bracket_1_bold": False,"square_bracket_1_italic": False,  # 方括号（由配置驱动）
        "hollow_bracket_bold": False,  "hollow_bracket_italic": False,    # 空心括号（由配置驱动）
        "book_bold": False,            "book_italic": False,              # 书名号（由配置驱动；默认 normal，可强制 bold）
    }


def get_default_config():
    """返回默认配置的浅拷贝，避免调用方修改默认值。"""
    return {
        key: (value.copy() if isinstance(value, (list, dict)) else value)
        for key, value in DEFAULT_CONFIG.items()
    }


def load_config():
    """加载配置文件"""
    default_config = get_default_config()

    config = load_json_file(CONFIG_FILE, default_config)
    for key in default_config:
        if key not in config:
            config[key] = default_config[key]
    return config


CONFIG = load_config()

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('NOVEL_MANAGER_SECRET_KEY') or secrets.token_hex(32)


@app.before_request
def csrf_protect():
    """对所有写请求做 CSRF 校验。前端 common.js 会自动带 X-CSRF-Token。"""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None
    if request.path == '/api/csrf-token':
        return None

    expected = session.get('csrf_token')
    provided = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token') or ''
    if not expected or not provided or not secrets.compare_digest(str(expected), str(provided)):
        return jsonify({'success': False, 'message': 'CSRF 校验失败，请刷新页面后重试'}), 403


@app.route('/api/csrf-token')
def api_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return jsonify({'csrf_token': session['csrf_token']})

print("📋 当前配置:")
print(f"   小说目录: {CONFIG['novel_dir']}")
print(f"   编辑器路径: {CONFIG['editor_path']}")
print(f"   服务地址: {CONFIG['app_host']}:{CONFIG['app_port']}")
print(f"   调试模式: {CONFIG['debug_mode']}")

# ==================== 预编译正则表达式 ====================
LEVEL1_PATTERN = re.compile(r'^\s*(?:第(?:\d+|[〇零一二三四五六七八九十百千万]+)[册集卷部]|[上下前后中终序][册集卷部])\s*[：:\s·]?\s*.*$')
LEVEL2_PATTERN = re.compile(r'^\s*(?:第(?:\d+|[〇零一二三四五六七八九十百千万]+)[篇章]|[上下前后中终序][篇章]|楔子|引子|引言|前言|序言|正文|番外|后记|尾声)\s*[：:\s·]?\s*.*$')
LEVEL3_PATTERN = re.compile(r'^\s*(?:第(?:\d+|[〇零一二三四五六七八九十百千万]+)[节回目幕])\s*[：:\s·]?\s*.{1,30}$')

# ===================== 日志配置 =====================
DEBUG_MODE = CONFIG.get('debug_mode', False) or os.environ.get('DEBUG_MODE', 'false').lower() == 'true'

# 日志文件滚动：单文件最大 5MB，保留 3 个备份（防止无限膨胀）
from logging.handlers import RotatingFileHandler
handlers = [RotatingFileHandler(LOG_FILE, encoding='utf-8', maxBytes=5 * 1024 * 1024, backupCount=3)]
if DEBUG_MODE:
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    handlers.append(console_handler)
    print("🔧 调试模式已启用，控制台输出可见")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=handlers
)
logger = logging.getLogger(__name__)

# 🔥 屏蔽 werkzeug 自带的访问日志（改为下方自定义的、更有用的访问日志）
logging.getLogger('werkzeug').setLevel(logging.WARNING)


# ===== 自定义访问日志（每次请求记录 方法/路径/状态码/耗时/IP）=====
# 排除：静态资源、高频轮询(扫描进度)、日志页自身（避免刷屏）
_ACCESS_LOG_EXCLUDES = ('/static/', '/api/scan_progress', '/logs', '/logs/download', '/favicon.ico')

@app.before_request
def _log_request_start():
    g.request_start = time.time()

@app.after_request
def log_request(response):
    try:
        path = request.path
        if not path.startswith(_ACCESS_LOG_EXCLUDES):
            duration_ms = int((time.time() - getattr(g, 'request_start', time.time())) * 1000)
            logger.info(
                f"访问 {request.method} {path} -> {response.status_code} "
                f"({duration_ms}ms) IP={request.remote_addr}"
            )
    except Exception:
        pass
    return response

print(f"程序启动时间: {datetime.now()}")
print(f"当前工作目录: {os.getcwd()}")
print(f"调试模式: {DEBUG_MODE}")

# ==================== 加载标签规则 ====================
def load_tag_rules():
    """加载标签规则配置文件（包含关键词）"""
    DEFAULT_KEYWORDS = [
        "连载", "完结", "太监", "断更", "番外", "同人", "原创", "翻译", "改编",
        "都市", "校园", "职场", "官场", "仙侠", "玄幻", "奇幻", "武侠", "穿越",
        "末世", "无限流", "恐怖", "悬疑", "纯爱", "出轨"

    ]
    DEFAULT_ALIASES = {
        "完结": ["完"],
        "连载": ["连载中", "更新中"],
        "太监": ["断更", "烂尾"]
    }
    DEFAULT_IMPLICATIONS = {
        "后宫": ["一男多女"],
        "百合": ["女同"],
        "催眠": ["精神控制"],
        "穿越": ["重生"],
        "重生": ["穿越"],
        "无限流": ["末世", "异界"],
        "异界": ["无限流", "末世"],
        "末世": ["无限流", "异界"],
        "恐怖": ["悬疑"],
        "悬疑": ["恐怖"]}
    
    DEFAULT_NEGATION_PATTERNS = []
    
    default_rules = {
        "implications": DEFAULT_IMPLICATIONS,
        "aliases": DEFAULT_ALIASES,
        "keywords": DEFAULT_KEYWORDS,
        "negation_patterns": DEFAULT_NEGATION_PATTERNS
    }
    
    rules = load_json_file(TAG_RULES_FILE, default_rules)
    
    for key, default in default_rules.items():
        if key not in rules or not rules[key]:
            rules[key] = default
            print(f"⚠️ {key} 字段缺失，已使用默认值")
    
    print(f"✅ 从 {TAG_RULES_FILE} 加载标签规则")
    print(f"   🔑 识别关键词: {len(rules.get('keywords', []))} 个")
    print(f"   🔗 别名映射: {len(rules.get('aliases', {}))} 组")
    print(f"   📌 派生规则: {len(rules.get('implications', {}))} 条")
    return rules


TAG_RULES = load_tag_rules()
TAG_IMPLICATIONS = TAG_RULES.get('implications', {})
TAG_ALIASES = TAG_RULES.get('aliases', {})
TAG_KEYWORDS = [str(k) for k in TAG_RULES.get('keywords', [])]

TAG_KEYWORDS_LOWER = []
TAG_ALIAS_TO_MAIN = {}


def refresh_tag_rule_caches():
    """重建标签关键词/别名查询缓存。规则变化后必须调用。"""
    global TAG_KEYWORDS_LOWER, TAG_ALIAS_TO_MAIN
    TAG_KEYWORDS_LOWER = [str(k).lower() for k in TAG_KEYWORDS]
    lookup = {}
    for main_tag, aliases in (TAG_ALIASES or {}).items():
        main = str(main_tag)
        lookup[main.lower()] = main
        for alias in (aliases or []):
            alias_text = str(alias).strip()
            if alias_text:
                lookup[alias_text.lower()] = main
    TAG_ALIAS_TO_MAIN = lookup


refresh_tag_rule_caches()

# ===== 排序规则设置 =====
if sys.platform != 'win32':
    try:
        import locale
        locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')
        print("✅ 已设置中文排序规则")
    except:
        try:
            locale.setlocale(locale.LC_ALL, 'C.UTF-8')
            print("✅ 已设置 C.UTF-8 排序规则")
        except:
            print("⚠️ 无法设置 locale，将使用默认排序规则")

# ===================== 从配置文件读取设置 =====================
NOVEL_DIR = CONFIG.get('novel_dir', os.path.join(os.path.expanduser('~'), 'Documents', 'novels'))
EMEDITOR_PATH = CONFIG.get('editor_path', '')
PER_PAGE = CONFIG.get('per_page', 100)
WORDS_PER_PAGE = CONFIG.get('words_per_page', 8000)


def load_reading_records():
    return load_json_file(READING_RECORD_FILE, {})


def save_reading_records(records):
    return save_json_file(READING_RECORD_FILE, records)


def load_scan_stats():
    """读取上次扫描的统计信息（不存在时返回空字典）。"""
    return load_json_file(SCAN_STATS_FILE, {})


def save_scan_stats(stats, merge=True):
    """持久化扫描统计到 data/scan_stats.json。

    merge=True（默认）时与现有内容合并：增量扫描只更新 last_scan_* 等字段，
    不会把 last_full_scan_time 冲掉。置 None 的键仍然会写入（表示显式清空）。
    """
    if merge:
        merged = load_scan_stats()
        if not isinstance(merged, dict):
            merged = {}
        merged.update(stats)
        stats = merged
    return save_json_file(SCAN_STATS_FILE, stats)


def check_interrupted_scan():
    """启动时检查上次扫描是否被中断（程序退出/被杀，扫描线程随之消失）。

    扫描开始时会在 scan_stats.json 写 scan_in_progress 标记，正常结束时清除。
    如果启动时还留着它，说明上一次扫描没能跑完 —— 统计数据不可信，且
    last_scan_type 可能停在「增量」，让用户误以为全量从未执行过。
    """
    try:
        stats = load_scan_stats()
        if not isinstance(stats, dict):
            return
        pending = stats.get('scan_in_progress')
        if not pending:
            return

        started = pending.get('start_time')
        scan_type = pending.get('type') or 'unknown'
        stats['scan_in_progress'] = None
        stats['last_scan_interrupted'] = {
            'type': scan_type,
            'start_time': started,
            'detected_at': time.time(),
        }
        save_scan_stats(stats, merge=False)

        from datetime import datetime
        when = datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S') if started else '未知时间'
        label = '全量扫描' if scan_type == 'full' else '增量扫描'
        logger.warning(f"⚠️ 检测到上次{label}未完成（开始于 {when}），程序可能在扫描过程中退出")
    except Exception as e:
        logger.warning(f"检查扫描中断状态失败（已跳过）：{e}")


def get_file_hash(file_path):
    """获取文件的快速哈希"""
    try:
        stat = os.stat(file_path)
        return f"{stat.st_size}_{getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))}"
    except Exception as e:
        print(f"⚠️ 获取文件哈希失败：{e}")
        return None


LINE_INDEX_STEP = 1000
LINE_INDEX_MAX = 100
LINE_BREAK_RE = re.compile(r'\r\n|\r|\n')
line_index_cache = OrderedDict()


def build_line_index(raw_data, encoding):
    """基于原始字节构建稀疏行偏移索引。

    只记录 1、1001、2001... 行的字节偏移，读取任意区间时
    从最近检查点向前扫描最多 LINE_INDEX_STEP 行，避免整本读入内存。
    """
    enc = (encoding or 'utf-8').lower()
    offsets = [0]
    line_count = 1
    n = len(raw_data)

    def _mark(offset):
        nonlocal line_count
        line_count += 1
        if line_count % LINE_INDEX_STEP == 1:
            offsets.append(offset)

    if enc.startswith('utf-16-le'):
        i = 0
        while i + 1 < n:
            a, b = raw_data[i], raw_data[i + 1]
            if a == 0x0A and b == 0x00:
                i += 2
                _mark(i)
            elif a == 0x0D and b == 0x00:
                if i + 3 < n and raw_data[i + 2] == 0x0A and raw_data[i + 3] == 0x00:
                    i += 4
                else:
                    i += 2
                _mark(i)
            else:
                i += 2
    elif enc.startswith('utf-16-be'):
        i = 0
        while i + 1 < n:
            a, b = raw_data[i], raw_data[i + 1]
            if a == 0x00 and b == 0x0A:
                i += 2
                _mark(i)
            elif a == 0x00 and b == 0x0D:
                if i + 3 < n and raw_data[i + 2] == 0x00 and raw_data[i + 3] == 0x0A:
                    i += 4
                else:
                    i += 2
                _mark(i)
            else:
                i += 2
    else:
        i = 0
        while i < n:
            b = raw_data[i]
            if b == 0x0A:
                i += 1
                _mark(i)
            elif b == 0x0D:
                if i + 1 < n and raw_data[i + 1] == 0x0A:
                    i += 2
                else:
                    i += 1
                _mark(i)
            else:
                i += 1

    return {
        'offsets': offsets,
        'line_count': line_count,
        'step': LINE_INDEX_STEP,
        'encoding': encoding or 'utf-8',
    }


def set_line_index(file_path, file_hash, raw_data, encoding):
    """构建并缓存一个文件的稀疏行索引。"""
    real_path = os.path.realpath(file_path)
    key = (real_path, file_hash)
    index = build_line_index(raw_data, encoding)
    index['file_path'] = real_path
    index['file_hash'] = file_hash
    line_index_cache[key] = index
    line_index_cache.move_to_end(key)
    while len(line_index_cache) > LINE_INDEX_MAX:
        line_index_cache.popitem(last=False)
    return index


def get_line_index(file_path, encoding=None):
    """获取行索引；缓存未命中时读取一次原始文件并构建。"""
    real_path = os.path.realpath(file_path)
    file_hash = get_file_hash(real_path)
    key = (real_path, file_hash)
    if key in line_index_cache:
        line_index_cache.move_to_end(key)
        return line_index_cache[key]

    if encoding is None:
        encoding = detect_encoding(real_path)
    with open(real_path, 'rb') as f:
        raw_data = f.read()
    return set_line_index(real_path, file_hash, raw_data, encoding)


# 行区间短期缓存：(真实路径, 文件哈希, 起始行, 结束行) -> 行列表
# 阅读页翻页、上一页/下一页、以及「预取下一章」都会命中，避免重复读同一段文件。
# 桌面版内存充裕，12 个区间约几 MB，换来翻章时不重新解析文件。
_line_range_cache = OrderedDict()
LINE_RANGE_CACHE_MAX = 12


def read_line_range(file_path, start_line, end_line, index=None, encoding=None):
    """按行读取（带短期缓存）。真正的实现是 _read_line_range_raw。"""
    index = index or get_line_index(file_path, encoding)
    key = (index.get('file_path') or os.path.realpath(file_path),
           index.get('file_hash'),
           max(1, int(start_line)),
           max(1, int(end_line)))

    hit = _line_range_cache.get(key)
    if hit is not None:
        _line_range_cache.move_to_end(key)
        return list(hit)

    lines = _read_line_range_raw(file_path, start_line, end_line, index=index, encoding=encoding)
    _line_range_cache[key] = lines
    while len(_line_range_cache) > LINE_RANGE_CACHE_MAX:
        _line_range_cache.popitem(last=False)
    return list(lines)


def _read_line_range_raw(file_path, start_line, end_line, index=None, encoding=None):
    """流式读取指定行区间（包含 start_line 和 end_line，1-based）。"""
    start_line = max(1, int(start_line))
    end_line = max(start_line, int(end_line))
    index = index or get_line_index(file_path, encoding)
    encoding = index.get('encoding') or encoding or 'utf-8'
    try:
        codecs.lookup(encoding)
    except LookupError:
        # 历史缓存里存了无效编码（如已废弃的 'prefetched' 哨兵）：
        # 丢掉行索引，按真实探测重建后再继续
        line_index_cache.pop((index.get('file_path') or os.path.realpath(file_path),
                              index.get('file_hash')), None)
        index = get_line_index(file_path)
        encoding = index.get('encoding') or 'utf-8'
    step = index.get('step', LINE_INDEX_STEP)
    offsets = index.get('offsets') or [0]
    line_count = index.get('line_count', 0)
    if start_line > line_count:
        return []
    end_line = min(end_line, line_count)

    checkpoint_idx = max(0, (start_line - 1) // step)
    if checkpoint_idx >= len(offsets):
        checkpoint_idx = len(offsets) - 1
    offset = offsets[checkpoint_idx]
    current_line = checkpoint_idx * step + 1
    lines = []
    buffer = ''
    decoder = codecs.getincrementaldecoder(encoding)(errors='ignore')

    with open(file_path, 'rb') as f:
        f.seek(offset)
        while current_line <= end_line:
            chunk = f.read(262144)
            if not chunk:
                tail = decoder.decode(b'', final=True)
                if tail:
                    buffer += tail
                if buffer or current_line <= line_count:
                    for part in LINE_BREAK_RE.split(buffer):
                        if current_line > end_line:
                            break
                        line = part
                        if current_line == 1 and line.startswith('\ufeff'):
                            line = line[1:]
                        if current_line >= start_line:
                            lines.append(line)
                        current_line += 1
                break

            buffer += decoder.decode(chunk)
            if current_line > end_line:
                break

            matches = list(LINE_BREAK_RE.finditer(buffer))
            if not matches:
                continue

            process_count = len(matches)
            if buffer.endswith('\r') and matches[-1].group() == '\r' and matches[-1].end() == len(buffer):
                process_count -= 1

            pos = 0
            for m in matches[:process_count]:
                line = buffer[pos:m.start()]
                if current_line == 1 and line.startswith('\ufeff'):
                    line = line[1:]
                if current_line >= start_line:
                    lines.append(line)
                    if current_line >= end_line:
                        return lines
                current_line += 1
                pos = m.end()
            buffer = buffer[pos:]

    return lines


def load_cache():
    """加载缓存的扫描结果"""
    global novel_data, chapter_cache, NOVEL_DIR, image_cache
    
    if not os.path.exists(CACHE_FILE):
        print(f"⚠️ 缓存文件不存在: {CACHE_FILE}")
        return False
    
    try:
        data = load_json_file(CACHE_FILE)
        if not data:
            return False
                
        loaded_novel_data = data.get('novel_data', [])
        novel_data = []
        
        for novel in loaded_novel_data:
            novel_copy = novel.copy()
            if 'file_path' in novel_copy:
                filename = os.path.basename(novel_copy['file_path'])
                abs_path = os.path.join(NOVEL_DIR, filename)
                novel_copy['file_path'] = abs_path
                
                if 'has_images' not in novel_copy:
                    image_folder = get_image_folder_for_novel(filename)
                    novel_copy['has_images'] = image_folder is not None
                    novel_copy['image_folder'] = image_folder
                
                if 'intro' not in novel_copy:
                    novel_copy['intro'] = '无简介'
            
            novel_data.append(novel_copy)
        
        loaded_chapter_cache = data.get('chapter_cache', {})
        chapter_cache = {}
        for old_path, chapters in loaded_chapter_cache.items():
            filename = os.path.basename(old_path)
            abs_path = os.path.join(NOVEL_DIR, filename)
            chapter_cache[abs_path] = chapters
        
        print(f"✅ 从缓存加载了 {len(novel_data)} 本小说，{len(chapter_cache)} 个章节信息")
        return True
        
    except Exception as e:
        print(f"⚠️ 缓存文件加载失败：{e}")
        traceback.print_exc()
        return False


def save_cache():
    """保存扫描结果到缓存（原子写入，并清理已删除文件的缓存）。"""
    global novel_data, chapter_cache, tag_parse_cache, image_cache

    try:
        active_paths = {os.path.realpath(n.get('file_path', '')) for n in novel_data if n.get('file_path')}
        active_names = {os.path.basename(p) for p in active_paths}

        relative_novel_data = []
        for novel in novel_data:
            novel_copy = novel.copy()
            if 'file_path' in novel_copy:
                novel_copy['file_path'] = os.path.basename(novel_copy['file_path'])

            image_folder = get_image_folder_for_novel(novel_copy.get('file_path', ''))
            if image_folder and is_path_within(NOVEL_DIR, image_folder):
                novel_copy['has_images'] = True
                novel_copy['image_folder'] = image_folder
            else:
                novel_copy['has_images'] = False
                novel_copy['image_folder'] = None

            if 'intro' not in novel_copy:
                novel_copy['intro'] = '无简介'

            # 字段完整：读取方默认这些键存在，缺失时运行时还要再补一次
            if 'preview' not in novel_copy:
                novel_copy['preview'] = None

            # work_id 是重命名识别的依据，缺省写 None 保持字段一致
            if 'work_id' not in novel_copy:
                novel_copy['work_id'] = None

            relative_novel_data.append(novel_copy)

        # 清理已删除文件相关的内存缓存
        for key in list(chapter_cache.keys()):
            if os.path.realpath(key) not in active_paths:
                chapter_cache.pop(key, None)
        for key in list(tag_parse_cache.keys()):
            if os.path.realpath(key) not in active_paths:
                tag_parse_cache.pop(key, None)
        for key in list(image_cache.keys()):
            if key not in active_names:
                image_cache.pop(key, None)

        # 内存里的 chapter_cache 可以放到 500 本，但磁盘只存最近 200 本 ——
        # 缓存文件从 6MB 涨到 15MB 会让启动加载明显变慢，而超过 200 本的部分
        # 命中率很低（谁也不会一天翻 300 本书），留着不划算。
        relative_chapter_cache = {}
        recent_chapters = list(chapter_cache.items())[-200:]
        for abs_path, chapters in recent_chapters:
            filename = os.path.basename(abs_path)
            if filename in active_names:
                relative_chapter_cache[filename] = chapters

        cache_data = {
            'novel_data': relative_novel_data,
        }

        # chapter_cache 是桌面版自己的运行时章节缓存，重启后用于加速首屏
        cache_data['chapter_cache'] = relative_chapter_cache

        # 缓存文件不需要人类可读的缩进，紧凑写入可显著减小 6MB+ 的缓存体积
        save_json_file(CACHE_FILE, cache_data, indent=None)
        print(f"✅ 已缓存 {len(novel_data)} 本小说，{len(chapter_cache)} 个章节信息")
    except Exception as e:
        print(f"❌ 缓存保存失败：{e}")
        traceback.print_exc()


def strip_txt_ext(filename):
    """去掉结尾的 .txt/.TXT（只去结尾，避免标题里的 .txt 被误伤）

    ⚠️ 不要用 filename.replace('.txt','')：那样 'a.txt版本.txt' 会变成
    'a版本'、'我的书.txt.txt' 会变成 '我的书'，导致配图目录名对不上。
    """
    if not filename:
        return ''
    if filename.lower().endswith('.txt'):
        return filename[:-4]
    return filename


def get_image_folder_for_novel(filename):
    """获取小说对应的配图文件夹路径（统一版本）

    ⚠️ 候选只认 *_images / *_配图。
    历史上还有第三个候选「与书名同名的目录」，但把书按目录整理时
    （NOVEL_DIR/某本书/ 下放正文），那个目录会被误判成配图文件夹，
    导致「配图」标签与前端找图路径双双出错，故移除。
    """
    if not filename:
        return None

    base_name = strip_txt_ext(filename)

    possible_folders = [
        os.path.join(NOVEL_DIR, f"{base_name}_images"),
        os.path.join(NOVEL_DIR, f"{base_name}_配图"),
    ]

    for folder in possible_folders:
        if os.path.isdir(folder):
            return folder

    return None


# ==================== 媒体类型判定（单一定义源）====================
# 「配图 / 视频 / 音频」是**文件系统存在性标记**，只能由 scan_media_types()
# 按配图目录实际内容生成，绝不能参与正文关键词匹配
# （小说正文里提到「视频」二字太常见，会把大量纯文字小说误标成「视频」）。
MEDIA_TAG_NAMES = frozenset({'配图', '视频', '音频'})

IMAGE_EXTENSIONS_ALL = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.avif',
    '.tif', '.tiff', '.heic', '.heif',
})
VIDEO_EXTENSIONS_ALL = frozenset({
    '.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v',
    '.mpg', '.mpeg', '.ts', '.m2ts', '.3gp', '.ogv',
})
AUDIO_EXTENSIONS_ALL = frozenset({
    '.mp3', '.m4a', '.m4b', '.aac', '.wav', '.flac', '.ogg', '.oga',
    '.opus', '.wma', '.ape', '.alac', '.aiff', '.aif',
})


def scan_media_types(folder_path, max_depth=3):
    """统计配图目录里实际存在的媒体类型（递归，跳过隐藏/垃圾文件）。

    旧实现只看 os.listdir 第一层 —— 配图按章节分子目录（第1章/01.jpg）时
    会整批漏掉，导致「配图」标签缺失。

    返回 {'image': bool, 'video': bool, 'audio': bool}
    """
    found = {'image': False, 'video': False, 'audio': False}
    if not folder_path or not os.path.isdir(folder_path):
        return found

    base_depth = folder_path.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(folder_path):
            if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.startswith('.') or f.lower() in ('thumbs.db', 'desktop.ini'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTENSIONS_ALL:
                    found['image'] = True
                elif ext in VIDEO_EXTENSIONS_ALL:
                    found['video'] = True
                elif ext in AUDIO_EXTENSIONS_ALL:
                    found['audio'] = True
            if all(found.values()):
                break
    except OSError as e:
        logger.warning(f"读取配图目录失败（已跳过）: {folder_path}: {e}")

    return found


def _media_tags_from(item):
    """从条目里取出 tags 列表（兼容字符串/列表）"""
    tags = item.get('tags') or ''
    if isinstance(tags, str):
        return [t for t in re.split(r'[,，\s]+', tags) if t]
    return list(tags)


def _set_media_tags(item, media_types):
    """按实际媒体情况增删 配图/视频/音频 三个标签，其余标签顺序不动"""
    current = _media_tags_from(item)
    desired = []
    if media_types.get('image'):
        desired.append('配图')
    if media_types.get('video'):
        desired.append('视频')
    if media_types.get('audio'):
        desired.append('音频')

    result = [t for t in current if t not in MEDIA_TAG_NAMES]
    for t in desired:
        if t not in result:
            result.append(t)

    if result != current:
        item['tags'] = ','.join(result) if result else '无'


def _refresh_media_tags(item, folder_path):
    """按目录实际内容刷新媒体标签"""
    try:
        _set_media_tags(item, scan_media_types(folder_path))
    except Exception as e:
        logger.warning(f"刷新媒体标签失败（已跳过）: {folder_path}: {e}")


def _strip_media_tags(item):
    """配图目录不存在时移除三类媒体标签"""
    try:
        _set_media_tags(item, {'image': False, 'video': False, 'audio': False})
    except Exception:
        pass


def get_novel_image_info(file_path):
    """获取小说的配图信息"""
    global image_cache

    filename = os.path.basename(file_path)
    base_name = strip_txt_ext(filename)   # 只去结尾扩展名，避免标题里的 .txt 被误伤

    if base_name in image_cache:
        image_cache.move_to_end(base_name)
        return image_cache[base_name]

    image_folder = get_image_folder_for_novel(filename)

    if not image_folder:
        image_cache[base_name] = None
        return None

    info = {
        'folder': image_folder,
        'files': []
    }

    try:
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
        for f in os.listdir(image_folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in image_extensions:
                info['files'].append(f)
    except Exception as e:
        logger.error(f"读取配图信息失败: {e}")

    image_cache[base_name] = info
    return info


def is_file_readable(file_path):
    """检查文件是否可读"""
    try:
        with open(file_path, 'rb') as f:
            f.read(1)
        return True
    except:
        return False


novel_data = []
chapter_cache = {}
scan_progress = {
    'total': 0,
    'current': 0,
    'status': 'idle',
    'message': '',
    'start_time': None,
    # 进度分两段：scan_dir（检查书目，增量扫描的主要耗时）→ parse（解析变化文件）
    # 百分比由接口按阶段加权，避免 total 切换导致的跳变
    'phase': '',
    'incremental': False,
}

cache = {
    'filter_options': None,
    'last_update': 0,
    'data_hash': None
}

tag_parse_cache = {}

# ==================== 后台任务 ====================
background_tasks = {}
background_tasks_lock = threading.Lock()
BACKGROUND_TASK_TTL = 3600
BACKGROUND_TASK_MAX = 20


def _cleanup_background_tasks_locked():
    now = time.time()
    stale = [
        task_id for task_id, task in background_tasks.items()
        if task.get('status') in ('completed', 'error')
        and now - task.get('updated_at', now) > BACKGROUND_TASK_TTL
    ]
    for task_id in stale:
        background_tasks.pop(task_id, None)

    if len(background_tasks) > BACKGROUND_TASK_MAX:
        ordered = sorted(background_tasks.items(), key=lambda kv: kv[1].get('updated_at', 0))
        for task_id, _ in ordered[:len(background_tasks) - BACKGROUND_TASK_MAX]:
            background_tasks.pop(task_id, None)


def create_background_task(task_type, total=0, message=''):
    task_id = secrets.token_hex(8)
    now = time.time()
    with background_tasks_lock:
        background_tasks[task_id] = {
            'id': task_id,
            'type': task_type,
            'status': 'running',
            'total': total,
            'current': 0,
            'message': message,
            'result': None,
            'error': None,
            'started_at': now,
            'updated_at': now,
            'finished_at': None,
        }
        _cleanup_background_tasks_locked()
    return task_id


def update_background_task(task_id, **fields):
    with background_tasks_lock:
        task = background_tasks.get(task_id)
        if task is None:
            return
        task.update(fields)
        task['updated_at'] = time.time()


TXT_HEALTH_SCAN_LOCK_FILE = os.path.join(tempfile.gettempdir(), 'novel_manager_txt_health_scan.lock')


class _CrossProcessLock:
    """跨进程互斥锁：多 worker（gunicorn / 多进程）部署时也只允许一个扫描。

    以原子创建文件的方式抢锁；进程异常退出后靠过期时间自动释放，
    避免残留锁文件导致永久无法扫描。
    """

    EXPIRE_SECONDS = 900  # 超过 15 分钟视为异常残留，强制接管

    def __init__(self, path):
        self.path = path
        self.acquired = False

    def _is_expired(self):
        try:
            age = time.time() - os.path.getmtime(self.path)
            return age > self.EXPIRE_SECONDS
        except OSError:
            return False

    def acquire(self):
        for attempt in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.acquired = True
                return True
            except FileExistsError:
                # 残留锁且已过期：先删再抢一次
                if attempt == 0 and self._is_expired():
                    try:
                        os.remove(self.path)
                    except OSError:
                        return False
                    continue
                return False
            except OSError:
                # 无权限等异常时不阻断功能，降级为仅进程内锁
                return True
        return False

    def release(self):
        if not self.acquired:
            return
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.acquired = False


def find_running_task(task_type):
    """查找指定类型中仍在运行的后台任务，返回 task_id；没有则返回 None。"""
    with background_tasks_lock:
        for task_id, task in background_tasks.items():
            if task.get('type') == task_type and task.get('status') == 'running':
                return task_id
    return None


def get_background_task(task_id):
    with background_tasks_lock:
        task = background_tasks.get(task_id)
        return dict(task) if task else None


def finish_background_task(task_id, result=None, error=None):
    status = 'error' if error else 'completed'
    update_background_task(
        task_id,
        status=status,
        result=result,
        error=str(error) if error else None,
        message='任务失败' if error else '任务完成',
        finished_at=time.time(),
    )


def invalidate_filter_cache():
    """小说标签/作者/站点变化后，让筛选选项缓存立即失效。"""
    cache['filter_options'] = None
    cache['data_hash'] = None


def get_data_hash(data):
    """计算数据哈希值"""
    if not data:
        return None
    try:
        return f"{len(data)}_{os.path.getmtime(NOVEL_DIR) if os.path.exists(NOVEL_DIR) else 0}"
    except:
        return f"{len(data)}_{time.time()}"


def split_author_aliases(author):
    """把「主名（马甲1,马甲2）」拆成 (主名, [马甲...])。

    元数据里同一作者的马甲统一写成：金鳞庸人（uwkuk8k,财狼少年）
    主名是括号前的部分；括号内用 , ， 、 & ＆ / ｜ 分隔都认
    （实际数据里主要是英文逗号）。

    没有括号时返回 (原串, [])。
    """
    if not author:
        return '', []

    text = str(author).strip()
    match = re.match(r'^(.*?)[（(]([^）)]*)[）)]\s*(.*)$', text)
    if not match:
        return text, []

    main = match.group(1).strip()
    inner = match.group(2).strip()
    tail = match.group(3).strip()

    if not main or not inner:
        return text, []

    aliases = [a.strip() for a in re.split(r'[,，、&＆/／|]+', inner) if a.strip()]

    if tail:
        main = f'{main} {tail}'.strip()

    return main, aliases


def author_names_of(author):
    """返回这本书涉及的全部名号：[主名, 马甲1, 马甲2...]"""
    main, aliases = split_author_aliases(author)
    if not main:
        return []
    return [main] + aliases


def build_author_identity_map(novels=None):
    """建立「任一名号 -> 该作者的全部名号」映射，用于把马甲和主名视为同一个人。

    例：{'金鳞庸人': {'金鳞庸人','uwkuk8k','财狼少年'},
         '财狼少年': {'金鳞庸人','uwkuk8k','财狼少年'}}

    这样下拉里选主名或选马甲，都能列出这个人署名的全部书。
    """
    source = novel_data if novels is None else novels
    # 先按主名把马甲并起来（同一主名在不同书里可能只写了部分马甲）
    merged = {}
    for n in source or []:
        main, aliases = split_author_aliases((n.get('author') or ''))
        if not main:
            continue
        bucket = merged.setdefault(main, set())
        bucket.add(main)
        bucket.update(aliases)

    lookup = {}
    for names in merged.values():
        for name in names:
            # 同名冲突时保留已有的（先到先得，避免来回覆盖）
            lookup.setdefault(name, names)
    return lookup

# ==================== 相似书籍推荐 ====================
# 用途：详情页 + 阅读页最后一页的「相似书籍」区块。锦上添花的功能，
# 刻意保持简单：只用书名 / 作者 / 标签，不引第三方库、不落盘、不加配置项。
#
# 取舍：宁缺毋滥 —— 分数不到阈值就不返回，调用方据此整块不渲染，
# 不拿随机书或弱标签凑数。
#
# 书名解析（parse_title_meta）解决三件事：
#   1) 系列：「系列名 + 第几部」拆开，同系列排一起、按卷次
#   2) 关系：番外 / 同人 / 外传 / 前传 / 续 单独标出，不跟原书混为一谈
#   3) 噪声：番号（FC2PPV-3179361）、原名/又名、【征文】这类尾巴不参与计算
#
# ⚠️ 冒号/下划线截出来的「系列根名」默认不可信：「XX：YY」这种修辞副标题会截出
#    两个字的假系列。只有该根名在全库出现 >= 2 次才认，否则回退完整书名。
#    实测 5102 本可聚出 266 个真系列簇。

SIMILAR_LIMIT = 8              # 最多几条
SIMILAR_THRESHOLD = 22.0       # 低于此分不展示
SIMILAR_SERIES_CAP = 3         # 同一系列最多占几条
SIMILAR_TAGS_FOR_MATCH = 6     # 只吃前 6 个高权重标签（每本中位数 46 个，全量算人人相似）
SIMILAR_GRAM_HOT_RATIO = 0.05  # 覆盖超过 5% 的二元组算热词，不进候选
SIMILAR_MIN_GRAM_HITS = 3      # 书名二元组至少命中几个才算候选

_SIM_TAIL_BRACKET_RE = re.compile(r'[（(【\[《]([^（()）【】\[\]《》]*)[）)】\]》]\s*$')
_SIM_VOLUME_RE = re.compile(r'第\s*([0-9一二三四五六七八九十百零两〇]{1,4})\s*[部卷册集篇季]')
_SIM_TRAIL_NUM_RE = re.compile(r'(?<=[\u4e00-\u9fa5])[\s·]*([0-9]{1,2})\s*$')
_SIM_CODE_RE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})[-_ ]?([0-9]{3,})(?![0-9])')
_SIM_ALIAS_RE = re.compile(r'(?:原名|又名)\s*[:：]?\s*(.+)$')
_SIM_SEP_RE = re.compile(r'[_＿]|[:：]|—{2,}')
_SIM_CN_DIGITS = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}
_SIM_RELATIONS = (
    ('番外', 'fanwai'), ('同人', 'tongren'), ('外传', 'waizhuan'),
    ('外篇', 'waizhuan'), ('前传', 'qianchuan'), ('后传', 'xuji'),
    ('续集', 'xuji'), ('续篇', 'xuji'),
)
_SIM_RELATION_LABEL = {
    'main': '', 'fanwai': '番外', 'tongren': '同人',
    'waizhuan': '外传', 'qianchuan': '前传', 'xuji': '续',
}
_SIM_CONTINUE_SKIP = '继续连持陆'
# 这些不是真作者，不能拿来做「同作者」匹配（否则 159 本 [不详] 会互相推荐）
_SIM_UNKNOWN_AUTHORS = {
    '', '[不详]', '【不详】', '不详', '未知作者', '未知', '匿名', '佚名', '-', '—', '无',
}


def _sim_cn_to_int(text):
    """一~九十九 的中文数字转整数；认不出返回 None。"""
    text = (text or '').strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if '十' in text:
        left, _, right = text.partition('十')
        if left and left not in _SIM_CN_DIGITS:
            return None
        if right and right not in _SIM_CN_DIGITS:
            return None
        tens = _SIM_CN_DIGITS.get(left, 1) if left else 1
        ones = _SIM_CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _SIM_CN_DIGITS.get(text)


def _sim_find_relation(text):
    """返回 (relation, 位置)，取最靠前的关系词；没找到返回 ('main', -1)。"""
    best_pos, best_rel = -1, 'main'
    for word, rel in _SIM_RELATIONS:
        pos = text.find(word)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos, best_rel = pos, rel
    # 单字「续」：前面是 继/连/持/陆 的不算（继续、连续、持续、陆续）
    for pos, char in enumerate(text):
        if char != '续':
            continue
        prev = text[pos - 1] if pos else ''
        if prev and prev in _SIM_CONTINUE_SKIP:
            continue
        if best_pos < 0 or pos < best_pos:
            best_pos, best_rel = pos, 'xuji'
        break
    return best_rel, best_pos


def _sim_clean(text):
    """去掉空白与残留分隔符，用于书名归一化比较。"""
    return re.sub(r'[\s\u3000·・]+', '', text or '').strip('_＿-—:：')


def parse_title_meta(title):
    """把书名拆成：系列根名 / 卷次 / 关系（番外·同人·续·外传）/ 原名 / 番号。

    返回的 dict 字段始终齐全。base 只是「候选系列根名」，是否可信由调用方
    按全库频次判定（见 _build_similar_index），避免冒号截断出假系列。
    """
    raw = (title or '').strip()
    meta = {
        'raw': raw, 'base': '', 'base_full': '', 'volume': None,
        'relation': 'main', 'relation_label': '', 'aliases': [], 'code': '', 'note': '',
    }
    if not raw:
        return meta

    text = raw.replace('《', '').replace('》', '').strip()

    # 1) 尾部括号逐层剥离（最多两层）：卷次 / 原名 / 番号 / 关系词 / 题材标注
    for _ in range(2):
        match = _SIM_TAIL_BRACKET_RE.search(text)
        if not match:
            break
        inner = (match.group(1) or '').strip()
        if not inner:
            break

        consumed = False
        volume = _SIM_VOLUME_RE.search(inner)
        if volume:
            meta['volume'] = _sim_cn_to_int(volume.group(1))
            consumed = True
        elif re.fullmatch(r'[0-9]{1,2}', inner):
            meta['volume'] = int(inner)
            consumed = True
        elif inner in ('上', '中', '下'):
            meta['volume'] = {'上': 1, '中': 2, '下': 3}[inner]
            consumed = True

        if not consumed:
            alias = _SIM_ALIAS_RE.search(inner)
            if alias:
                meta['aliases'].append(alias.group(1).strip())
                consumed = True

        if not consumed and len(inner) <= 20:
            code = _SIM_CODE_RE.search(inner)
            if code:
                meta['code'] = f'{code.group(1).upper()}-{code.group(2)}'
                consumed = True

        if not consumed:
            relation, _pos = _sim_find_relation(inner)
            if relation != 'main':
                meta['relation'] = relation
                consumed = True

        if not consumed and not meta['note']:
            meta['note'] = inner

        text = text[:match.start()].strip()
        if not text:
            break

    # 2) 关系词：整段书名里再找一次（拆掉括号后可能才露出来）
    relation, _pos = _sim_find_relation(text)
    if meta['relation'] == 'main' and relation != 'main':
        meta['relation'] = relation

    # 3) 分隔符左侧 = 系列名候选
    head = text
    sep = _SIM_SEP_RE.search(text)
    if sep and sep.start() >= 2:
        head = text[:sep.start()].strip()

    # 4) 卷次：「第X部」或书名尾部裸数字
    volume = _SIM_VOLUME_RE.search(head)
    if volume and meta['volume'] is None:
        meta['volume'] = _sim_cn_to_int(volume.group(1))
    head = _SIM_VOLUME_RE.sub('', head)
    trailing = _SIM_TRAIL_NUM_RE.search(head)
    if trailing:
        if meta['volume'] is None:
            meta['volume'] = int(trailing.group(1))
        head = head[:trailing.start()].strip()

    meta['base'] = _sim_clean(head)
    meta['base_full'] = _sim_clean(text)
    meta['relation_label'] = _SIM_RELATION_LABEL.get(meta['relation'], '')
    if not meta['base']:
        meta['base'] = meta['base_full']
    return meta


def _sim_grams(text, size=2):
    """中文/字母数字二元组集合，用于抓「同格式书名同族」（如番号类长标题）。"""
    cleaned = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', text or '')
    if len(cleaned) < size:
        return set()
    return {cleaned[i:i + size] for i in range(len(cleaned) - size + 1)}


def _sim_split_tags(value):
    """标签兼容字符串（缓存里是逗号分隔）和 list（内存里可能是 list）。"""
    if isinstance(value, (list, tuple, set)):
        items = [str(tag).strip() for tag in value]
    else:
        items = [tag.strip() for tag in str(value or '').split(',')]
    return [tag for tag in items if tag and tag != '无']


_similar_index_cache = {'key': None, 'data': None}


def _build_similar_index():
    """建倒排索引：系列 / 作者身份组 / 书名二元组 / 标签。全库一次，约 70ms。"""
    novels = novel_data or []
    if not novels:
        return None

    identity = build_author_identity_map(novels)
    metas = []
    base_count = {}
    for novel in novels:
        meta = parse_title_meta(novel.get('title') or '')
        metas.append(meta)
        if meta['base']:
            base_count[meta['base']] = base_count.get(meta['base'], 0) + 1

    by_series, by_author, by_gram, by_tag = {}, {}, {}, {}
    tag_sets = []
    authors = []

    for idx, (novel, meta) in enumerate(zip(novels, metas)):
        # 系列根名必须全库 >= 2 次才算数，否则用完整书名当 key（防假系列）
        series_key = meta['base'] if base_count.get(meta['base'], 0) >= 2 else meta['base_full']
        meta['series_key'] = series_key
        if series_key:
            by_series.setdefault(series_key, []).append(idx)

        names = author_names_of(novel.get('author') or '')
        group = ''
        if names and names[0] not in _SIM_UNKNOWN_AUTHORS:
            group = sorted(identity.get(names[0]) or {names[0]})[0]
            by_author.setdefault(group, []).append(idx)
        meta['author_group'] = group
        authors.append((names[0] if names else '', max(0, len(names) - 1)))

        meta['grams'] = _sim_grams(meta['raw'])
        for gram in meta['grams']:
            by_gram.setdefault(gram, []).append(idx)

        tag_set = set(_sim_split_tags(novel.get('tags'))[:SIMILAR_TAGS_FOR_MATCH])
        tag_sets.append(tag_set)
        for tag in tag_set:
            by_tag.setdefault(tag, []).append(idx)

    return {
        'novels': novels, 'metas': metas, 'base_count': base_count,
        'alias_group': identity, 'by_series': by_series, 'by_author': by_author,
        'by_gram': by_gram, 'by_tag': by_tag, 'tag_sets': tag_sets,
        'authors': authors, 'total': len(novels),
    }


def _get_similar_index():
    """索引生命周期跟着 novel_data 这个列表对象走，不落盘。

    扫描/重载缓存都是整体替换 `novel_data = [...]`（load_cache 与扫描分支都是新列表），
    所以比较对象身份 + 长度就能准确判断要不要重建，比按目录 mtime 更可靠
    （扫描只读目录，mtime 不会变）。
    """
    cached = _similar_index_cache
    data = cached['data']
    if (data is not None and data['novels'] is novel_data
            and len(data['novels']) == len(novel_data or [])):
        return data
    data = _build_similar_index()
    cached['key'] = (id(novel_data), len(novel_data or []))
    cached['data'] = data
    return data


def find_similar_novels(title, author, tags, exclude_work_id='', exclude_path='',
                        limit=SIMILAR_LIMIT):
    """找相似书籍，返回按相关度排好的 list。

    打分：系列根名相同 60 / 作者身份组相同（含马甲）30 /
          书名二元组 Jaccard ×20 / 标签 Jaccard ×15，满分 125。
    不到 SIMILAR_THRESHOLD 直接丢弃；同系列最多 SIMILAR_SERIES_CAP 条。
    """
    index = _get_similar_index()
    if not index:
        return []

    novels = index['novels']
    metas = index['metas']
    total = index['total']
    base_count = index['base_count']
    hot_limit = max(1, int(total * SIMILAR_GRAM_HOT_RATIO))

    query_meta = parse_title_meta(title)
    query_base = query_meta['base']
    query_series = query_base if base_count.get(query_base, 0) >= 2 else query_meta['base_full']
    query_grams = _sim_grams(query_meta['raw'])
    query_tags = set(_sim_split_tags(tags)[:SIMILAR_TAGS_FOR_MATCH])

    query_group = ''
    names = author_names_of(author or '')
    if names and names[0] not in _SIM_UNKNOWN_AUTHORS:
        query_group = sorted(index['alias_group'].get(names[0]) or {names[0]})[0]

    # === 候选集：系列 + 作者 + 书名二元组 + 非热标签，上限通常两三百本 ===
    candidates = set()
    if query_series:
        candidates.update(index['by_series'].get(query_series, ()))
    if query_group:
        candidates.update(index['by_author'].get(query_group, ()))

    gram_hits = {}
    for gram in query_grams:
        posting = index['by_gram'].get(gram)
        if not posting or len(posting) > hot_limit:
            continue
        for idx in posting:
            gram_hits[idx] = gram_hits.get(idx, 0) + 1
    candidates.update(idx for idx, hits in gram_hits.items() if hits >= SIMILAR_MIN_GRAM_HITS)

    for tag in query_tags:
        posting = index['by_tag'].get(tag)
        if not posting or len(posting) > hot_limit:
            continue
        candidates.update(posting)

    exclude_name = os.path.basename(exclude_path or '')
    items = []
    for idx in candidates:
        novel = novels[idx]
        if exclude_work_id and novel.get('work_id') == exclude_work_id:
            continue
        if exclude_name and os.path.basename(novel.get('file_path') or '') == exclude_name:
            continue

        meta = metas[idx]
        matched = []
        score = 0.0
        is_series = bool(query_series) and meta.get('series_key') == query_series
        if is_series:
            score += 60.0
            matched.append('series')
        else:
            other_grams = meta.get('grams') or set()
            union = len(query_grams | other_grams)
            if union:
                score += 20.0 * len(query_grams & other_grams) / union
        if query_group and meta.get('author_group') == query_group:
            score += 30.0
            matched.append('author')

        other_tags = index['tag_sets'][idx]
        union = len(query_tags | other_tags)
        common_tags = len(query_tags & other_tags)
        if union:
            score += 15.0 * common_tags / union
        if score < SIMILAR_THRESHOLD:
            continue

        labels = []
        if is_series:
            labels.append('系列' + (f'·第{meta["volume"]}部' if meta.get('volume') else ''))
        if meta['relation'] != 'main':
            labels.append(meta['relation_label'])
        if not labels:
            labels.append('同作者' if 'author' in matched else '同标签')

        author_name, alias_count = index['authors'][idx]
        items.append({
            'title': novel.get('title') or meta['raw'],
            'author': author_name or '未知作者',
            'alias_count': alias_count,
            'reason': ' · '.join(label for label in labels if label),
            'score': round(score, 1),
            'volume': meta.get('volume') or 0,
            'is_series': is_series,
            'is_main': meta['relation'] == 'main',
            'series_key': meta.get('series_key') or '',
            'file_path': (novel.get('file_path') or '').lstrip('/'),
        })

    # 系列整体排前面；系列内部按「本篇 → 卷次」，避免番外/同人把原书挤出前 3 条
    items.sort(key=lambda item: (
        0 if item['is_series'] else 1,
        0 if item['is_main'] else 1,
        item['volume'],
        -item['score'],
        item['title'],
    ))

    picked = []
    series_used = {}
    for item in items:
        if item['is_series']:
            used = series_used.get(item['series_key'], 0)
            if used >= SIMILAR_SERIES_CAP:
                continue
            series_used[item['series_key']] = used + 1
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def build_similar_urls(items, **query):
    """给相似项补详情页链接，并带上当前列表的筛选参数（返回列表不丢状态）。"""
    clean = {key: value for key, value in query.items() if value not in (None, '', 0)}
    for item in items:
        item['detail_url'] = url_for('novel_detail', file_path=item['file_path'], **clean)
    return items

def parse_progress(filename):
    """解析文件名中的连载进度信息"""
    progress_pattern = r"【([^】]+)】"
    match = re.search(progress_pattern, filename)
    if match:
        progress_text = match.group(1).strip()
        separators = r'[+\s/、]'
        
        parts = []
        if '完' in progress_text:
            if progress_text.endswith('完'):
                main_part = progress_text[:-1]
                if main_part:
                    subparts = re.split(separators, main_part)
                    parts.extend([p for p in subparts if p])
                parts.append('完')
            elif progress_text.startswith('完'):
                parts.append('完')
                main_part = progress_text[1:]
                if main_part:
                    subparts = re.split(separators, main_part)
                    parts.extend([p for p in subparts if p])
            else:
                temp_parts = progress_text.split('完')
                for i, part in enumerate(temp_parts):
                    if part:
                        subparts = re.split(separators, part)
                        parts.extend([p for p in subparts if p])
                    if i < len(temp_parts) - 1:
                        parts.append('完')
        else:
            parts = re.split(separators, progress_text)
        
        parts = [p.strip() for p in parts if p.strip()]
        
        seen = set()
        unique_parts = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique_parts.append(p)
        parts = unique_parts
        
        if len(parts) > 1:
            return ','.join(parts)
        else:
            return parts[0] if parts else "未知"
    
    return "未知"


def read_file_header(file_path, max_size=16384):
    """只读取文件头部"""
    try:
        with open(file_path, 'rb') as f:
            f.seek(0)
            raw_data = f.read(max_size)
        
        try:
            content = raw_data.decode('utf-8')
        except:
            try:
                content = raw_data.decode('gbk')
            except:
                content = raw_data.decode('utf-8', errors='ignore')
        
        if content.startswith('\ufeff'):
            content = content[1:]
        
        return content
        
    except Exception as e:
        print(f"❌ 读取文件出错：{e}")
        return None


def normalize_name(name, type='site'):
    """标准化名称"""
    if not name or name == '未知作者' or name == '未知网站' or name == '未知':
        return name
    
    if type == 'site':
        return name.strip().lower()
    if type == 'author':
        return name.lower()
    if type == 'tag':
        return name.lower()
    return name.strip()

# ==================== 预览提取函数 ====================
# 与简介提取共用同一套「元数据行 / 图片行 / 章节行」判定，避免两处规则漂移
def _clean_line(s):
    """去掉首尾空白及零宽字符（简介/预览/元数据判定统一入口）"""
    return s.strip(' \t\r\n\u3000\u200b\ufeff')


# 元数据前缀：以这些开头的内容属于文件头信息，不能当简介或正文预览
_META_PREFIXES = (
    '书名：', '书名:', '作者：', '作者:', '链接：', '链接:',
    '标签：', '标签:', '内容简介：', '内容简介:', '简介：', '简介:',
    '说明：', '说明:', '首发于', '发布于', '发表于',
    '发布：', '发布:', '首发：', '首发:', '发表：', '发表:',
    '转发：', '转发:', '独发于', '转发于',
    '分类：', '分类:', '状态：', '状态:', '字数：', '字数:',
    '更新时间', '更新：', '更新:',
    # 封面/配图标签行：内容是图片地址，不是正文
    '封面图：', '封面图:', '封面：', '封面:', '配图：', '配图:', '插图：', '插图:',
)

# [img:…] 表情/图片标记（emoji_editor_v2 生成的格式）
_IMG_MARK_RE = re.compile(r'\[\s*img\s*[:：]?[^\]]*\]', re.IGNORECASE)
# 纯装饰分隔行：----- ===== *** ++++ 之类（含全角变体）
_SEPARATOR_RE = re.compile(
    r'^[\d\s\-/\\\.=_*#~·—○●◎＊※◇♦♢★☆♡♥✿❀+＋＝－＿﹡＊｜|]{3,}$'
)
# 纯日期行
_PURE_DATE_RE = re.compile(r'^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?$')
# 日期（不要求整行）
_ANY_DATE_RE = re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}')
_PUBLISH_WORDS = ('首发', '发布', '发表', '转发', '独发',
                  '发表于', '首发于', '发布于')


def is_meta_line(t):
    """元数据行：书名/作者/链接等前缀、纯日期、日期+发表动词、纯 URL

    注意**不包含图片行**——在简介结构里图片属于简介内容，要保留给前端渲染。
    """
    t = _clean_line(t)
    if not t:
        return False
    for p in _META_PREFIXES:
        if t.startswith(p):
            return True
    if _PURE_DATE_RE.match(t):
        return True
    if _ANY_DATE_RE.search(t) and any(k in t for k in _PUBLISH_WORDS):
        return True
    if t.startswith('http://') or t.startswith('https://'):
        return True
    return False


def is_chapter_line(t):
    """该行是否是章节标题（三级标题任一命中）"""
    t = _clean_line(t)
    if not t:
        return False
    return bool(LEVEL1_PATTERN.match(t) or
                LEVEL2_PATTERN.match(t) or
                LEVEL3_PATTERN.match(t))


# LEVEL2_PATTERN 里的「正文/番外/后记/尾声」是裸词 + 尾部 .*$，
# 于是「正文第一行，这是小说开头的内容。」这种正常正文也会被判定成章节标题。
# 章节扫描沿用原正则（改动会影响目录结构），但简介/预览的边界判定必须更严格，
# 否则正文第一行被当标题跳过，预览会凭空少一段。
_BARE_CH_TITLES = ('楔子', '引子', '引言', '前言', '序言', '正文', '番外', '后记', '尾声')
# 句读符号：真正的标题不会带这些（「正文 第一章」「番外篇：xxx」都不带句子标点）
_SENTENCE_PUNCT_RE = re.compile(r'[，。！？；、,\.!\?;]')


def is_chapter_line_strict(t):
    """简介/预览专用的章节标题判定：避免裸词误判正文

    与 is_chapter_line 的区别：只在 LEVEL2 的裸词分支上收紧。
    「第X章 / 上篇章」这类带序号的标题照旧；裸词（正文/番外/楔子…）则要求
    该行确实像标题——要么整行就是这个裸词，要么是「正文 第一章」式的短标签，
    不能是一句带句读的正文。
    """
    t = _clean_line(t)
    if not t:
        return False
    if LEVEL1_PATTERN.match(t) or LEVEL3_PATTERN.match(t):
        return True
    if not LEVEL2_PATTERN.match(t):
        return False
    # 命中 LEVEL2：带序号的标题直接认定
    if re.match(r'^\s*第(?:\d+|[〇零一二三四五六七八九十百千万]+)[篇章]', t):
        return True
    if re.match(r'^\s*[上下前后中终序][篇章]', t):
        return True
    # 裸词分支：带句读 → 是正文句子，不是标题
    if _SENTENCE_PUNCT_RE.search(t):
        return False
    stripped = t.strip(' \t：:·、-—')
    for word in _BARE_CH_TITLES:
        if stripped == word:
            return True
        if stripped.startswith(word):
            # 去掉裸词前缀后，剩下的部分要么为空，要么是「第一章/篇」之类的短标签
            rest = stripped[len(word):].strip(' \t：:·、-—')
            if not rest:
                return True
            return len(rest) <= 8
    return False


def is_separator_line(t):
    """纯符号装饰行（分隔线）"""
    return bool(_SEPARATOR_RE.match(_clean_line(t)))


def is_image_line(t):
    """整行是否只是一张图片：外链图片 / 本地图片路径 / [img:…] 表情标记"""
    t = _clean_line(t)
    if not t:
        return False
    # [img:…] 表情 / 图片标记
    if _IMG_MARK_RE.search(t):
        return True
    # 外链图片：「封面：https://…」「封面https://…」等带标签写法。
    # 只允许「封面/配图/插图/图片」这类图片标签做前缀——
    # 否则「链接：https://…」「作者博客：https://…」也会被误判成图片行。
    if re.match(r'^(?:封面图|封面|配图|插图|图片)?\s*[：:]?\s*(https?://\S+)$', t):
        return True
    # 本地图片路径：images/a.jpg、./图/01.png、D:\pics\a.jpg
    if re.match(r'^(?:[A-Za-z]:[\\/]|[./\\])?[^\s:*?"<>|]+\.'
                r'(?:jpe?g|png|gif|webp|bmp|svg)$', t, re.IGNORECASE):
        return True
    return False


# ==================== 作品指纹（work_id）====================
# 用于识别「同一本书换了文件名」，与文件名无关。
#
# 算法：MinHash 风格的「最小行哈希集合」
#   1. 正文按行归一化（去掉所有空白符），过滤掉过短的行（空行/纯序号）
#   2. 给每一行算一个固定的随机优先级（种子固定 → 跨进程/重启稳定）
#   3. 取优先级最小的 K 行，作为这本书的「指纹集合」
#   4. work_id = 指纹集合排序后整体哈希
#
# 注意：常量、盐值和算法**不要随意改动** ——
#       改了对已有缓存里的 work_id 就对不上，表现为重命名识别失效一次
#       （文件名匹配仍然有效，所以影响可控，重扫一次即可恢复）。
WORK_ID_VERSION = 2
WORK_ID_BYTES = 16              # 16 字节 = 32 位十六进制
WORK_ID_FINGERPRINT_LINES = 32  # 指纹集合大小（行数）
WORK_ID_SEED = 20240512         # 固定种子，保证跨进程稳定
WORK_ID_MIN_LINE_LEN = 6        # 太短的行（空行/序号）不参与计算
WORK_ID_MATCH_THRESHOLD = 0.5   # 相似度 >= 该值视为同一本书
WORK_ID_SALT = b'novel-work-id-v2'

# (realpath, size, mtime) -> work_id（进程内缓存，避免反复读全文）
_work_id_file_cache = OrderedDict()
MAX_WORK_ID_FILE_CACHE = 2000


def _normalize_fingerprint_line(line):
    """归一化一行文本，让空格/空白符差异不影响指纹"""
    if not line:
        return ''
    return re.sub(r'\s+', '', line)


def _fingerprint_line_hash(text):
    """单行文本 → 短哈希（指纹集合的元素）"""
    return hashlib.blake2b(text.encode('utf-8', errors='ignore'),
                           digest_size=8).hexdigest()


def _line_priority(text):
    """给一行文本算一个稳定的随机优先级（用于取「最小 K 行」）"""
    digest = hashlib.blake2b(text.encode('utf-8', errors='ignore'),
                             digest_size=16).digest()
    keyed = hashlib.blake2b(digest, key=WORK_ID_SALT, digest_size=8).digest()
    return int.from_bytes(keyed, 'big')


def extract_work_id_set(text):
    """从正文文本中抽取「指纹集合」（行哈希集合）；无有效行返回空集合"""
    if not text:
        return set()

    candidates = []
    for raw_line in text.splitlines():
        line = _normalize_fingerprint_line(raw_line)
        if len(line) >= WORK_ID_MIN_LINE_LEN:
            candidates.append(line)

    if not candidates:
        # 极短文本：退化为整篇哈希，至少保证「改名不变指纹」
        whole = _normalize_fingerprint_line(text)
        return {_fingerprint_line_hash(whole)} if whole else set()

    # 按固定优先级取最小的 K 行 —— 插入/追加不会改变已选中行的优先级
    candidates.sort(key=_line_priority)
    picked = candidates[:WORK_ID_FINGERPRINT_LINES]
    return {_fingerprint_line_hash(p) for p in picked}


def work_id_from_set(hashes):
    """指纹集合 → work_id 字符串"""
    if not hashes:
        return None
    joined = ''.join(sorted(hashes))
    return hashlib.blake2b(joined.encode('utf-8'),
                           key=WORK_ID_SALT,
                           digest_size=WORK_ID_BYTES).hexdigest()


def read_text_for_fingerprint(file_path, max_bytes=None):
    """读取正文用于计算指纹。

    max_bytes 为 None 时读取全文（建库时用）。
    """
    try:
        with open(file_path, 'rb') as f:
            head = f.read(3)
            f.seek(0)
            if head == b'\xef\xbb\xbf':
                raw = f.read()
                return raw[3:].decode('utf-8', errors='ignore')
            if head[:2] == b'\xff\xfe':
                raw = f.read()
                return raw[2:].decode('utf-16-le', errors='ignore')
            if head[:2] == b'\xfe\xff':
                raw = f.read()
                return raw[2:].decode('utf-16-be', errors='ignore')

            raw = f.read() if max_bytes is None else f.read(max_bytes)

        for enc in ('utf-8', 'gbk', 'gb18030', 'big5'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f"读取指纹内容失败 {file_path}: {e}")
        return ''


def read_and_decode_novel(file_path):
    """一次性读取并解码整本小说，返回 (raw_bytes, text, encoding)。

    扫描时 work_id 与详情解析都需要全文，过去各读一次；
    抽出公共实现让调用方读一次、两处复用。解码顺序与
    parse_novel_details 保持一致，保证两条路径结果相同。
    encoding 必须原样传给 parse_novel_details —— 它会进入行索引缓存，
    传哨兵值（如 'prefetched'）会让阅读页的增量解码器直接抛 LookupError。
    """
    with open(file_path, 'rb') as f:
        raw_data = f.read()

    if raw_data[:3] == b'\xef\xbb\xbf':
        return raw_data, raw_data[3:].decode('utf-8'), 'utf-8'
    if raw_data[:2] == b'\xff\xfe':
        return raw_data, raw_data[2:].decode('utf-16-le'), 'utf-16-le'
    if raw_data[:2] == b'\xfe\xff':
        return raw_data, raw_data[2:].decode('utf-16-be'), 'utf-16-be'

    for enc in ('utf-8', 'gbk', 'gb18030', 'big5'):
        try:
            return raw_data, raw_data.decode(enc), enc
        except UnicodeDecodeError:
            continue

    try:
        detected = chardet.detect(raw_data[:65536]).get('encoding') or 'utf-8'
    except Exception:
        detected = 'utf-8'
    return raw_data, raw_data.decode(detected, errors='ignore'), detected


def compute_work_id(file_path, _use_cache=True, text=None):
    """计算文件的 work_id（必须基于全文，不能用前缀近似）

    text：调用方若已读过并解码全文，可直接传入，避免同一文件被读第二遍
    （扫描时 work_id 与详情解析都需要全文，这是主要耗时）。
    """
    if not file_path or not os.path.isfile(file_path):
        return None

    try:
        stat = os.stat(file_path)
        cache_key = (os.path.realpath(file_path), stat.st_size, stat.st_mtime)
    except OSError:
        return None

    if _use_cache and cache_key in _work_id_file_cache:
        _work_id_file_cache.move_to_end(cache_key)
        return _work_id_file_cache[cache_key]

    if text is None:
        text = read_text_for_fingerprint(file_path)
    work_id = work_id_from_set(extract_work_id_set(text))

    if _use_cache:
        _work_id_file_cache[cache_key] = work_id
        while len(_work_id_file_cache) > MAX_WORK_ID_FILE_CACHE:
            _work_id_file_cache.popitem(last=False)

    return work_id


def extract_preview_clean(lines, max_lines=12, max_chars=600):
    """取正文开头作为预览。"""
    # 1. 跳过开头的元数据行；顺带收集封面/配图行，正文为空时兜底显示
    start = 0
    cover_lines = []
    for i in range(min(len(lines), 80)):
        t = _clean_line(lines[i])
        if not t:
            continue
        if is_image_line(t):
            cover_lines.append(t)
            start = i + 1
            continue
        if is_meta_line(t):
            start = i + 1
            continue
        if is_chapter_line_strict(t):
            start = i + 1  # 跳过章节标题本身
            break
        if len(t) > 3:
            start = i
            break

    # 2. 从 start 开始收集正文
    collected = []
    total_chars = 0

    for i in range(start, len(lines)):
        t = _clean_line(lines[i])

        if not t:
            if collected:
                break
            continue

        if is_meta_line(t):
            continue
        if is_separator_line(t):
            continue
        if len(t) <= 1:
            continue

        collected.append(t)
        total_chars += len(t)

        if len(collected) >= max_lines or total_chars >= max_chars:
            break

    if not collected:
        # 没有正文可预览，但有封面/配图 → 返回封面块（前端会渲染成 <img>）
        if cover_lines:
            return '\n'.join(cover_lines)
        return None

    preview = '\n'.join(collected)
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + '……'

    return preview


# ==================== 简介提取函数 =====================
# 这些 txt 的结构很简单，简介就是「元数据结束 → 第一个章节标题」之间那一段。
# 所以这里不做任何「这是不是配图小标题」的猜测，只做三件事：
#   1. 定位简介段的起止
#   2. 认出其中的图片行（外链图片 / 本地图片 / [img:…] 表情），原样保留，
#      由前端 convertImageLinks() 渲染成 <img>
#   3. 其余行原样当文字保留
# 这样「作者配图」「摄影师配图」或任何别的写法，都只是简介里的一行普通文字，
# 不需要维护任何关键字表。
_INTRO_MARKERS = (
    '简介', '内容简介', '作品简介', '故事简介', '小说简介',
    '写在前面', '文案', '介绍', '故事介绍', '题记',
    '作者言', '作者语', '作者的话', '自序', '作者注', '作者按', '说明',
    '书籍简介', '本书简介', '文章简介',
)


def _match_intro_marker(t):
    """返回 (是否是简介标记, 冒号后的内容)"""
    t = _clean_line(t)
    for m in _INTRO_MARKERS:
        mt = re.match(rf'^{re.escape(m)}[：:]\s*(.*)$', t)
        if mt:
            return True, mt.group(1).strip()
    return False, ''


def extract_intro_clean(lines):
    """从正文行里提取简介；没有则返回 '无简介'"""
    if not lines:
        return '无简介'

    # ========== 1. 定位简介段 ==========
    # 起点：跳过开头的元数据行；有「简介：」则从它下一行开始。
    start = 0
    intro_marker_content = ''
    for i in range(min(len(lines), 50)):
        t = _clean_line(lines[i])
        if not t:
            continue
        is_marker, content = _match_intro_marker(t)
        if is_marker:
            intro_marker_content = content
            start = i + 1
            break
        if is_meta_line(t):
            start = i + 1
            continue
        # 章节标题或第一条普通正文 → 简介段从这里开始
        start = i
        break

    # 终点：第一个章节标题行（找不到就到文件末尾）
    end = len(lines)
    for i in range(start, len(lines)):
        if is_chapter_line_strict(_clean_line(lines[i])):
            end = i
            break

    # ========== 2. 逐行收集 ==========
    # 空行保留（用于分段），图片行保留（前端渲染成图片），其余文字原样保留。
    collected = []
    total_chars = 0

    for line in lines[start:end]:
        t = _clean_line(line)

        if not t:
            if collected:
                collected.append('')
            continue

        # 图片行：原样保留，交给前端渲染
        if is_image_line(t):
            collected.append(t)
            continue

        # 纯符号分隔行
        if is_separator_line(t):
            continue

        # 其他元数据行（书名/作者/链接等）不属于简介
        if is_meta_line(t):
            continue

        total_chars += len(t)
        if total_chars > 3000:
            # 这一段太长，说明其实是正文而非简介
            return '无简介'

        collected.append(t)

    # 去掉首尾空行
    while collected and not collected[0]:
        collected.pop(0)
    while collected and not collected[-1]:
        collected.pop()

    intro = '\n'.join(collected).strip()

    # 「简介：内容」写在冒号后面的写法
    if intro_marker_content:
        intro = f"{intro_marker_content}\n{intro}".strip() if intro else intro_marker_content

    return intro if intro else '无简介'


# 与 extract_intro_clean / _META_PREFIXES 同义的图片行判定（本地图片、外链、
# [img:…] 标记）。「简介里只有图、没有文字」的书，提取结果里的文字只剩这些
# 标记 —— is_valid_intro 检查前必须先剔除，否则整段简介被判无效、丢成「无简介」。
_INTRO_IMAGE_LINE_RE = re.compile(
    r'^(?:'
    r'\[\s*img\s*[:：]?[^\]]*\]'                     # [img:01 caption=封面]
    r'|(?:封面图|封面|配图|插图|图片)?\s*[：:]?\s*https?://\S+'   # 封面：https://…
    r'|(?:[A-Za-z]:[\\/]|[./\\])?[^\s:*?"<>|]+\.(?:jpe?g|png|gif|webp|bmp|svg)'  # 本地路径
    r')$',
    re.IGNORECASE,
)


def intro_text_part(intro):
    """去掉简介里的图片行，只留文字部分（用于有效性校验）

    正文/阅读页会把图片行原样渲染成 <img>，所以图片行必须留在简介里；
    但它们不是文字，不能参与「过短 / 无标点」这类文字质量校验。
    """
    if not intro or intro == '无简介':
        return ''
    kept = [
        ln for ln in re.split(r'\r?\n', intro)
        if ln.strip() and not _INTRO_IMAGE_LINE_RE.match(_clean_line(ln))
    ]
    return '\n'.join(kept).strip()


def is_valid_intro(intro):
    """简介有效性校验：排除元数据误截、过短、无标点的内容

    ⚠️ 只看文字部分（intro_text_part）：以 [img:…] 开头的图文小说，正文全是
    「一句简述 + 多张配图」，旧逻辑拿标记行当文字算「无标点」，
    于是简介被判无效、详情页只剩预览，图片标记一并丢失。
    """
    if not intro or intro == '无简介':
        return False
    if any(kw in intro for kw in ['书名：', '作者：', '标签：', '链接：']):
        return False
    text = intro_text_part(intro)
    if not text:
        # 纯图片简介（只有 [img:…] / 图片链接），没有正文可预览时也要能显示
        return True
    return len(text) > 10 and bool(re.search(r'[，。！？；：、]', text))


def _intro_section_start(lines):
    """返回简介段起始行号（0-based）；与 extract_intro_clean 的起点判定保持一致。

    用于「全文阅读」虚拟章节定位：跳过文件头元数据，避免从书名/作者行开始读。
    """
    if not lines:
        return 0
    for i in range(min(len(lines), 50)):
        t = _clean_line(lines[i])
        if not t:
            continue
        is_marker, _ = _match_intro_marker(t)
        if is_marker:
            return i + 1
        if is_meta_line(t):
            continue
        return i
    return 0

# ==================== 快速解析文件头部获取元数据 =====================
def parse_file_content_fast(file_path):
    """快速解析TXT文件头部获取元数据（包含简介）"""
    current_hash = get_file_hash(file_path)
    if file_path in tag_parse_cache:
        cached_hash, cached_result = tag_parse_cache[file_path]
        if cached_hash == current_hash:
            return cached_result
    
    header = read_file_header(file_path, max_size=65536)
    
    if not header:
        result = {
            'title': '解析失败',
            'author': '未知作者',
            'site': '未知网站',
            'word_count': 0,
            'chapter_count': 1,
            'tags': '无',
            'publish_date': '未知',
            'file_path': file_path,
            'intro': '无简介'
        }
        tag_parse_cache[file_path] = (current_hash, result)
        return result
    
    lines = re.split(r'\r?\n|\r', header)
    
    title = strip_txt_ext(os.path.basename(file_path))
    author = "未知作者"
    site = "未知网站"
    link = ""
    publish_date = "未知"
    tags_from_meta = []
    
    meta_keywords = [
        '书名：', '作者：', '链接：', '标签：', '内容简介：', '说明：',
        '首发于：', '首发于', '发布于：', '发布于', '发表于：', '发表于',
        '发布：', '发布', '首发：', '首发', '发表：', '转发：', '独发于', '转发于'
    ]
    
    found_meta = False
    meta_ended = False
    
    for line in lines[:30]:
        line = line.replace('\ufeff', '').strip()
        if not line:
            if found_meta:
                meta_ended = True
            continue
        
        if meta_ended:
            break
        
        is_meta_line = any(line.startswith(kw) for kw in meta_keywords)
        
        date_match = re.search(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)', line)
        publish_keywords = ['首发于', '发布于', '发表于', '发布', '首发', '发表', '转发', '独发']
        has_date_and_publish = date_match and any(kw in line for kw in publish_keywords)
        is_date_only = re.match(r'^\s*\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?\s*$', line)
        is_meta_line = is_meta_line or has_date_and_publish or is_date_only
        
        if line.startswith('链接：') or line.startswith('链接:'):
            found_meta = True
            link = line[3:].strip()
            if not link.startswith('http'):
                link_match = re.search(r'(https?://[^\s）\)>]+)', line)
                if link_match:
                    link = link_match.group(1)
            continue
        
        if line.startswith('标签：'):
            found_meta = True
            tag_raw = line[3:].strip()
            tags_list = re.split(r'[ /＃#，,、；;|、\s]+', tag_raw)
            tags_from_meta = [t.strip() for t in tags_list if t.strip()]
            continue
        
        if is_meta_line:
            found_meta = True
            
            if line.startswith('书名：') and title == strip_txt_ext(os.path.basename(file_path)):
                title = line[3:].strip()
            elif line.startswith('作者：'):
                author_raw = line[3:].strip()
                if '＆' in author_raw or '&' in author_raw or '、' in author_raw:
                    author_parts = re.split(r'[＆&、]', author_raw)
                    author_parts = [normalize_name(p.strip(), 'author') for p in author_parts if p.strip()]
                    author = ','.join(author_parts)
                else:
                    author = normalize_name(author_raw, 'author')
            else:
                publish_keywords = ['首发于：', '首发于', '发布于：', '发布于', '发表于：', '发表于', '发布：', '发布', '首发：', '首发', '发表：', '转发：', '独发于', '转发于']
                
                found_site = False
                for keyword in publish_keywords:
                    pos = line.find(keyword)
                    if pos != -1:
                        if site == '未知网站' and not found_site:
                            after_keyword = line[pos + len(keyword):].strip()
                            after_keyword = re.sub(r'^[：:：\s]*', '', after_keyword)
                            after_keyword = re.sub(r'[。，、；：\s]+$', '', after_keyword)
                            if after_keyword and len(after_keyword) < 30:
                                if not re.search(r'第[0-9零一二三四五六七八九十百千万]+[篇部章节回目]', after_keyword):
                                    site = normalize_name(after_keyword, 'site')
                                    found_site = True
                        
                        if publish_date == '未知':
                            date_match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?', line)
                            if date_match:
                                year, month, day = date_match.groups()
                                month = month.zfill(2)
                                day = day.zfill(2)
                                publish_date = f"{year}-{month}-{day}"
                        
                        if found_site and publish_date != '未知':
                            break
        else:
            if found_meta:
                line_clean = line.strip()
                if len(line_clean) < 10 and not re.search(r'[，。！？；：、]', line_clean):
                    continue
                if (LEVEL1_PATTERN.match(line_clean) or 
                    LEVEL2_PATTERN.match(line_clean) or 
                    LEVEL3_PATTERN.match(line_clean)):
                    continue
                if len(line_clean) > 15 or re.search(r'[，。！？；：、]', line_clean):
                    meta_ended = True
    
    file_size = os.path.getsize(file_path)
    estimated_words = file_size // 2

    chapter_titles = set()
    title_count = 0
    for line in lines[:500]:
        line_clean = line.strip()
        if not line_clean or len(line_clean) > 100:
            continue
        if (LEVEL1_PATTERN.match(line_clean) or 
            LEVEL2_PATTERN.match(line_clean) or 
            LEVEL3_PATTERN.match(line_clean)):
            chapter_titles.add(line_clean.lower())
            title_count += 1
            if title_count >= 200:
                break
    
    titles_text = ' '.join(chapter_titles)
    intro_text = header[:30000].lower()
    combined_text_lower = titles_text + ' ' + intro_text
    
    tags_set = set()

    if tags_from_meta:
        for tag in tags_from_meta:
            tags_set.add(tag)

    if CONFIG.get('auto_tag_enabled', True):
        for original_keyword, keyword_lower in zip(TAG_KEYWORDS, TAG_KEYWORDS_LOWER):
            # ⚠️ 配图/视频/音频 是文件系统存在性标记，由下方 scan_media_types
            # 按配图目录实际内容生成，不能参与正文关键词匹配 ——
            # 小说里写到「视频」二字太常见，否则会把大量纯文字小说误标成「视频」。
            if keyword_lower in MEDIA_TAG_NAMES:
                continue
            if keyword_lower and keyword_lower in combined_text_lower:
                tags_set.add(normalize_tag(original_keyword))
    
    # ===== 在 parse_file_content_fast 中 =====

    filename = os.path.basename(file_path)
    if '完' in filename or '完结' in filename:
        tags_set.add('完结')

    # ===== 检测配图文件夹中的媒体文件（复用 get_image_folder_for_novel，支持 _images 和 _配图）=====
    media_folder = get_image_folder_for_novel(filename)

    if media_folder:
        # 递归扫描 + 统一扩展名，避免子目录遗漏与大小写/格式漂移
        media_types = scan_media_types(media_folder)

        if media_types['image']:
            tags_set.add('配图')
        if media_types['video']:
            tags_set.add('视频')
        if media_types['audio']:
            tags_set.add('音频')
        
    tags = list(tags_set)
    
    if tags:
        tags = derive_tags(tags)
        tags = clean_tags(tags)
    
    # 简介 / 预览：与 parse_novel_details 走同一套提取函数，避免两条路径给出不同结果
    intro = extract_intro_clean(lines)

    # 预览无条件提取：即使有简介也留一份正文开头，
    # 前端在卡片上展示时更丰富，且两边缓存字段才能对齐。
    preview = extract_preview_clean(lines)
    
    result = {
        'title': title[:50] + '...' if len(title) > 50 else title,
        'author': author,
        'site': site,
        'word_count': estimated_words,
        'chapter_count': 1,
        'tags': ','.join(tags) if tags else '无',
        'publish_date': publish_date,
        'link': link,
        'file_path': file_path,
        'intro': intro,
        'preview': preview   # 🔥 新增
    }
    
    tag_parse_cache[file_path] = (current_hash, result)
    return result


# ================== 标签相关函数 ==================
def normalize_tag(tag):
    """把各种别名统一为主标签"""
    if not tag:
        return ''
    tag = str(tag).lower().strip()
    return TAG_ALIAS_TO_MAIN.get(tag, tag)

# ================== 清理和规范化标签 ==================
def clean_tags(tags_list):
    """清理和规范化标签"""
    if not tags_list:
        return []
    
    mapped = [normalize_tag(tag) for tag in tags_list if tag]
    
    seen = set()
    result = []
    for tag in mapped:
        tag = tag.strip()
        if tag and tag != '无' and len(tag) <= 12:
            if tag not in seen:
                seen.add(tag)
                result.append(tag)
    
    return result


def derive_tags(original_tags_list):
    """根据已有标签推导隐含的上级标签"""
    if not original_tags_list or not CONFIG.get('enable_derived_tags', True):
        return list(original_tags_list or [])

    result = set(original_tags_list)
    queue = list(result)
    while queue:
        tag = queue.pop()
        for implied_tag in TAG_IMPLICATIONS.get(tag, []):
            if implied_tag not in result:
                result.add(implied_tag)
                queue.append(implied_tag)

    return list(result)

# ================== 检测文件编码（统一版本） ==================
def detect_encoding(file_path):
    """检测文件编码（统一版本）"""
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            
            if raw_data[:3] == b'\xef\xbb\xbf':
                return 'utf-8-sig'
            if raw_data[:2] == b'\xff\xfe':
                return 'utf-16-le'
            if raw_data[:2] == b'\xfe\xff':
                return 'utf-16-be'
            
            try:
                result = chardet.detect(raw_data)
                encoding = result.get('encoding', '')
                if encoding and encoding.lower() in ['gb2312', 'gbk', 'big5']:
                    return 'gbk'
                return encoding if encoding else 'utf-8'
            except:
                return 'utf-8'
    except:
        return 'utf-8'


def read_file_with_encoding(file_path):
    """使用检测到的编码读取文件"""
    encoding = detect_encoding(file_path)
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError:
        for enc in ['utf-8', 'gbk', 'gb18030', 'big5', 'latin-1']:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    return f.read()
            except:
                continue
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()


# ==================== 空章节判定 =====================
# 有些小说文件为了排版会插入「只有标题、没有正文」的章节。
# 这类章节在目录里仍然要显示，但不应该可点击（点进去是空白页）。
# 判定方式：一个章节从它的标题行之后，到下一个章节标题行之前，
# 如果没有任何一行含实际正文（非空白、非分隔线一类的装饰行），
# 就认为它是空章节。
_EMPTY_CHAPTER_IGNORE_PATTERN = re.compile(
    r'^[\s\-—–~=*＊·•.。…_#※☆★✦✧]+$'
)


def _is_meaningful_body_line(line):
    """判断一行是否算「正文内容」（排除空行与分隔线装饰行）"""
    stripped = line.strip()
    if not stripped:
        return False
    if _EMPTY_CHAPTER_IGNORE_PATTERN.match(stripped):
        return False
    return True


def mark_empty_chapters(all_chapters, lines):
    """给每个章节打上 is_empty 标记，返回被标记为空的章节数

    传入的 all_chapters 必须已按 line_number 升序排列。
    """
    if not all_chapters:
        return 0

    total_lines = len(lines)
    empty_count = 0

    for idx, chapter in enumerate(all_chapters):
        start = chapter.get('line_number', 1)  # 1-based，指向标题行本身
        if idx + 1 < len(all_chapters):
            # 下一个章节的标题行不计入本章正文
            end = all_chapters[idx + 1].get('line_number', start) - 1
        else:
            end = total_lines

        # 只截取标题行之后的部分
        body = lines[start:max(start, end)] if end >= start else []

        has_body = any(_is_meaningful_body_line(line) for line in body)
        chapter['is_empty'] = not has_body
        if not has_body:
            empty_count += 1

    return empty_count


def parse_novel_details(file_path, prefetched=None):
    """解析小说详情：提取简介和三级章节结构（带缓存）

    prefetched：可选 (raw_bytes, text)。扫描流程里 compute_work_id 已读过全文，
    传入即可避免重复整本读取。
    """
    import time
    start = time.time()
    
    current_hash = get_file_hash(file_path)
    if prefetched is None and file_path in chapter_cache:
        cached_info = chapter_cache[file_path]
        if isinstance(cached_info, dict) and cached_info.get('file_hash') == current_hash:
            # hash 一致也再校验一次简介：旧版本写进去的坏简介（混入元数据、
            # 被截断成半行）不该继续复用，否则页面会一直显示错的简介。
            cached_intro = cached_info.get('intro', '') or ''
            if cached_intro and cached_intro != '无简介' and not is_valid_intro(cached_intro):
                print("🗑️ 缓存简介无效，重新解析")
                del chapter_cache[file_path]
            else:
                # 旧缓存可能没有 is_empty 标记（升级前生成的缓存），
                # 这种书必须重新解析补上空章节标记，否则详情页/阅读页
                # 跳过空白章节的功能不生效（直接命中旧缓存就被 return 了）。
                if any('is_empty' not in c for c in cached_info.get('all_chapters', [])):
                    print("🗑️ 缓存缺少空章节标记，重新解析")
                    del chapter_cache[file_path]
                else:
                    return cached_info
        else:
            if file_path in chapter_cache:
                del chapter_cache[file_path]
    
    image_info = get_novel_image_info(file_path)
    file_size = os.path.getsize(file_path)
    print(f"📖 开始解析: {os.path.basename(file_path)} ({file_size/1024/1024:.2f} MB)")
    
    t1 = time.time()
    pre_encoding = None
    if prefetched is not None:
        raw_data, _pre_text, pre_encoding = prefetched
        print(f"   ⏱️ 复用预读内容（跳过重复读取）")
    else:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
    raw_for_index = raw_data
    print(f"   ⏱️ 读取文件: {time.time()-t1:.3f}s")
    
    t2 = time.time()
    content = None

    if prefetched is not None:
        # 预读路径：直接复用已解码文本，跳过编码探测。
        # 编码必须用预读时的真实值 —— 哨兵值一旦传进行索引缓存，
        # 阅读页 codecs.getincrementaldecoder('prefetched') 会抛 LookupError
        content = _pre_text
        encoding = pre_encoding or 'utf-8'
    elif raw_data[:3] == b'\xef\xbb\xbf':
        content = raw_data[3:].decode('utf-8')
        encoding = 'utf-8-sig'
    elif raw_data[:2] == b'\xff\xfe':
        content = raw_data[2:].decode('utf-16-le')
        encoding = 'utf-16-le'
    elif raw_data[:2] == b'\xfe\xff':
        content = raw_data[2:].decode('utf-16-be')
        encoding = 'utf-16-be'
    else:
        for enc in ['utf-8', 'gbk', 'gb18030', 'big5']:
            try:
                content = raw_data.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            sample = raw_data[:65536]
            result = chardet.detect(sample)
            encoding = result['encoding'] or 'utf-8'
            content = raw_data.decode(encoding, errors='ignore')
    
    print(f"   ⏱️ 检测编码: {time.time()-t2:.3f}s, 编码={encoding}")
    
    if content.startswith('\ufeff'):
        content = content[1:]
    
    content = content.lstrip('\ufeff\u200b\u200c\u3000')
    set_line_index(file_path, current_hash, raw_for_index, encoding)
    lines = re.split(r'\r?\n|\r', content)
    
    # ========== 简介提取（统一走 extract_intro_clean）==========
    # 简介段起止由 extract_intro_clean 内部判定（元数据行跳过 → 首个章节标题截止），
    # 这里不再重复维护一套 meta_end_line / chapter_start_line 的边界推导。
    intro = extract_intro_clean(lines)
    intro_start_line = _intro_section_start(lines)

    # 没有简介时，提取正文开头作为预览
    # 预览无条件提取；intro 单独判定
    preview = extract_preview_clean(lines)
    if intro == '无简介':
        print(f"📝 无简介，提取预览: {len(preview) if preview else 0} 字")
    elif len(intro) > 50:
        print(f"📝 提取简介: {intro[:50]}...")
    else:
        print(f"📝 提取简介: {intro}")

    max_lines_to_scan = len(lines)
    chapters_level1 = []
    chapters_level2 = []
    chapters_level3 = []
    all_chapters = []
    
    for i, line in enumerate(lines[:max_lines_to_scan]):
        line_clean = line.strip()
        if not line_clean or len(line_clean) > 100:
            continue
        
        if LEVEL1_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 1}
            chapters_level1.append(chapter_info)
            all_chapters.append(chapter_info)
        elif LEVEL2_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 2}
            chapters_level2.append(chapter_info)
            all_chapters.append(chapter_info)
        elif LEVEL3_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 3}
            chapters_level3.append(chapter_info)
            all_chapters.append(chapter_info)
        
        if len(all_chapters) > 5000:
            print(f"⚠️ 已找到 {len(all_chapters)} 个章节，停止扫描")
            break
    
    print(f"📚 找到章节：一级 {len(chapters_level1)} 个，二级 {len(chapters_level2)} 个，三级 {len(chapters_level3)} 个")

    if not all_chapters:
        start_line = intro_start_line + 1
        virtual_chapter = {
            'text': '全文阅读',
            'line_number': start_line,
            'level': 1
        }
        all_chapters = [virtual_chapter]
        chapters_level1 = [virtual_chapter]
        print(f"📖 无章节结构，自动添加虚拟章节，从第 {start_line} 行开始")
    
    all_chapters = sorted(all_chapters, key=lambda x: x['line_number'])
    mark_empty_chapters(all_chapters, lines)

    result = {
        'intro': intro if intro and intro != '无简介' else '无简介',
        'preview': preview, 
        'chapters_level1': chapters_level1,
        'chapters_level2': chapters_level2,
        'chapters_level3': chapters_level3,
        'all_chapters': all_chapters,
        'encoding': encoding,
        'has_images': image_info is not None,
        'image_folder': image_info['folder'] if image_info else None,
        'image_files': image_info['files'] if image_info else [],
        'line_count': len(lines),
        'file_hash': current_hash
    }
    
    chapter_cache[file_path] = result
    
    # 桌面版内存充裕，缓存上限放宽到 500 本（翻过的书基本都能秒开章节列表）；
    # Docker 版仍保持 200，那边要顾 NAS 的内存和缓存文件体积。
    CHAPTER_CACHE_MAX = 500
    if len(chapter_cache) > CHAPTER_CACHE_MAX:
        old_keys = list(chapter_cache.keys())[:50]
        for key in old_keys:
            del chapter_cache[key]
    
    return result


# 后台扫描函数
def scan_novel_files_background(full_scan=False):
    """后台扫描小说目录。

    修复点：
    - 扫描结果为空时也会正确清空 novel_data，不再残留已删除小说；
    - 全量扫描时解析章节详情，而不是只调用快速解析；
    - 异常时日志仍能打印正确的处理数量/耗时；
    - 应用 exclude_patterns / max_file_size_mb 配置。
    """
    global novel_data, scan_progress, chapter_cache, tag_parse_cache, image_cache

    # 首次扫描没有缓存时，即使调用方传 full_scan=False 也按全量扫描处理，
    # 否则只会调用快速解析，缺少章节详情。
    if not novel_data:
        full_scan = True

    start_time = time.time()
    files_to_scan = []
    scan_progress['start_time'] = start_time

    logger.info(f"开始扫描 - full_scan={full_scan}, 当前小说数={len(novel_data)}")

    if scan_progress['status'] == 'scanning':
        print("⚠️ 已有扫描任务进行中，跳过本次扫描")
        return

    try:
        scan_progress['status'] = 'scanning'
        scan_progress['current'] = 0
        scan_progress['phase'] = 'scan_dir'
        scan_progress['incremental'] = not full_scan
        scan_progress['message'] = '正在扫描目录...'

        if not os.path.exists(NOVEL_DIR):
            scan_progress['status'] = 'error'
            scan_progress['message'] = f'目录不存在：{NOVEL_DIR}'
            return

        # 记录「扫描进行中」标记：正常结束会清除，程序若在扫描途中退出，
        # 下次启动时 check_interrupted_scan() 就能发现上次没跑完
        try:
            save_scan_stats({
                'scan_in_progress': {
                    'type': 'full' if full_scan else 'incremental',
                    'start_time': start_time,
                }
            })
        except Exception as e:
            logger.warning(f"写入扫描进行中标记失败（不影响扫描）：{e}")

        exclude_patterns = [p for p in (CONFIG.get('exclude_patterns') or []) if p]
        try:
            max_size_bytes = int(CONFIG.get('max_file_size_mb', 100) or 0) * 1024 * 1024
        except (TypeError, ValueError):
            max_size_bytes = 0

        all_files = {}
        for filename in os.listdir(NOVEL_DIR):
            if not filename.endswith(('.txt', '.TXT')):
                continue
            if any(pattern in filename for pattern in exclude_patterns):
                logger.info(f"跳过排除项: {filename}")
                continue

            file_path = os.path.join(NOVEL_DIR, filename)
            try:
                if max_size_bytes and os.path.getsize(file_path) > max_size_bytes:
                    logger.warning(f"跳过超大文件: {filename}")
                    continue
            except OSError as e:
                logger.warning(f"读取文件大小失败，跳过 {filename}: {e}")
                continue
            all_files[filename] = file_path

        scan_progress['total'] = len(all_files)

        changed_files_list = []
        image_changed_files = []
        new_files = []
        changed_files = []
        unchanged_files = []

        if not full_scan and novel_data:
            existing_files = {}
            for item in novel_data:
                filename = os.path.basename(item.get('file_path', ''))
                if filename:
                    existing_files[filename] = item

            _check_total = len(all_files)
            _checked = 0
            for filename, file_path in all_files.items():
                _checked += 1
                # 每 50 个文件刷新一次进度：这是增量扫描最耗时的环节
                if _checked % 50 == 0:
                    scan_progress['current'] = _checked
                    scan_progress['total'] = _check_total
                    scan_progress['message'] = f'正在检查书目：{_checked}/{_check_total}'
                try:
                    current_mtime = os.path.getmtime(file_path)
                except OSError:
                    continue

                if filename in existing_files:
                    old_item = existing_files[filename]
                    old_mtime = old_item.get('mtime')

                    if old_mtime == current_mtime:
                        new_image_folder = get_image_folder_for_novel(filename)
                        new_has_images = new_image_folder is not None

                        # 老缓存可能没有 work_id（本功能加入前生成的），
                        # 增量扫描时补算一次，避免一直缺失。
                        if not old_item.get('work_id'):
                            try:
                                old_item['work_id'] = compute_work_id(file_path)
                            except Exception as e:
                                logger.warning(f"补算 work_id 失败 {filename}: {e}")

                        # 🔥 未变化的文件也要刷新媒体标签。
                        # 「配图/视频/音频」原本只在 parse_file_content_fast
                        # 里生成，而未变化文件不会重跑该函数 —— 于是后往配图
                        # 目录里加的图/视频，标签永远停在首次扫描那一刻。
                        # 这里单独重算，成本仅一次目录遍历，远低于重解析整本。
                        if new_image_folder:
                            _refresh_media_tags(old_item, new_image_folder)
                        else:
                            _strip_media_tags(old_item)

                        if new_has_images != old_item.get('has_images', False) or new_image_folder != old_item.get('image_folder'):
                            print(f"🖼️ 配图变化: {filename}")
                            image_changed_files.append(filename)
                            old_item['has_images'] = new_has_images
                            old_item['image_folder'] = new_image_folder
                            base_name = strip_txt_ext(filename)
                            image_cache.pop(base_name, None)
                            unchanged_files.append(old_item)
                        else:
                            old_item['file_path'] = file_path
                            unchanged_files.append(old_item)
                    else:
                        changed_files.append(filename)
                        changed_files_list.append(filename)
                        chapter_cache.pop(file_path, None)
                        tag_parse_cache.pop(file_path, None)
                        base_name = strip_txt_ext(filename)
                        image_cache.pop(base_name, None)
                else:
                    new_files.append(filename)

            files_to_scan = new_files + changed_files
            # 检查阶段收尾，切到解析阶段（百分比由接口按阶段加权）
            scan_progress['phase'] = 'parse'
            scan_progress['current'] = 0
            scan_progress['total'] = len(files_to_scan)

            message_parts = []
            if new_files:
                message_parts.append(f"{len(new_files)} 个新增")
            if changed_files:
                message_parts.append(f"{len(changed_files)} 个修改")
            if image_changed_files:
                message_parts.append(f"{len(image_changed_files)} 个配图变化")

            scan_progress['message'] = (
                f"发现 {', '.join(message_parts)}，将扫描 {len(files_to_scan)} 个文件"
                if message_parts else "没有文件变化"
            )
            temp_data = unchanged_files.copy()
        else:
            chapter_cache.clear()
            tag_parse_cache.clear()
            image_cache.clear()
            print("✅ 全量扫描：已清空所有缓存")

            files_to_scan = list(all_files.keys())
            temp_data = []
            # 全量扫描没有「检查书目」阶段，直接进入解析（百分比 0-100）
            scan_progress['phase'] = 'parse'
            scan_progress['current'] = 0
            scan_progress['total'] = len(files_to_scan)
            scan_progress['message'] = f'完全扫描 {len(files_to_scan)} 个文件...'

        files_needing_details = set(all_files.keys()) if full_scan else (set(new_files) | set(changed_files_list))
        batch_size = 50
        for batch_start in range(0, len(files_to_scan), batch_size):
            batch = files_to_scan[batch_start:batch_start + batch_size]

            for filename in batch:
                scan_progress['current'] += 1
                scan_progress['message'] = f'正在解析：{filename[:30]}...'
                file_path = all_files[filename]

                if not is_file_readable(file_path):
                    logger.warning(f"文件不可读，跳过: {filename}")
                    continue

                try:
                    base_info = {
                        'filename': filename,
                        'progress': parse_progress(filename),
                        'file_size': os.path.getsize(file_path) // 1024,
                        'file_hash': get_file_hash(file_path),
                        'mtime': os.path.getmtime(file_path),
                        'file_path': file_path
                    }
                except OSError as e:
                    logger.warning(f"读取文件信息失败，跳过 {filename}: {e}")
                    continue

                # 🔥 性能：整本只读一次。
                # work_id 需要全文，详情解析也需要全文，过去各读一次。
                # 这里先读一次，解码结果同时喂给两者；
                # 只在「需要算 work_id」或「详情未命中缓存」时才读盘。
                _need_details = filename in files_needing_details
                _details_cached = (not _need_details) or (
                    file_path in chapter_cache
                    and isinstance(chapter_cache.get(file_path), dict)
                    and chapter_cache[file_path].get('file_hash') == get_file_hash(file_path)
                )
                prefetched = None
                _cached_wid = None
                try:
                    _st = os.stat(file_path)
                    _ck = (os.path.realpath(file_path), _st.st_size, _st.st_mtime)
                    _cached_wid = _work_id_file_cache.get(_ck)
                except OSError:
                    pass

                if _cached_wid is None or not _details_cached:
                    try:
                        prefetched = read_and_decode_novel(file_path)
                    except Exception as e:
                        logger.warning(f"读取正文失败 {filename}: {e}")

                # work_id：「作品指纹」，与文件名无关。
                # 缓存里存一份，重启加载时不必为了它重读全文。
                try:
                    base_info['work_id'] = compute_work_id(
                        file_path,
                        text=(prefetched[1] if prefetched else None))
                except Exception as e:
                    logger.warning(f"计算 work_id 失败 {filename}: {e}")
                    base_info['work_id'] = None

                try:
                    content_info = parse_file_content_fast(file_path) or {}
                except Exception as e:
                    logger.warning(f"快速解析失败，跳过 {filename}: {e}")
                    continue

                if _need_details:
                    try:
                        detail_info = parse_novel_details(file_path, prefetched=prefetched)
                        if detail_info.get('intro') and detail_info.get('intro') != '无简介':
                            content_info['intro'] = detail_info['intro']
                        if detail_info.get('all_chapters'):
                            content_info['chapter_count'] = len(detail_info['all_chapters'])
                    except Exception as e:
                        logger.warning(f"解析章节详情失败 {filename}: {e}")

                if 'intro' not in content_info:
                    content_info['intro'] = '无简介'

                novel_info = {**base_info, **content_info}

                # 🔥 修复：全量/重新解析的条目必须补上配图目录字段。
                # 过去只有「未变化」与「改名」分支会写 has_images/image_folder，
                # 走解析分支的条目（含全量扫描的全部书）这两个字段一直缺失
                # （has_images=False, image_folder=None），导致详情页拿不到配图，
                # 即使 _images 目录确实存在。
                _img_folder = get_image_folder_for_novel(filename)
                novel_info['has_images'] = _img_folder is not None
                novel_info['image_folder'] = _img_folder

                temp_data.append(novel_info)

            # 改为让出 CPU（sleep(0)）而不是固定等 50ms：
            # 5000 本书按批累积下来会白等好几分钟，而真正瓶颈是磁盘 I/O。
            time.sleep(0)

        temp_data.sort(key=lambda x: (x.get('filename') or '').lower())
        novel_data = temp_data.copy()
        save_cache()

        if not full_scan:
            message_parts = []
            if new_files:
                message_parts.append(f"新增 {len(new_files)} 本")
            if changed_files:
                message_parts.append(f"更新 {len(changed_files)} 本")
            if image_changed_files:
                message_parts.append(f"刷新 {len(image_changed_files)} 本配图")

            scan_progress['message'] = (
                f"扫描完成！{', '.join(message_parts)}" if message_parts
                else "扫描完成，没有变化"
            )
        else:
            scan_progress['message'] = f'全量扫描完成！共 {len(novel_data)} 本小说'

        # 持久化本次扫描统计，供首页「扫描管理」区块展示「上次扫描」信息
        try:
            duration = time.time() - start_time
            scan_stats = {
                'last_scan_time': time.time(),
                'last_scan_type': 'full' if full_scan else 'incremental',
                'last_scan_total': len(novel_data),
                'last_scan_new': len(new_files) if not full_scan else 0,
                'last_scan_updated': len(changed_files) if not full_scan else 0,
                'last_scan_images': len(image_changed_files) if not full_scan else 0,
                'last_scan_duration': round(duration, 1),
                # 本次正常结束：清掉进行中标记
                'scan_in_progress': None,
            }
            # 中断告警的清除要保守：启动后很快就会自动跑一次增量扫描，
            # 若无条件清除，用户还没打开页面告警就没了。
            # 规则：全量成功 → 清除任何告警；增量成功 → 只清除「增量被中断」的告警。
            prev = load_scan_stats()
            pending = prev.get('last_scan_interrupted') if isinstance(prev, dict) else None
            keep_warn = bool(pending) and not full_scan and pending.get('type') == 'full'
            scan_stats['last_scan_interrupted'] = pending if keep_warn else None
            # 全量扫描成功才更新，增量扫描不碰它（merge 写入会保留旧值）
            if full_scan:
                scan_stats['last_full_scan_time'] = scan_stats['last_scan_time']
            save_scan_stats(scan_stats)
        except Exception as e:
            print(f"⚠️ 保存扫描统计失败：{e}")

        scan_progress['status'] = 'completed'
        cache['filter_options'] = None
        cache['data_hash'] = None
        print(f"✅ 扫描完成，共 {len(novel_data)} 本小说")

    except Exception as e:
        scan_progress['status'] = 'error'
        scan_progress['message'] = f'扫描出错：{str(e)}'
        print(f"❌ 扫描失败：{e}")
        traceback.print_exc()
        # 扫描出错：清掉进行中标记，并留下可展示的中断原因
        try:
            save_scan_stats({
                'scan_in_progress': None,
                'last_scan_interrupted': {
                    'type': 'full' if full_scan else 'incremental',
                    'start_time': start_time,
                    'reason': f'扫描出错：{e}',
                },
            })
        except Exception:
            pass
    finally:
        # 兜底：任何未预期路径都不要留下「进行中」标记，否则下次启动会误报
        if scan_progress.get('status') != 'completed':
            try:
                save_scan_stats({'scan_in_progress': None})
            except Exception:
                pass
        elapsed = time.time() - start_time
        logger.info(
            f"扫描结束 - 处理文件: {len(files_to_scan)}, "
            f"最终小说数: {len(novel_data)}, "
            f"耗时: {elapsed:.1f}s"
        )


# ===================== 路由 =====================
@app.route('/api/scan_progress')
def get_scan_progress():
    if scan_progress['status'] == 'scanning':
        # 分阶段加权：增量的「检查书目」占 0-55%，「解析」占 55-100%；
        # 全量扫描没有检查阶段，直接 0-100%。这样 total 切换时百分比不会倒退。
        _cur = scan_progress['current']
        _tot = scan_progress['total']
        if scan_progress.get('phase') == 'scan_dir':
            percentage = int(_cur / _tot * 55) if _tot else 0
        elif scan_progress.get('incremental'):
            percentage = 55 + int(_cur / _tot * 45) if _tot else 55
        else:
            percentage = int(_cur / _tot * 100) if _tot else 0
        elapsed = time.time() - scan_progress['start_time'] if scan_progress['start_time'] else 0
        
        if scan_progress['current'] > 0:
            speed = scan_progress['current'] / elapsed if elapsed > 0 else 0
            remaining = (scan_progress['total'] - scan_progress['current']) / speed if speed > 0 else 0
        else:
            remaining = 0
        
        return jsonify({
            'status': scan_progress['status'],
            'current': scan_progress['current'],
            'total': scan_progress['total'],
            'percentage': percentage,
            'message': scan_progress['message'],
            'elapsed': int(elapsed),
            'remaining': int(remaining)
        })
    else:
        return jsonify({
            'status': scan_progress['status'],
            'message': scan_progress['message'],
            'total': scan_progress['total'],
            'current': scan_progress['current']
        })


@app.route('/api/start_scan', methods=['POST'])
def start_scan():
    full = request.args.get('full', 'false').lower() == 'true'
    if scan_progress['status'] != 'scanning':
        thread = threading.Thread(target=scan_novel_files_background, args=(full,))
        thread.daemon = True
        thread.start()
        return jsonify({'status': 'started', 'full_scan': full})
    return jsonify({'status': 'already_scanning'})


def get_filter_options_cached():
    """获取所有筛选选项（带缓存）"""
    global novel_data, cache
    
    current_hash = get_data_hash(novel_data)
    
    if cache['filter_options'] and cache['data_hash'] == current_hash:
        return cache['filter_options']
    
    if not novel_data:
        result = [], [], []
    else:
        author_count = {}
        for n in novel_data:
            if n.get('author', '未知作者') != '未知作者':
                author = n.get('author')
                author_count[author] = author_count.get(author, 0) + 1
        authors = sorted(author_count.keys(), key=lambda x: (-author_count[x], x))
        
        site_count = {}
        for n in novel_data:
            if n.get('site', '未知网站') != '未知网站':
                site = n.get('site')
                site_count[site] = site_count.get(site, 0) + 1
        sites = sorted(site_count.keys(), key=lambda x: (-site_count[x], x))
        
        tag_count = {}
        for n in novel_data:
            tags_value = n.get('tags') or ''
            if tags_value and tags_value != '无':
                for tag in tags_value.split(','):
                    if tag:
                        tag_count[tag] = tag_count.get(tag, 0) + 1
        tags = sorted(tag_count.keys(), key=lambda x: (-tag_count[x], x))
        
        result = authors, tags, sites
    
    cache['filter_options'] = result
    cache['data_hash'] = current_hash
    cache['last_update'] = time.time()
    
    return result


@app.route('/api/search/suggest')
def api_search_suggest():
    q = (request.args.get('q') or '').strip().lower()
    limit = request.args.get('limit', 10, type=int)
    limit = max(1, min(limit or 10, 50))
    if not q:
        return jsonify({'suggestions': []})

    values = []
    seen = set()
    for novel in novel_data:
        candidates = [
            novel.get('title', ''),
            novel.get('author', ''),
            novel.get('site', ''),
        ]
        tags = str(novel.get('tags') or '')
        if tags and tags != '无':
            candidates.extend(t.strip() for t in tags.split(',') if t.strip())

        for value in candidates:
            value = str(value or '').strip()
            if not value or value in seen:
                continue
            if q in value.lower():
                seen.add(value)
                values.append(value)

    values.sort(key=lambda x: (not x.lower().startswith(q), x.lower()))
    return jsonify({'suggestions': values[:limit]})


@app.route('/api/search/stats')
def api_search_stats():
    size = os.path.getsize(CACHE_FILE) if os.path.exists(CACHE_FILE) else 0
    return jsonify({
        'doc_count': len(novel_data),
        'index_dir': NOVEL_DIR,
        'index_size_mb': round(size / 1024 / 1024, 2)
    })


@app.route('/api/search/rebuild', methods=['POST'])
def api_search_rebuild():
    if scan_progress['status'] != 'scanning':
        thread = threading.Thread(target=scan_novel_files_background, args=(True,), daemon=True)
        thread.start()
    return jsonify({'success': True, 'count': len(novel_data), 'message': '已开始后台重建'})


@app.route('/open_file_ajax/<path:file_path>', methods=['POST'])
def open_file_ajax(file_path):
    try:
        import urllib.parse
        file_path = urllib.parse.unquote(file_path)
        print(f"📂 原始路径: {file_path}")
        
        filename = safe_basename(file_path)
        if os.path.isfile(file_path) and is_path_within(NOVEL_DIR, file_path):
            final_path = os.path.realpath(file_path)
        else:
            try:
                final_path = safe_join(NOVEL_DIR, filename)
            except ValueError:
                return jsonify({'success': False, 'error': '路径不合法'})

            if not os.path.exists(final_path):
                for root, dirs, files in os.walk(NOVEL_DIR):
                    if filename in files:
                        candidate = os.path.join(root, filename)
                        if is_path_within(NOVEL_DIR, candidate):
                            final_path = candidate
                        break
        print(f"📂 最终路径: {final_path}")
        
        if not os.path.exists(final_path):
            return jsonify({'success': False, 'error': f'文件不存在: {final_path}'})
        
        editor_path = CONFIG.get('editor_path', '')
        if not editor_path:
            return jsonify({'success': False, 'error': '未配置外部编辑器路径，请在设置里填写 editor_path'})
        subprocess.Popen([editor_path, final_path])
        return jsonify({'success': True, 'message': '文件已打开'})
        
    except Exception as e:
        print(f"❌ 打开文件失败: {e}")
        return jsonify({'success': False, 'error': str(e)})



def human_size(num_bytes):
    """把字节数格式化为易读字符串（B/KB/MB/GB/TB/PB）。"""
    try:
        num_bytes = float(num_bytes)
    except (TypeError, ValueError):
        return '0 B'
    if num_bytes < 1024:
        return f"{num_bytes:.0f} B"
    num_bytes /= 1024
    for unit in ('KB', 'MB', 'GB', 'TB'):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def human_words(num):
    """把字数格式化为简略字符串：不足 1 万保留千分位，1 万以上按「万字」，1 亿以上按「亿字」。

    例：8888 → "8,888"；12345 → "1.2万字"；1234567 → "123万字"；1169930000 → "11.7亿字"。
    """
    try:
        num = int(num)
    except (TypeError, ValueError):
        return '0'
    if num < 10000:
        return f"{num:,}"
    yi = round(num / 100000000, 1)
    if yi >= 1:
        text = f"{yi:.1f}"
        if text.endswith('.0'):
            text = text[:-2]
        return f"{text}亿字"
    wan = round(num / 10000, 1)
    if wan >= 100:
        return f"{int(wan)}万字"
    text = f"{wan:.1f}"
    if text.endswith('.0'):
        text = text[:-2]
    return f"{text}万字"


def get_cache_stats():
    """首页「扫描管理」区块展示的缓存概览统计。"""
    global novel_data
    total_novels = len(novel_data)
    total_words = 0
    authors = set()
    tags = set()
    sites = set()
    image_novels = 0
    video_novels = 0
    audio_novels = 0
    for n in novel_data:
        try:
            total_words += int(n.get('word_count', 0) or 0)
        except (TypeError, ValueError):
            pass
        a = n.get('author')
        if a and a != '未知作者':
            authors.add(a)
        t = n.get('tags')
        if t:
            for tag in str(t).split(','):
                tag = tag.strip()
                if tag:
                    tags.add(tag)
                    if tag == '配图':
                        image_novels += 1
                    elif tag == '视频':
                        video_novels += 1
                    elif tag == '音频':
                        audio_novels += 1
        s = n.get('site')
        if s and s != '未知网站':
            sites.add(s)

    return {
        'total_novels': total_novels,
        'total_words': total_words,
        'total_words_text': human_words(total_words),
        'image_novels': image_novels,
        'video_novels': video_novels,
        'audio_novels': audio_novels,
        'authors': len(authors),
        'tags': len(tags),
        'sites': len(sites),
    }


# 正文里的封面/配图外链：「封面：https://…」这类写法，扫描时保留在 intro / preview 里
COVER_URL_RE = re.compile(r'(?:封面图?|配图)\s*[：:]\s*(https?://\S+)')
COVER_PLACEHOLDER = '/static/images/cover-placeholder.webp'


def resolve_cover_url(novel):
    """决定「每日推荐」卡片用什么封面，没有可用封面时返回空字符串。

    优先级（书库里都没有独立封面文件，只能从这两类资源里找）：
      1. 正文里的封面外链 —— 约 85 本带这种行；外链可能失效，前端 onerror 会退回占位
      2. 配图目录 *_images 的第一张图 —— 约 671 本有，走已有的 /api/local_image 提供

    返回空字符串表示「没有封面」，此时由前端渲染占位样式：
    static/images/cover-placeholder.webp 底图 + 书名首字（与 Docker 版一致）。
    这里不再返回占位图路径 —— 否则前端就分不清哪张是真封面、哪张是兜底，
    也就没法只在真正缺封面时才叠首字。
    """
    from urllib.parse import quote

    text = (novel.get('intro') or '') + '\n' + (novel.get('preview') or '')
    match = COVER_URL_RE.search(text)
    if match:
        return match.group(1)

    folder = novel.get('image_folder') or ''
    if folder and os.path.isdir(folder):
        try:
            for name in sorted(os.listdir(folder)):
                if os.path.splitext(name)[1].lower() in IMAGE_MEDIA_EXTENSIONS:
                    return f"/api/local_image?folder={quote(folder)}&name={quote(name)}"
        except OSError:
            pass

    return ''


def pick_random_novel(exclude_work_id=None, prefer_rich=True):
    """随机挑一本书，供「每日推荐」区块使用（移植自 Docker 版）。

    prefer_rich=True 时优先从「有可用简介或预览」的书里挑，避免推荐出空卡片；
    候选为空时退回全量，保证一定能推荐出东西。
    exclude_work_id：避免「换一本」时抽到同一本。

    与 Docker 版的差异：桌面版没有封面图（无 cover_url）和作者马甲拆分
    （无 split_author_aliases），所以这里 author 用原值、不返回 aliases，
    卡片也不渲染封面。
    """
    if not novel_data:
        return None

    def _has_text(value):
        text = (value or '').strip()
        return bool(text) and text != '无简介'

    def _build(novel):
        base_info = novel
        title = base_info.get('title') or os.path.basename(str(base_info.get('file_path') or ''))
        # 简介优先；没有就用正文预览（预览是截取的正文开头，更适合「试读」）
        intro = ''
        for key in ('intro', 'preview'):
            if is_valid_intro(base_info.get(key)):
                intro = base_info[key].strip()
                break
        if not intro:
            preview = (base_info.get('preview') or '').strip()
            intro = preview if preview and preview != '无简介' else ''

        tags = [t.strip() for t in (base_info.get('tags') or '').split(',')
                if t.strip() and t.strip() != '无']

        # 有配图目录时才给「打开文件夹」按钮（与详情页 has_images 的做法一致）
        image_folder = base_info.get('image_folder') or ''
        has_images = bool(image_folder and os.path.isdir(image_folder))

        return {
            'work_id': base_info.get('work_id', ''),
            'title': title,
            'author': base_info.get('author') or '未知作者',
            'site': base_info.get('site') or '未知网站',
            'word_count': base_info.get('word_count', 0),
            'publish_date': base_info.get('publish_date') or '未知',
            'progress': base_info.get('progress') or '',
            'tags': tags,
            'intro': intro,
            'file_path': base_info.get('file_path', ''),
            # 封面：正文外链 → 配图目录首图（见 resolve_cover_url）
            'cover_url': resolve_cover_url(base_info),
            'has_images': has_images,
            'image_folder': image_folder if has_images else '',
        }

    candidates = novel_data
    if exclude_work_id:
        filtered = [n for n in novel_data if n.get('work_id') != exclude_work_id]
        # 只剩一本时就用它，否则「换一本」会没结果
        if filtered:
            candidates = filtered

    if prefer_rich:
        rich = [n for n in candidates
                if is_valid_intro(n.get('intro')) or _has_text(n.get('preview'))]
        if rich:
            candidates = rich

    return _build(random.choice(candidates))


@app.route('/api/random_novel')
def api_random_novel():
    """随机推荐一本书（供「每日推荐」区块的「换一本」使用）。

    桌面版本地单人使用、无登录鉴权，所以这里不做 is_authenticated 校验。
    """
    exclude = (request.args.get('exclude') or '').strip()
    novel = pick_random_novel(exclude_work_id=exclude or None)
    if not novel:
        return jsonify({'success': False, 'message': '书库为空，请先扫描目录'})

    novel['detail_url'] = url_for('novel_detail', file_path=(novel.get('file_path') or '').lstrip('/'))
    novel['read_url'] = url_for('read_chapter',
                                file_path=(novel.get('file_path') or '').lstrip('/'), line_number=1)
    return jsonify({'success': True, 'novel': novel})


@app.route('/', methods=['GET', 'POST'])
def index():
    global novel_data, scan_progress
    
    date_format = CONFIG.get('date_format', 'YYYY-MM-DD')
    records = load_reading_records()
    recent_records = sorted(records.values(), key=lambda x: x.get('timestamp', 0), reverse=True)[:10]

    cache_stats = get_cache_stats()
    scan_stats = load_scan_stats()
    
    authors, tags, sites = get_filter_options_cached()
    
    search_author = request.args.get('author', '').strip()
    search_tag = request.args.get('tag', '').strip()
    search_site = request.args.get('site', '').strip()
    search_text = request.args.get('search', '').strip()
    
    filtered_data = novel_data.copy()
    
    if search_text:
        search_lower = search_text.lower()
        filtered_data = [n for n in filtered_data if 
                        search_lower in str(n.get('title', '')).lower() or
                        search_lower in str(n.get('author', '')).lower() or
                        search_lower in str(n.get('tags', '')).lower() or
                        search_lower in str(n.get('site', '')).lower()]
    
    if search_author:
        filtered_data = [n for n in filtered_data if n.get('author', '未知作者') == search_author]
    
    if search_tag:
        filtered_data = [n for n in filtered_data if search_tag in str(n.get('tags', '')).split(',')]
    
    if search_site:
        filtered_data = [n for n in filtered_data if n.get('site', '未知网站') == search_site]
    
    sort_by = request.args.get('sort')
    sort_order = request.args.get('order')
    
    if not sort_by:
        sort_by = CONFIG.get('default_sort_by', 'title')
    if not sort_order:
        sort_order = CONFIG.get('default_sort_order', 'asc')
    
    def get_sort_key(novel):
        if sort_by == 'author':
            key = novel.get('author', '未知作者')
        elif sort_by == 'site':
            key = novel.get('site', '未知网站')
        elif sort_by == 'date':
            publish_date = novel.get('publish_date', '')
            if publish_date and publish_date != '未知':
                key = publish_date
            else:
                key = novel.get('filename', '')
        elif sort_by == 'word_count':
            key = novel.get('word_count', 0)
        else:
            key = novel.get('title', '')
        
        if key is None:
            key = ''
        
        if sort_by == 'word_count':
            return key
        
        if isinstance(key, str):
            return key.lower()
        return key
    
    reverse_order = (sort_order == 'desc')
    filtered_data.sort(key=get_sort_key, reverse=reverse_order)
    
    page = request.args.get('page', 1, type=int)
    per_page = PER_PAGE
    
    total = len(filtered_data)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_data = [n.copy() for n in filtered_data[start:end]]
    
    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': (total + per_page - 1) // per_page
    }
    
    for novel in paginated_data:
        # 🔥 标记文件状态
        fp = novel.get('file_path', '')
        if fp and os.path.exists(fp):
            try:
                cached_mtime = float(novel.get('mtime', 0))
                real_mtime = os.path.getmtime(fp)
                if cached_mtime and abs(cached_mtime - real_mtime) > 1:
                    novel['stale'] = True
            except (OSError, TypeError, ValueError):
                novel['missing'] = True
        else:
            novel['missing'] = True
        
        if novel.get('publish_date') and novel['publish_date'] != '未知':
            publish_date = novel['publish_date']
            match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', publish_date)
            if match:
                year, month, day = match.groups()
                month = month.zfill(2)
                day = day.zfill(2)
                
                if date_format == 'YYYY-MM-DD':
                    novel['publish_date'] = f"{year}-{month}-{day}"
                elif date_format == 'YYYY/MM/DD':
                    novel['publish_date'] = f"{year}/{month}/{day}"
                elif date_format == 'YYYY年MM月DD日':
                    novel['publish_date'] = f"{year}年{month}月{day}日"
    
    return render_template('index.html',
        novels=paginated_data,
        authors=authors,
        tags=tags,
        sites=sites,
        recent_records=recent_records, 
        total_count=len(novel_data),
        filtered_count=total,
        pagination=pagination, 
        search_author=search_author,
        search_tag=search_tag,
        search_site=search_site,
        search_text=search_text,
        novel_dir=NOVEL_DIR,
        sort_by=sort_by,
        sort_order=sort_order,
        cache_stats=cache_stats,
        scan_stats=scan_stats,
        # 每次刷新页面随机推荐一本；「换一本」按钮再走 /api/random_novel
        random_novel=pick_random_novel()
    )


@app.route('/novel_detail/<path:file_path>')
def novel_detail(file_path):
    import urllib.parse
    
    file_path = urllib.parse.unquote(file_path)
    print(f"📂 原始路径：{file_path}")
    
    filename = safe_basename(file_path)

    if os.path.exists(file_path) and is_path_within(NOVEL_DIR, file_path):
        actual_path = os.path.realpath(file_path)
    else:
        try:
            actual_path = safe_join(NOVEL_DIR, filename)
        except ValueError:
            return render_missing_page(file_path, 'error')

        if not os.path.exists(actual_path):
            for root, dirs, files in os.walk(NOVEL_DIR):
                if filename in files:
                    candidate = os.path.join(root, filename)
                    if is_path_within(NOVEL_DIR, candidate):
                        actual_path = candidate
                    break
    print(f"📂 实际路径：{actual_path}")
    
    # ===== 🔥 文件有效性校验 =====
    if not os.path.exists(actual_path):
        logger.warning(f"详情页：文件不存在 {actual_path}")
        return render_missing_page(actual_path, 'deleted')
    
    if not os.path.isfile(actual_path):
        logger.warning(f"详情页：路径不是文件 {actual_path}")
        return render_missing_page(actual_path, 'deleted')
    
    if not is_file_readable(actual_path):
        logger.warning(f"详情页：文件不可读 {actual_path}")
        return render_missing_page(actual_path, 'error')
    
    # 对比 mtime，判断缓存是否过期
    cached_novel = next(
        (n for n in novel_data
         if os.path.basename(n.get('file_path', '')) == filename),
        None
    )
    if cached_novel:
        try:
            cached_mtime = float(cached_novel.get('mtime', 0))
            current_mtime = os.path.getmtime(actual_path)
            if cached_mtime and abs(cached_mtime - current_mtime) > 1:
                logger.warning(
                    f"详情页：文件已更新但缓存未同步 {filename} "
                    f"(缓存mtime={cached_mtime}, 实际mtime={current_mtime})"
                )
                return render_missing_page(actual_path, 'modified')
        except (OSError, TypeError, ValueError):
            return render_missing_page(actual_path, 'error')
    
    # 检测配图文件夹
    has_images = False
    image_folder = get_image_folder_for_novel(filename)
    if image_folder and os.path.exists(image_folder):
        # 检查是否有图片文件
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
        try:
            for f in os.listdir(image_folder):
                ext = os.path.splitext(f)[1].lower()
                if ext in image_extensions:
                    has_images = True
                    break
        except:
            has_images = False
    
    if os.path.exists(actual_path):
        current_hash = get_file_hash(actual_path)
        
        if actual_path in chapter_cache:
            cached_info = chapter_cache[actual_path]
            cached_hash = cached_info.get('file_hash', '') if isinstance(cached_info, dict) else ''
            if cached_hash != current_hash:
                print(f"🗑️ 清除过期章节缓存")
                del chapter_cache[actual_path]
        
        if actual_path in tag_parse_cache:
            cached_hash, _ = tag_parse_cache[actual_path]
            if cached_hash != current_hash:
                print(f"🗑️ 清除过期标签缓存")
                del tag_parse_cache[actual_path]
    
    detail_info = parse_novel_details(actual_path)
    base_info = parse_file_content_fast(actual_path)
    
    # ===== 简介 / 预览：多级兜底，确保不会因为某条缓存坏了就显示"无简介" =====
    final_intro = '无简介'

    # 1) 优先用章节解析里的简介（已校验有效）
    detail_intro = detail_info.get('intro') or ''
    if detail_intro and detail_intro != '无简介' and is_valid_intro(detail_intro):
        final_intro = detail_intro

    # 2) 退回快速解析里的简介
    if final_intro == '无简介':
        base_intro = base_info.get('intro') or ''
        if base_intro and base_intro != '无简介' and is_valid_intro(base_intro):
            final_intro = base_intro

    # 3) 都无效 → 直接从文件重新提取（依赖文件真实编码，避免乱码）
    fallback_lines = None

    def _read_fallback_lines():
        """按真实编码读取文件头，供简介/预览兜底共用（只读一次）

        ⚠️ 必须用文件真实路径 actual_path：file_path 是 URL 里的那串
        （可能是相对名，且在 /read 路由里已被 unquote 过），直接 open
        会落到进程 CWD 上，抛异常后简介兜底静默失效。
        """
        nonlocal fallback_lines
        if fallback_lines is None:
            with open(actual_path, 'r', encoding=detect_encoding(actual_path),
                      errors='ignore') as f:
                fallback_lines = re.split(r'\r?\n|\r', f.read(65536))
        return fallback_lines

    if final_intro == '无简介':
        try:
            final_intro = extract_intro_clean(_read_fallback_lines())
            if final_intro != '无简介':
                # 回写缓存，避免每次打开都重算
                if actual_path in chapter_cache and isinstance(chapter_cache[actual_path], dict):
                    chapter_cache[actual_path]['intro'] = final_intro
                if actual_path in tag_parse_cache:
                    _, cached_result = tag_parse_cache[actual_path]
                    if isinstance(cached_result, dict):
                        cached_result['intro'] = final_intro
                print(f"♻️ 兜底重新提取简介: {final_intro[:50]}")
        except Exception as e:
            logger.error(f"重新提取简介失败: {e}")

    if final_intro != '无简介' and not is_valid_intro(final_intro):
        # 校验不过说明是误截内容，当作没有简介，交给预览显示
        print(f"⚠️ 简介校验不通过，改用正文预览: {final_intro[:30]}")
        final_intro = '无简介'

    # 详情页与快速解析共享同一份简介，避免两个页面显示不一致
    base_info['intro'] = final_intro
    detail_info['intro'] = final_intro

    final_preview = None
    if final_intro == '无简介':
        if detail_info.get('preview'):
            final_preview = detail_info['preview']
        elif base_info.get('preview'):
            final_preview = base_info['preview']
        else:
            # 兜底：直接从文件重新提取正文开头
            try:
                final_preview = extract_preview_clean(_read_fallback_lines())
            except Exception as e:
                logger.error(f"提取预览失败: {e}")
    
    link = base_info.get('link', '')
    if link and not link.startswith(('http://', 'https://')):
        link = 'https://' + link
        print(f"🔗 链接已修复: {link}")
    
    date_format = CONFIG.get('date_format', 'YYYY-MM-DD')
    publish_date = base_info.get('publish_date', '未知')
    
    if publish_date != '未知':
        match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', publish_date)
        if match:
            year, month, day = match.groups()
            month = month.zfill(2)
            day = day.zfill(2)
            if date_format == 'YYYY-MM-DD':
                publish_date = f"{year}-{month}-{day}"
            elif date_format == 'YYYY/MM/DD':
                publish_date = f"{year}/{month}/{day}"
            elif date_format == 'YYYY年MM月DD日':
                publish_date = f"{year}年{month}月{day}日"
    
    back_page = request.args.get('page', 1, type=int)
    search_text = request.args.get('search', '')
    search_author = request.args.get('author', '')
    search_tag = request.args.get('tag', '')
    search_site = request.args.get('site', '')
    
    url_file_path = urllib.parse.quote(filename)

    # 相似书籍：扩展阅读用，无结果时模板整块不渲染
    similar_novels = build_similar_urls(
        find_similar_novels(
            base_info['title'], base_info['author'], base_info['tags'],
            exclude_path=actual_path
        ),
        page=back_page, search=search_text, author=search_author,
        tag=search_tag, site=search_site
    )

    return render_template('novel_detail.html',
        title=base_info['title'],
        author=base_info['author'],
        site=base_info['site'],
        word_count=base_info['word_count'],
        publish_date=publish_date,
        file_path=url_file_path,
        link=link,
        intro=final_intro,          # 🔥 改用 final_intro
        preview=final_preview,      # 🔥 新增
        all_chapters=detail_info['all_chapters'],
        chapters_level1=detail_info['chapters_level1'],
        chapters_level2=detail_info['chapters_level2'],
        chapters_level3=detail_info['chapters_level3'],
        tags=base_info['tags'],
        back_page=back_page,
        search_text=search_text,
        search_author=search_author,
        search_tag=search_tag,
        search_site=search_site,
        has_images=has_images,
        similar_novels=similar_novels
    )


@app.route('/read/<path:file_path>/<int:line_number>')
def read_chapter(file_path, line_number):
    import urllib.parse

    file_path = urllib.parse.unquote(file_path)
    filename = os.path.basename(file_path)
    full_path = os.path.join(NOVEL_DIR, filename)

    # ===== 🔥 文件有效性校验 =====
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        logger.warning(f"阅读页：文件不存在 {full_path}")
        return render_missing_page(full_path, 'deleted')

    file_path = full_path
    print(f"✅ 阅读文件: {file_path}")

    if not is_file_readable(file_path):
        logger.warning(f"阅读页：文件不可读 {file_path}")
        return render_missing_page(file_path, 'error')

    back_page = request.args.get('list_page', 1, type=int)
    search_text = request.args.get('search', '')
    search_author = request.args.get('author', '')
    search_tag = request.args.get('tag', '')
    search_site = request.args.get('site', '')

    file_size = os.path.getsize(file_path)
    try:
        max_read_bytes = int(CONFIG.get('max_file_size_mb', 100) or 100) * 1024 * 1024
    except (TypeError, ValueError):
        max_read_bytes = 100 * 1024 * 1024
    if max_read_bytes and file_size > max_read_bytes:
        return "文件过大，无法在线阅读"

    try:
        page = request.args.get('page', 1, type=int) or 1
        current_file_hash = get_file_hash(file_path)

        cache_cleared = False
        cached_info = chapter_cache.get(file_path)
        if cached_info is not None:
            cached_hash = cached_info.get('file_hash', '') if isinstance(cached_info, dict) else ''
            cached_intro = cached_info.get('intro', '') if isinstance(cached_info, dict) else ''
            if cached_hash != current_file_hash:
                print(f"🔄 检测到文件被修改，清除章节缓存: {os.path.basename(file_path)}")
                chapter_cache.pop(file_path, None)
                cache_cleared = True
            elif cached_intro and cached_intro != '无简介' and not is_valid_intro(cached_intro):
                # 旧版本写进去的坏简介：文件没变，但缓存内容是错的
                print(f"🗑️ 清除损坏的章节缓存（简介无效）: {os.path.basename(file_path)}")
                chapter_cache.pop(file_path, None)

        if file_path in tag_parse_cache:
            cached_hash, cached_result = tag_parse_cache[file_path]
            cached_intro = cached_result.get('intro', '') if isinstance(cached_result, dict) else ''
            if cached_hash != current_file_hash:
                del tag_parse_cache[file_path]
            elif cached_intro and cached_intro != '无简介' and not is_valid_intro(cached_intro):
                print(f"🗑️ 清除损坏的标签缓存（简介无效）: {os.path.basename(file_path)}")
                del tag_parse_cache[file_path]

        if cache_cleared:
            records = load_reading_records()
            file_key = file_path.replace('\\', '/')
            old_chapter_text = records.get(file_key, {}).get('chapter_text', '')
            if old_chapter_text:
                found = False
                read_encoding = detect_encoding(file_path)
                try:
                    with open(file_path, 'r', encoding=read_encoding, errors='ignore') as f:
                        for i, line in enumerate(f):
                            if line.strip() == old_chapter_text.strip():
                                line_number = i + 1
                                found = True
                                print(f"✅ 智能恢复章节: '{old_chapter_text[:30]}...' -> 行{line_number}")
                                break
                            if i > 50000:
                                break
                    if not found:
                        print("⚠️ 未找到原章节，从第1行开始")
                        line_number = 1
                except Exception as e:
                    print(f"⚠️ 智能恢复章节失败：{e}")
                    line_number = 1

        detail_info = parse_novel_details(file_path)
        encoding = detail_info.get('encoding') or detect_encoding(file_path)
        line_index = get_line_index(file_path, encoding)
        total_lines = detail_info.get('line_count') or line_index.get('line_count') or 1

        all_chapters = detail_info.get('all_chapters') or []
        if not all_chapters:
            all_chapters = [{'text': '全文阅读', 'line_number': 1, 'level': 1}]
            detail_info['all_chapters'] = all_chapters

        is_virtual_chapter = (len(all_chapters) == 1 and
                              all_chapters[0].get('text') == '全文阅读')

        current_chapter = None
        prev_chapter = None
        next_chapter = None
        chapter_index = -1

        if is_virtual_chapter:
            current_chapter = all_chapters[0]
            chapter_index = 0
            line_number = max(1, min(int(current_chapter.get('line_number', 1)), total_lines))
            current_chapter['line_number'] = line_number
            print(f"📖 虚拟章节模式: line_number 修正为 {line_number}")
        else:
            for i, chapter in enumerate(all_chapters):
                if int(chapter.get('line_number', 1)) <= line_number:
                    current_chapter = chapter
                    chapter_index = i
                else:
                    break

            # 兜底：line_number 落在第一个章节标题之前（例如进入时 line_number=1
            # 而文件开头是书名/作者/简介，首章标题在第 N 行）。上面的循环一次都没命中，
            # 必须显式回退到第一章——注意不能在这里 return，后面还要据此算 prev/next。
            if current_chapter is None and all_chapters:
                current_chapter = all_chapters[0]
                chapter_index = 0
                print("⚠️ 未找到匹配章节，使用第一个章节")

            if current_chapter:
                # 上一章/下一章跳过空章节（只有标题没有正文），
                # 避免阅读页的 ◀ ▶ 按钮把用户带到空白页。
                # 找不到非空章节时退回相邻章节，保证按钮不会凭空消失。
                if chapter_index > 0:
                    prev_chapter = next(
                        (c for c in reversed(all_chapters[:chapter_index])
                         if not c.get('is_empty')),
                        all_chapters[chapter_index - 1]
                    )
                if chapter_index < len(all_chapters) - 1:
                    next_chapter = next(
                        (c for c in all_chapters[chapter_index + 1:]
                         if not c.get('is_empty')),
                        all_chapters[chapter_index + 1]
                    )
                line_number = current_chapter['line_number']

        if current_chapter:
            chapter_start_line = max(1, int(current_chapter.get('line_number', 1)))
            chapter_end_line = total_lines
            for chapter in all_chapters:
                next_line = int(chapter.get('line_number', total_lines + 1))
                if next_line > chapter_start_line:
                    chapter_end_line = next_line - 1
                    break

            if is_virtual_chapter:
                # 无章节结构时按行分页，避免把整本小说读进内存。
                lines_per_page = CONFIG.get('virtual_lines_per_page')
                if not lines_per_page:
                    # 没有显式配置时，按每行约 30 字估算，尽量接近 words_per_page 的阅读量
                    lines_per_page = int(WORDS_PER_PAGE / 30) if WORDS_PER_PAGE else 300
                lines_per_page = max(50, min(2000, int(lines_per_page)))
                start_offset = chapter_start_line - 1
                virtual_total = max(1, total_lines - start_offset)
                total_pages = max(1, (virtual_total + lines_per_page - 1) // lines_per_page)
                page = max(1, min(page, total_pages))

                start_line = start_offset + (page - 1) * lines_per_page + 1
                end_line = min(start_offset + page * lines_per_page, total_lines)
                raw_lines = read_line_range(file_path, start_line, end_line, index=line_index)
                current_lines = [line.lstrip(' \t\u3000') if line.strip() else '' for line in raw_lines]
                prev_page = page - 1 if page > 1 else None
                next_page = page + 1 if page < total_pages else None
            else:
                chapter_lines = read_line_range(file_path, chapter_start_line, chapter_end_line, index=line_index)
                processed_lines = [line.lstrip(' \t\u3000') if line.strip() else '' for line in chapter_lines]

                total_words = sum(len(line) for line in chapter_lines)
                if total_words > WORDS_PER_PAGE:
                    prefix = [0]
                    for line in chapter_lines:
                        prefix.append(prefix[-1] + len(line))

                    boundaries = [0]
                    start_idx = 0
                    n = len(chapter_lines)
                    while start_idx < n:
                        target = prefix[start_idx] + WORDS_PER_PAGE
                        end_idx = bisect_left(prefix, target, lo=start_idx + 1)
                        if end_idx > n:
                            end_idx = n
                        if end_idx <= start_idx:
                            end_idx = min(start_idx + 1, n)
                        boundaries.append(end_idx)
                        start_idx = end_idx

                    total_pages = max(1, len(boundaries) - 1)
                    page = max(1, min(page, total_pages))
                    start_idx = boundaries[page - 1]
                    end_idx = boundaries[page]

                    current_lines = processed_lines[start_idx:end_idx]
                    start_line = chapter_start_line + start_idx
                    end_line = chapter_start_line + end_idx - 1
                    prev_page = page - 1 if page > 1 else None
                    next_page = page + 1 if page < total_pages else None
                else:
                    current_lines = processed_lines
                    start_line = chapter_start_line
                    end_line = chapter_end_line
                    total_pages = 1
                    prev_page = None
                    next_page = None
        else:
            # 兜底：当前无匹配章节（如全书无有效章节结构的纯文本小说）。
            # 复用「全文阅读」虚拟章节的估算方式，按 words_per_page 近似换算行数，
            # 不再写死 300 行，使配置页的「每页显示字数」对它同样生效。
            lines_per_page = CONFIG.get('virtual_lines_per_page')
            if not lines_per_page:
                # 没有显式配置时，按每行约 30 字估算，尽量接近 words_per_page 的阅读量
                lines_per_page = int(WORDS_PER_PAGE / 30) if WORDS_PER_PAGE else 300
            lines_per_page = max(50, min(2000, int(lines_per_page)))
            total_pages = max(1, (total_lines + lines_per_page - 1) // lines_per_page)
            page = max(1, min(page, total_pages))
            start_idx = (page - 1) * lines_per_page
            end_idx = min(start_idx + lines_per_page, total_lines)
            raw_lines = read_line_range(file_path, start_idx + 1, end_idx, index=line_index)
            current_lines = [line.lstrip(' \t\u3000') if line.strip() else '' for line in raw_lines]
            start_line = start_idx + 1
            end_line = end_idx
            prev_page = page - 1 if page > 1 else None
            next_page = page + 1 if page < total_pages else None

        if current_lines:
            full_text = '\n'.join(current_lines)
            processed_text = highlight_crossline_brackets(full_text)
            current_lines = processed_text.split('\n')

        if file_path in tag_parse_cache:
            cached_hash, base_info = tag_parse_cache[file_path]
        else:
            base_info = parse_file_content_fast(file_path)

        chapter_text = '全文阅读' if is_virtual_chapter else (current_chapter['text'] if current_chapter else '正文')

        if CONFIG.get('auto_save_progress', True):
            records = load_reading_records()
            file_key = file_path.replace('\\', '/')
            records[file_key] = {
                'title': base_info['title'],
                'author': base_info['author'],
                'line_number': line_number,
                'chapter_text': chapter_text,
                'timestamp': time.time(),
                'file_path': file_path,
                'page': page,
                'total_pages': total_pages,
                'is_virtual': is_virtual_chapter
            }
            save_success = save_reading_records(records)
        else:
            save_success = True

        # ===== 预取下一章（后台线程，不阻塞本次响应）=====
        # 多数情况下用户会继续往下读，提前把下一章读进行缓存，翻章时不必再等磁盘。
        if next_chapter and not is_virtual_chapter:
            def _prefetch_next():
                try:
                    n_start = max(1, int(next_chapter.get('line_number', 1)))
                    n_end = total_lines
                    for ch in all_chapters:
                        nl = int(ch.get('line_number', total_lines + 1))
                        if nl > n_start:
                            n_end = nl - 1
                            break
                    read_line_range(file_path, n_start, n_end, index=line_index)
                except Exception:
                    pass

            threading.Thread(target=_prefetch_next, daemon=True).start()

    except Exception as e:
        print(f"❌ 读取文件失败：{str(e)}")
        traceback.print_exc()
        return f"读取文件失败：{str(e)}"

    filename_for_template = os.path.basename(file_path)

    # 相似书籍：只在全书最后一页出现（没有下一章也没有下一页）
    try:
        at_the_end = (next_chapter is None and next_page is None)
    except NameError:
        at_the_end = False
    similar_novels = []
    if at_the_end:
        similar_novels = build_similar_urls(
            find_similar_novels(
                base_info['title'], base_info['author'], base_info['tags'],
                exclude_path=file_path
            ),
            page=back_page, search=search_text, author=search_author,
            tag=search_tag, site=search_site
        )

    return render_template('read_chapter.html',
        title=base_info['title'],
        author=base_info['author'],
        file_path=filename_for_template,
        content_lines=current_lines,
        start_line=start_line,
        end_line=end_line,
        total_lines=total_lines,
        all_chapters=all_chapters,
        current_chapter=current_chapter,
        prev_chapter=prev_chapter,
        next_chapter=next_chapter,
        page=page,
        total_pages=total_pages,
        prev_page=prev_page,
        next_page=next_page,
        file_size=file_size,
        save_success=save_success,
        user_prefs={
            'font_size': CONFIG.get('font_size', 24),
            'font_family': 'system-ui',
            'line_height': CONFIG.get('line_height', 1.8),
            # 分元素字体（自定义高亮标点符号字体）：从全局配置读取，空 = 跟随正文
            'body_font_family': CONFIG.get('body_font_family', ''),
            'title_font_family': CONFIG.get('title_font_family', ''),
            'double_quote_font_family': CONFIG.get('double_quote_font_family', ''),
            'single_quote_font_family': CONFIG.get('single_quote_font_family', ''),
            'bracket_font_family': CONFIG.get('bracket_font_family', ''),
            'square_bracket_font_family': CONFIG.get('square_bracket_font_family', ''),
            'square_bracket_1_font_family': CONFIG.get('square_bracket_1_font_family', ''),
            'hollow_bracket_font_family': CONFIG.get('hollow_bracket_font_family', ''),
            'book_font_family': CONFIG.get('book_font_family', ''),
            # 分元素 加粗/斜体（默认对齐桌面 reader.css 现状，仅「偏离默认」才注入覆盖）
            'body_bold': CONFIG.get('body_bold', False),
            'body_italic': CONFIG.get('body_italic', False),
            'title_bold': CONFIG.get('title_bold', False),
            'title_italic': CONFIG.get('title_italic', False),
            'double_quote_bold': CONFIG.get('double_quote_bold', False),
            'double_quote_italic': CONFIG.get('double_quote_italic', False),
            'single_quote_bold': CONFIG.get('single_quote_bold', False),
            'single_quote_italic': CONFIG.get('single_quote_italic', False),
            'bracket_bold': CONFIG.get('bracket_bold', False),
            'bracket_italic': CONFIG.get('bracket_italic', False),
            'square_bracket_bold': CONFIG.get('square_bracket_bold', False),
            'square_bracket_italic': CONFIG.get('square_bracket_italic', False),
            'square_bracket_1_bold': CONFIG.get('square_bracket_1_bold', False),
            'square_bracket_1_italic': CONFIG.get('square_bracket_1_italic', False),
            'hollow_bracket_bold': CONFIG.get('hollow_bracket_bold', False),
            'hollow_bracket_italic': CONFIG.get('hollow_bracket_italic', False),
            'book_bold': CONFIG.get('book_bold', False),
            'book_italic': CONFIG.get('book_italic', False),
            'indent_paragraph': CONFIG.get('indent_paragraph', True),
        },
        current_page_words=sum(len(line) for line in current_lines),
        back_page=back_page,
        search_text=search_text,
        search_author=search_author,
        search_tag=search_tag,
        search_site=search_site,
        is_virtual_chapter=is_virtual_chapter,
        similar_novels=similar_novels
    )


@app.route('/continue/<path:file_path>')
def continue_reading(file_path):
    import urllib.parse
    
    file_path = urllib.parse.unquote(file_path)
    print(f"🔍 继续阅读 - 原始路径: {file_path}")
    
    filename = os.path.basename(file_path)
    full_path = os.path.join(NOVEL_DIR, filename)
    
    records = load_reading_records()
    file_key = full_path.replace('\\', '/')
    
    if file_key in records:
        record = records[file_key]
        
        if record.get('is_virtual', False):
            if os.path.exists(full_path):
                detail_info = parse_novel_details(full_path)
                if detail_info['all_chapters']:
                    record['line_number'] = detail_info['all_chapters'][0]['line_number']
                    print(f"🔧 修复虚拟章节起始行: {record['line_number']}")
        
        url = url_for('read_chapter', 
                     file_path=filename,
                     line_number=record['line_number'])
        
        if 'page' in record and record['page'] > 1:
            url += f"?page={record['page']}"
            
        return redirect(url)
    else:
        return redirect(url_for('read_chapter', 
                               file_path=filename,
                               line_number=1))


@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    dt = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    if dt.date() == now.date():
        return f"今天 {dt.strftime('%H:%M')}"
    elif (now - dt).days == 1:
        return f"昨天 {dt.strftime('%H:%M')}"
    else:
        return dt.strftime('%m-%d %H:%M')


@app.template_filter('truncate_tags')
def truncate_tags(tags_str, max_tags=3):
    if not tags_str or tags_str == '无':
        return '无'
    
    tags_list = tags_str.split(',')
    if len(tags_list) <= max_tags:
        return tags_str
    else:
        displayed_tags = ','.join(tags_list[:max_tags])
        return f"{displayed_tags}…"


_css_version_cache = {'value': 0, 'ts': 0}


def get_css_version():
    """取 static/css 下所有样式的最新 mtime 作为 ?v=，改样式后浏览器不会拿旧缓存。"""
    now = time.time()
    if _css_version_cache['value'] and now - _css_version_cache['ts'] < 300:
        return _css_version_cache['value']
    latest = 0
    try:
        for entry in os.scandir(os.path.join(BASE_DIR, 'static', 'css')):
            if entry.name.endswith('.css') and entry.is_file():
                latest = max(latest, int(entry.stat().st_mtime))
    except OSError:
        pass
    _css_version_cache['value'] = latest
    _css_version_cache['ts'] = now
    return latest


@app.context_processor
def inject_globals():
    # 让所有模板都能读到「最大标签显示数」配置，主页列表据此限制标签数量
    return {
        'max_tags_display': CONFIG.get('max_tags_display', 3),
        'css_version': get_css_version(),
    }


@app.route('/clear_records', methods=['POST'])
def clear_records():
    try:
        if os.path.exists(READING_RECORD_FILE):
            os.remove(READING_RECORD_FILE)
        logger.info("阅读记录已清空")
        return jsonify({'success': True, 'message': '阅读记录已清空'})
    except Exception as e:
        print(f"❌ 清除记录失败：{e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/get_all_authors')
def get_all_authors():
    authors, _, _ = get_filter_options_cached()
    return jsonify({'authors': authors})


@app.route('/get_all_tags')
def get_all_tags():
    _, tags, _ = get_filter_options_cached()
    return jsonify({'tags': tags})


@app.route('/get_all_sites')
def get_all_sites():
    _, _, sites = get_filter_options_cached()
    return jsonify({'sites': sites})


@app.route('/get_first_authors')
def get_first_authors():
    authors, _, _ = get_filter_options_cached()
    return jsonify({'authors': authors[:100], 'total': len(authors)})


@app.route('/get_first_tags')
def get_first_tags():
    _, tags, _ = get_filter_options_cached()
    return jsonify({'tags': tags[:50], 'total': len(tags)})


@app.route('/get_first_sites')
def get_first_sites():
    _, _, sites = get_filter_options_cached()
    return jsonify({'sites': sites[:20], 'total': len(sites)})


@app.route('/clear_chapter_cache', methods=['POST'])
def clear_chapter_cache():
    global chapter_cache
    count = len(chapter_cache)
    chapter_cache.clear()
    save_cache()
    return jsonify({'success': True, 'status': 'success', 'cleared': count, 'message': f'已清除 {count} 个章节缓存'})


@app.route('/api/delete_record', methods=['POST'])
def delete_reading_record():
    data = request.get_json()
    file_path = data.get('file_path', '')
    
    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不能为空'})
    
    records = load_reading_records()
    file_key = file_path.replace('\\', '/')
    
    if file_key in records:
        del records[file_key]
        save_reading_records(records)
        print(f"🗑️ 用户删除了阅读记录: {file_path}")
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': '记录不存在'})


# ==================== 标签管理 API ====================
@app.route('/api/tag/stats')
def api_tag_stats():
    tag_count = {}
    for novel in novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            for tag in novel['tags'].split(','):
                tag = tag.strip()
                if tag:
                    tag_count[tag] = tag_count.get(tag, 0) + 1
    
    custom_tags = CONFIG.get('custom_tags', [])
    derived_rules = TAG_IMPLICATIONS
    
    return jsonify({
        'total_tags': len(tag_count),
        'used_tags': len([t for t in tag_count if tag_count[t] > 0]),
        'custom_tags': len(custom_tags),
        'derived_rules': len(derived_rules)
    })


@app.route('/api/tag/list')
def api_tag_list():
    tag_count = {}
    for novel in novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            for tag in novel['tags'].split(','):
                tag = tag.strip()
                if tag:
                    tag_count[tag] = tag_count.get(tag, 0) + 1
    
    tags = [{'name': k, 'count': v} for k, v in sorted(tag_count.items(), key=lambda x: -x[1])]
    return jsonify(tags)


@app.route('/api/tag/derived-rules')
def api_tag_derived_rules():
    rules = []
    for source, derived_list in TAG_IMPLICATIONS.items():
        for derived in derived_list:
            rules.append({'source': source, 'derived': derived})
    return jsonify(rules)


@app.route('/api/tag/add', methods=['POST'])
def api_tag_add():
    data = request.get_json()
    tag = data.get('tag', '').strip()
    
    if not tag:
        return jsonify({'success': False, 'message': '标签名称不能为空'})
    
    if len(tag) > 20:
        return jsonify({'success': False, 'message': '标签名称不能超过20个字符'})
    
    custom_tags = CONFIG.get('custom_tags', [])
    if tag not in custom_tags:
        custom_tags.append(tag)
        CONFIG['custom_tags'] = custom_tags
        save_json_file(CONFIG_FILE, CONFIG)
    
    return jsonify({'success': True})


@app.route('/api/tag/edit', methods=['POST'])
def api_tag_edit():
    data = request.get_json()
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()
    
    if not old_name or not new_name:
        return jsonify({'success': False, 'message': '标签名称不能为空'})
    
    count = 0
    for novel in novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            tags = novel['tags'].split(',')
            if old_name in tags:
                tags = [new_name if t == old_name else t for t in tags]
                novel['tags'] = ','.join(tags)
                count += 1
    
    custom_tags = CONFIG.get('custom_tags', [])
    if old_name in custom_tags:
        custom_tags.remove(old_name)
        if new_name not in custom_tags:
            custom_tags.append(new_name)
        CONFIG['custom_tags'] = custom_tags
    
    save_cache()
    invalidate_filter_cache()
    save_json_file(CONFIG_FILE, CONFIG)
    
    return jsonify({'success': True, 'count': count})


@app.route('/api/tag/delete', methods=['POST'])
def api_tag_delete():
    data = request.get_json()
    tag = data.get('tag', '').strip()
    
    if not tag:
        return jsonify({'success': False, 'message': '标签名称不能为空'})
    
    count = 0
    for novel in novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            tags = [t for t in novel['tags'].split(',') if t != tag]
            if len(tags) != len(novel['tags'].split(',')):
                novel['tags'] = ','.join(tags) if tags else '无'
                count += 1
    
    custom_tags = CONFIG.get('custom_tags', [])
    if tag in custom_tags:
        custom_tags.remove(tag)
        CONFIG['custom_tags'] = custom_tags
    
    save_cache()
    invalidate_filter_cache()
    save_json_file(CONFIG_FILE, CONFIG)
    
    return jsonify({'success': True, 'count': count})


@app.route('/api/tag/add-derived-rule', methods=['POST'])
def api_tag_add_derived_rule():
    data = request.get_json(silent=True) or {}
    source = str(data.get('source', '')).strip()
    derived = str(data.get('derived', '')).strip()

    if not source or not derived:
        return jsonify({'success': False, 'message': '请填写源标签和派生标签'})

    if source == derived:
        return jsonify({'success': False, 'message': '源标签和派生标签不能相同'})

    TAG_IMPLICATIONS.setdefault(source, [])
    if derived not in TAG_IMPLICATIONS[source]:
        TAG_IMPLICATIONS[source].append(derived)

    save_tag_rules_file()
    CONFIG['tag_implications'] = TAG_IMPLICATIONS
    save_json_file(CONFIG_FILE, CONFIG)
    return jsonify({'success': True})


@app.route('/api/tag/delete-derived-rule', methods=['POST'])
def api_tag_delete_derived_rule():
    data = request.get_json(silent=True) or {}
    try:
        index = int(data.get('index'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '索引无效'})

    rules = []
    for source, derived_list in TAG_IMPLICATIONS.items():
        for derived in derived_list:
            rules.append({'source': source, 'derived': derived})

    if not (0 <= index < len(rules)):
        return jsonify({'success': False, 'message': '规则不存在'})

    rule = rules[index]
    source = rule['source']
    derived = rule['derived']

    if source in TAG_IMPLICATIONS and derived in TAG_IMPLICATIONS[source]:
        TAG_IMPLICATIONS[source].remove(derived)
        if not TAG_IMPLICATIONS[source]:
            del TAG_IMPLICATIONS[source]

    save_tag_rules_file()
    CONFIG['tag_implications'] = TAG_IMPLICATIONS
    save_json_file(CONFIG_FILE, CONFIG)
    return jsonify({'success': True})


@app.route('/api/tag/export')
def api_tag_export():
    return jsonify({
        'custom_tags': CONFIG.get('custom_tags', []),
        'tag_implications': TAG_IMPLICATIONS
    })


@app.route('/api/tag/import', methods=['POST'])
def api_tag_import():
    data = request.get_json(silent=True) or {}
    global TAG_IMPLICATIONS

    if 'custom_tags' in data:
        CONFIG['custom_tags'] = data['custom_tags']

    if 'tag_implications' in data:
        TAG_IMPLICATIONS = data['tag_implications']
        CONFIG['tag_implications'] = TAG_IMPLICATIONS

    save_tag_rules_file()
    save_json_file(CONFIG_FILE, CONFIG)
    return jsonify({'success': True})


@app.route('/api/tag/reset', methods=['POST'])
def api_tag_reset():
    global TAG_IMPLICATIONS

    TAG_IMPLICATIONS = {
        '绿帽': ['NTR', '绿系'],
        'NTR': ['绿系'],
    }
    CONFIG['custom_tags'] = []
    CONFIG['tag_implications'] = TAG_IMPLICATIONS

    save_tag_rules_file()
    save_json_file(CONFIG_FILE, CONFIG)
    return jsonify({'success': True})


@app.route('/api/tag/reapply', methods=['POST'])
def api_tag_reapply():
    count = 0
    for novel in novel_data:
        file_path = novel.get('file_path')
        if file_path and os.path.exists(file_path):
            new_info = parse_file_content_fast(file_path)
            if new_info['tags'] != novel.get('tags'):
                novel['tags'] = new_info['tags']
                count += 1
    
    save_cache()
    invalidate_filter_cache()
    return jsonify({'success': True, 'count': count})


# ==================== 配置路由 ====================
@app.route('/config')
def config_page():
    return render_template('config.html', config=CONFIG)


@app.route('/tag_manager')
def tag_manager():
    return render_template('tag_manager.html')


@app.route('/config/save', methods=['POST'])
def save_config_api():
    try:
        new_config = request.get_json(silent=True) or {}
        if not isinstance(new_config, dict):
            return jsonify({'success': False, 'message': '配置格式不正确'})

        checks = [
            ('app_port', 1024, 65535, '端口号必须在 1024-65535 之间'),
            ('per_page', 20, 500, '每页数量必须在 20-500 之间'),
            ('words_per_page', 1000, 50000, '每页字数必须在 1000-50000 之间'),
        ]
        for key, low, high, message in checks:
            if key not in new_config:
                continue
            try:
                value = int(new_config[key])
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': f'{key} 必须是整数'})
            if not (low <= value <= high):
                return jsonify({'success': False, 'message': message})
            new_config[key] = value

        current_config = load_config()
        for key in new_config:
            if key not in ('tag_implications', 'tag_aliases'):
                current_config[key] = new_config[key]

        for key in ('app_port', 'per_page', 'words_per_page', 'max_file_size_mb',
                    'max_tags_display', 'scan_interval_hours', 'backup_interval_days',
                    'max_backups', 'preload_recent_count'):
            if key in current_config:
                try:
                    current_config[key] = int(current_config[key])
                except (TypeError, ValueError):
                    pass

        current_config = {**get_default_config(), **current_config}
        save_json_file(CONFIG_FILE, current_config)

        global CONFIG, NOVEL_DIR, PER_PAGE, WORDS_PER_PAGE
        CONFIG = current_config
        NOVEL_DIR = CONFIG.get('novel_dir', NOVEL_DIR)
        PER_PAGE = CONFIG.get('per_page', 100)
        WORDS_PER_PAGE = CONFIG.get('words_per_page', 8000)
        invalidate_filter_cache()
        logger.info("配置已保存")
        return jsonify({'success': True})

    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})


@app.route('/config/reset', methods=['POST'])
def reset_config_api():
    global CONFIG, NOVEL_DIR, PER_PAGE, WORDS_PER_PAGE
    try:
        default_config = get_default_config()
        save_json_file(CONFIG_FILE, default_config)
        CONFIG = default_config
        NOVEL_DIR = CONFIG.get('novel_dir', NOVEL_DIR)
        PER_PAGE = CONFIG.get('per_page', 100)
        WORDS_PER_PAGE = CONFIG.get('words_per_page', 8000)
        invalidate_filter_cache()
        logger.info("配置已重置为默认值")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/tag/rules/edit')
def edit_tag_rules():
    content = load_json_file(TAG_RULES_FILE)
    content_str = json.dumps(content, ensure_ascii=False, indent=2)
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>编辑标签规则</title>
            <meta charset="utf-8">
            <style>
                body { font-family: monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }
                .container { max-width: 1200px; margin: 0 auto; }
                textarea { width: 100%; height: 70vh; background: #2d2d2d; color: #d4d4d4; 
                           border: 1px solid #555; padding: 15px; font-family: monospace; font-size: 14px; }
                button { padding: 10px 20px; margin-top: 10px; cursor: pointer; }
                .save-btn { background: #4caf50; color: white; border: none; border-radius: 4px; }
                .cancel-btn { background: #666; color: white; border: none; border-radius: 4px; }
                .info { background: #2d2d2d; padding: 10px; border-radius: 4px; margin-bottom: 10px; }
            </style>
            <script src="{{ url_for('static', filename='js/common.js') }}"></script>
        </head>
        <body>
            <div class="container">
                <h2>📝 编辑标签规则</h2>
                <div class="info">
                    💡 提示：修改后点击保存，然后点击"重载规则"生效<br>
                    📌 格式说明：implications 为派生规则，aliases 为别名映射
                </div>
                <textarea id="rulesContent">{{ content }}</textarea>
                <div>
                    <button class="save-btn" onclick="saveRules()">💾 保存</button>
                    <button class="cancel-btn" onclick="window.close()">❌ 关闭</button>
                </div>
            </div>
            <script>
                function saveRules() {
                    const content = document.getElementById('rulesContent').value;
                    fetch('/api/tag/rules/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ content: content })
                    })
                    .then(r => r.json())
                    .then(d => {
                        if (d.success) {
                            alert('保存成功！请点击"重载规则"生效');
                        } else {
                            alert('保存失败: ' + d.message);
                        }
                    });
                }
            </script>
        </body>
        </html>
    ''', content=content_str)


@app.route('/api/tag/rules/save', methods=['POST'])
def save_tag_rules():
    data = request.get_json()
    content = data.get('content', '')
    
    try:
        json.loads(content)
        save_json_file(TAG_RULES_FILE, json.loads(content))
        logger.info("标签规则已保存")
        return jsonify({'success': True})
    except json.JSONDecodeError as e:
        return jsonify({'success': False, 'message': f'JSON 格式错误: {e}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/tag/rules/reload', methods=['POST'])
def reload_tag_rules():
    global TAG_IMPLICATIONS, TAG_ALIASES, TAG_KEYWORDS, tag_parse_cache

    try:
        rules = load_json_file(TAG_RULES_FILE, {})
        TAG_IMPLICATIONS = rules.get('implications', {}) or {}
        TAG_ALIASES = rules.get('aliases', {}) or {}
        TAG_KEYWORDS = [str(k) for k in rules.get('keywords', [])]
        refresh_tag_rule_caches()
        tag_parse_cache.clear()
        logger.info("标签规则已重载，已清空缓存")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/tag/rules/open')
def open_tag_rules_file():
    return jsonify({'path': TAG_RULES_FILE})


@app.route('/config/reload', methods=['POST'])
def reload_config_api():
    global CONFIG, NOVEL_DIR, PER_PAGE, WORDS_PER_PAGE
    try:
        CONFIG = load_config()
        NOVEL_DIR = CONFIG.get('novel_dir', NOVEL_DIR)
        PER_PAGE = CONFIG.get('per_page', 100)
        WORDS_PER_PAGE = CONFIG.get('words_per_page', 8000)
        print("✅ 配置已重载")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/tag/rules/get')
def get_tag_rules():
    return jsonify({
        'keywords': TAG_KEYWORDS,
        'aliases': TAG_ALIASES,
        'implications': TAG_IMPLICATIONS
    })


@app.route('/api/tag/keyword/add', methods=['POST'])
def add_keyword():
    data = request.get_json()
    keyword = data.get('keyword', '').strip()
    
    if not keyword:
        return jsonify({'success': False, 'message': '关键词不能为空'})
    
    if keyword in TAG_KEYWORDS:
        return jsonify({'success': False, 'message': '关键词已存在'})
    
    TAG_KEYWORDS.append(keyword)
    save_tag_rules_file()
    return jsonify({'success': True})


@app.route('/api/tag/keyword/delete', methods=['POST'])
def delete_keyword():
    data = request.get_json(silent=True) or {}
    try:
        index = int(data.get('index'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '索引无效'})

    if 0 <= index < len(TAG_KEYWORDS):
        TAG_KEYWORDS.pop(index)
        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '索引无效'})


def save_tag_rules_file():
    rules = {
        'keywords': TAG_KEYWORDS,
        'aliases': TAG_ALIASES,
        'implications': TAG_IMPLICATIONS
    }
    save_json_file(TAG_RULES_FILE, rules)
    refresh_tag_rule_caches()


@app.route('/api/tag/keyword/edit', methods=['POST'])
def edit_keyword():
    data = request.get_json(silent=True) or {}
    try:
        index = int(data.get('index'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '索引无效'})

    keyword = str(data.get('keyword', '')).strip()
    if not keyword:
        return jsonify({'success': False, 'message': '关键词不能为空'})

    if 0 <= index < len(TAG_KEYWORDS):
        TAG_KEYWORDS[index] = keyword
        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '索引无效'})


@app.route('/api/tag/alias/add', methods=['POST'])
def add_alias():
    data = request.get_json()
    main = data.get('main', '').strip()
    aliases = data.get('aliases', [])
    
    if not main:
        return jsonify({'success': False, 'message': '主标签不能为空'})
    
    aliases = [a.strip() for a in aliases if a.strip()]
    TAG_ALIASES[main] = aliases
    save_tag_rules_file()
    return jsonify({'success': True})


@app.route('/api/tag/alias/edit', methods=['POST'])
def edit_alias():
    data = request.get_json()
    old_main = data.get('old_main', '').strip()
    new_main = data.get('new_main', '').strip()
    aliases = data.get('aliases', [])
    
    if not old_main or not new_main:
        return jsonify({'success': False, 'message': '标签名称不能为空'})
    
    if old_main in TAG_ALIASES:
        del TAG_ALIASES[old_main]
    
    if aliases:
        TAG_ALIASES[new_main] = [a.strip() for a in aliases if a.strip()]
    else:
        TAG_ALIASES[new_main] = []
    
    save_tag_rules_file()
    return jsonify({'success': True})


@app.route('/api/tag/alias/delete', methods=['POST'])
def delete_alias():
    data = request.get_json()
    main = data.get('main', '').strip()
    
    if main in TAG_ALIASES:
        del TAG_ALIASES[main]
        save_tag_rules_file()
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': '别名不存在'})


@app.route('/api/tag/alias/update', methods=['POST'])
def update_alias():
    data = request.get_json()
    main_tag = data.get('main_tag', '').strip()
    aliases_str = data.get('aliases', '').strip()
    
    if not main_tag:
        return jsonify({'success': False, 'message': '主标签不能为空'})
    
    if not aliases_str:
        return jsonify({'success': False, 'message': '别名不能为空'})
    
    aliases_list = re.split(r'[ ,，]+', aliases_str)
    aliases_list = [a.strip() for a in aliases_list if a.strip()]
    
    if not aliases_list:
        return jsonify({'success': False, 'message': '别名不能为空'})
    
    global TAG_ALIASES
    TAG_ALIASES[main_tag] = aliases_list
    save_tag_rules_file()
    return jsonify({'success': True})


@app.route('/api/tag/rule/add', methods=['POST'])
def add_derived_rule():
    data = request.get_json()
    source = data.get('source', '').strip()
    derived_list = data.get('derived', [])
    
    if not source:
        return jsonify({'success': False, 'message': '源标签不能为空'})
    
    derived_list = [d.strip() for d in derived_list if d.strip()]
    
    if source not in TAG_IMPLICATIONS:
        TAG_IMPLICATIONS[source] = []
    
    for derived in derived_list:
        if derived not in TAG_IMPLICATIONS[source]:
            TAG_IMPLICATIONS[source].append(derived)
    
    save_tag_rules_file()
    return jsonify({'success': True})


@app.route('/api/tag/rule/delete', methods=['POST'])
def delete_derived_rule():
    data = request.get_json(silent=True) or {}
    source = str(data.get('source', '')).strip()
    derived = str(data.get('derived', '')).strip()

    if source and derived:
        if source in TAG_IMPLICATIONS and derived in TAG_IMPLICATIONS[source]:
            TAG_IMPLICATIONS[source].remove(derived)
            if not TAG_IMPLICATIONS[source]:
                del TAG_IMPLICATIONS[source]
            save_tag_rules_file()
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': '规则不存在'})

    try:
        index = int(data.get('index'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '索引无效'})

    rules = []
    for src, derived_list in TAG_IMPLICATIONS.items():
        for d in derived_list:
            rules.append({'source': src, 'derived': d})

    if 0 <= index < len(rules):
        rule = rules[index]
        src = rule['source']
        d = rule['derived']

        if src in TAG_IMPLICATIONS and d in TAG_IMPLICATIONS[src]:
            TAG_IMPLICATIONS[src].remove(d)
            if not TAG_IMPLICATIONS[src]:
                del TAG_IMPLICATIONS[src]

        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '规则不存在'})


@app.route('/api/tag/rules/preview')
def preview_tag_rules():
    return jsonify({
        'keywords': TAG_KEYWORDS[:20],
        'keyword_total': len(TAG_KEYWORDS),
        'aliases': TAG_ALIASES,
        'implications': TAG_IMPLICATIONS
    })


@app.route('/config/get')
def get_config_api():
    return jsonify(CONFIG)


@app.route('/config/save_sort', methods=['POST'])
def save_sort_preference():
    try:
        data = request.get_json()
        sort_by = data.get('sort_by', 'title')
        sort_order = data.get('sort_order', 'asc')
        
        CONFIG['default_sort_by'] = sort_by
        CONFIG['default_sort_order'] = sort_order
        save_json_file(CONFIG_FILE, CONFIG)

        logger.info(f"排序偏好已保存: {sort_by} {sort_order}")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== 详情/阅读页文件失效提示 ====================
def render_missing_page(file_path, reason):
    """渲染友好的文件失效提示页（模块级，多处可调用）"""
    reasons = {
        'deleted': {
            'title': '文件不存在或已被删除',
            'desc': '这本书的文件可能已被移除、重命名或移动了位置。<br>'
                    '如果文件确实还在，请点击下方按钮重新扫描目录以更新缓存。',
            'class': 'deleted',
            'text': '❌ 文件未找到'
        },
        'modified': {
            'title': '文件已更新',
            'desc': '这本书的文件已被修改，当前缓存数据已过期。<br>'
                    '请执行一次扫描以更新最新内容，然后重新打开。',
            'class': 'modified',
            'text': '⚠️ 缓存已过期'
        },
        'error': {
            'title': '文件读取失败',
            'desc': '读取文件时发生错误，可能是权限问题或文件损坏。<br>'
                    '请检查文件后重试，或执行扫描刷新缓存。',
            'class': 'error',
            'text': '⚠️ 读取异常'
        }
    }
    info = reasons.get(reason, reasons['error'])
    return render_template(
        'novel_missing.html',
        title=os.path.basename(file_path),
        file_path=file_path,
        page_title=info['title'],
        page_desc=info['desc'],
        reason_class=info['class'],
        reason_text=info['text'],
        back_url=url_for('index'),
        is_admin=False   # 🔥 桌面版没有管理员概念
    ), 404

# ===================== 日志 =====================
@app.route('/logs')
def view_logs():
    log_file = LOG_FILE
    
    log_content = ''
    total_lines = 0
    file_size = '0 KB'
    display_lines = 0
    error_message = None
    
    if os.path.exists(log_file):
        try:
            size_bytes = os.path.getsize(log_file)
            if size_bytes < 1024:
                file_size = f'{size_bytes} B'
            elif size_bytes < 1024 * 1024:
                file_size = f'{size_bytes / 1024:.2f} KB'
            else:
                file_size = f'{size_bytes / 1024 / 1024:.2f} MB'
            
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                total_lines = len(lines)
                last_lines = lines[-500:] if len(lines) > 500 else lines
                display_lines = len(last_lines)
                log_content = ''.join(reversed(last_lines))
                
        except Exception as e:
            error_message = f'读取日志文件失败: {str(e)}'
    else:
        error_message = f'日志文件不存在: {log_file}\n请确保程序已运行过'
    
    return render_template('logs.html',
        log_content=log_content,
        log_file=log_file,
        file_size=file_size,
        total_lines=total_lines,
        display_lines=display_lines,
        error_message=error_message,
        auto_refresh=False
    )


@app.route('/logs/download')
def download_logs():
    if os.path.exists(LOG_FILE):
        return send_file(
            LOG_FILE,
            as_attachment=True,
            download_name=f'novel_manager_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
            mimetype='text/plain'
        )
    else:
        return "日志文件不存在", 404


@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    try:
        if os.path.exists(LOG_FILE):
            backup_file = LOG_FILE + '.bak'
            import shutil
            shutil.copy2(LOG_FILE, backup_file)
            print(f"📦 已备份日志到: {backup_file}")
        
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"日志已清空 - {datetime.now()}\n")
            f.write(f"清空时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 50 + "\n")
        
        return jsonify({'success': True, 'message': '日志已清空'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/tag/rules/import', methods=['POST'])
def import_tag_rules():
    try:
        rules = request.get_json()
        
        if 'keywords' in rules:
            global TAG_KEYWORDS
            TAG_KEYWORDS = rules['keywords']
        if 'aliases' in rules:
            global TAG_ALIASES
            TAG_ALIASES = rules['aliases']
        if 'implications' in rules:
            global TAG_IMPLICATIONS
            TAG_IMPLICATIONS = rules['implications']
        
        save_tag_rules_file()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===================== 本地图片/视频/音频 API =====================
IMAGE_MEDIA_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
VIDEO_MEDIA_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.wmv'}
AUDIO_MEDIA_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.wma', '.opus'}


def _serve_local_media(folder, name, extensions):
    """安全地提供小说目录内的本地媒体文件。"""
    if not folder or not name:
        return '', 400
    try:
        folder = os.path.realpath(str(folder))
        if not is_path_within(NOVEL_DIR, folder):
            return '', 403

        name = safe_basename(name)
        candidates = []
        _, name_ext = os.path.splitext(name)
        if name_ext.lower() in extensions:
            candidates.append(name)
        for ext in extensions:
            candidates.append(name + ext)

        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            file_path = safe_join(folder, candidate)
            if os.path.isfile(file_path):
                mime = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
                return send_file(file_path, mimetype=mime, conditional=True)
    except (OSError, TypeError, ValueError):
        return '', 403
    return '', 404


@app.route('/api/check_image_folder', methods=['POST'])
def check_image_folder():
    data = request.get_json(silent=True) or {}
    folders = data.get('folders', [])
    if not isinstance(folders, list):
        folders = []

    for folder in folders:
        try:
            folder = os.path.realpath(str(folder))
        except (TypeError, ValueError):
            continue
        if is_path_within(NOVEL_DIR, folder) and os.path.isdir(folder):
            return jsonify({'exists': True, 'path': folder})

    return jsonify({'exists': False, 'path': None})


@app.route('/api/local_image')
def serve_local_image():
    return _serve_local_media(
        request.args.get('folder', ''),
        request.args.get('name', ''),
        IMAGE_MEDIA_EXTENSIONS
    )


@app.route('/api/list_image_folder', methods=['POST'])
def list_image_folder():
    data = request.get_json(silent=True) or {}
    folder = data.get('folder', '')
    try:
        folder = os.path.realpath(str(folder))
    except (TypeError, ValueError):
        return jsonify({'files': []})

    if not is_path_within(NOVEL_DIR, folder) or not os.path.isdir(folder):
        return jsonify({'files': []})

    files = []
    for f in os.listdir(folder):
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_MEDIA_EXTENSIONS:
            files.append(f)
    return jsonify({'files': files})


@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    data = request.get_json(silent=True) or {}
    path = data.get('path', '')
    try:
        path = os.path.realpath(str(path))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '路径不合法'})

    if not is_path_within(NOVEL_DIR, path) or not os.path.exists(path):
        return jsonify({'success': False, 'message': '文件夹不存在或不可访问'})

    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/local_video')
def serve_local_video():
    return _serve_local_media(
        request.args.get('folder', ''),
        request.args.get('name', ''),
        VIDEO_MEDIA_EXTENSIONS
    )


@app.route('/api/local_audio')
def serve_local_audio():
    return _serve_local_media(
        request.args.get('folder', ''),
        request.args.get('name', ''),
        AUDIO_MEDIA_EXTENSIONS
    )


# ==================== 媒体检测功能 ====================
def detect_media_issues(file_path, media_type='all'):
    result = {
        'has_issues': False,
        'missing_in_txt': [],
        'extra_markers': [],
        'duplicate_markers': [],
        'media_files': [],
        'markers': []
    }
    
    if not os.path.exists(file_path):
        return result
    
    filename = os.path.basename(file_path)
    image_folder = get_image_folder_for_novel(filename)
    
    if not image_folder:
        return result
    
    media_config = {
        'image': {
            'extensions': {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'},
            'patterns': [r'\[img:([^\]]+)\]', r'\[图:([^\]]+)\]', r'\[image:([^\]]+)\]'],
            'display_name': '图片'
        },
        'video': {
            'extensions': {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.wmv'},
            'patterns': [r'\[video:([^\]]+)\]', r'\[vid:([^\]]+)\]', r'\[视频:([^\]]+)\]'],
            'display_name': '视频'
        },
        'audio': {
            'extensions': {'.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.wma', '.opus'},
            'patterns': [r'\[audio:([^\]]+)\]', r'\[aud:([^\]]+)\]', r'\[音乐:([^\]]+)\]', r'\[音频:([^\]]+)\]'],
            'display_name': '音频'
        }
    }
    
    if media_type != 'all' and media_type in media_config:
        media_config = {media_type: media_config[media_type]}
    
    try:
        content = read_file_with_encoding(file_path)
    except Exception as e:
        print(f"⚠️ 读取文件失败 {file_path}: {e}")
        return result
    
    for mtype, config in media_config.items():
        media_files = []
        for f in os.listdir(image_folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in config['extensions']:
                name_without_ext = os.path.splitext(f)[0]
                media_files.append({
                    'filename': f,
                    'number': name_without_ext,
                    'path': os.path.join(image_folder, f)
                })
        
        if not media_files:
            continue
        
        media_numbers = {f['number'] for f in media_files}
        
        markers_raw = []
        markers_normalized = []
        for pattern in config['patterns']:
            matches = re.findall(pattern, content)
            for match in matches:
                match_stripped = match.strip()
                markers_raw.append(match_stripped)
                parts = match_stripped.strip().split()
                number = parts[0].strip() if parts else match_stripped
                markers_normalized.append(number)
        
        marker_set = set(markers_normalized)
        
        for f in media_files:
            if f['number'] not in marker_set:
                result['missing_in_txt'].append((mtype, f))
        
        seen_extra = set()
        for i, norm_marker in enumerate(markers_normalized):
            if norm_marker not in media_numbers and markers_raw[i] not in seen_extra:
                seen_extra.add(markers_raw[i])
                result['extra_markers'].append((mtype, markers_raw[i]))
        
        seen = {}
        for norm_marker in markers_normalized:
            seen[norm_marker] = seen.get(norm_marker, 0) + 1
        
        for norm_marker, count in seen.items():
            if count > 1:
                example = next((m for i, m in enumerate(markers_raw) if markers_normalized[i] == norm_marker), norm_marker)
                result['duplicate_markers'].append((mtype, {
                    'normalized': norm_marker,
                    'raw': example,
                    'count': count
                }))
        
        if result['missing_in_txt'] or result['extra_markers'] or result['duplicate_markers']:
            result['has_issues'] = True
        
        result['media_files'].extend([(mtype, f) for f in media_files])
        result['markers'].extend([(mtype, m) for m in markers_raw])
    
    return result

#==================== 媒体检测 API ====================
@app.route('/api/media/detect', methods=['POST'])
def api_media_detect():
    data = request.get_json(silent=True) or {}
    file_path = str(data.get('file_path', '') or '').strip()
    media_type = data.get('media_type', 'all')

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不能为空'})

    # 🔥 兼容"孤立配图文件夹"：直接返回缺少 TXT 的提示
    if os.path.isdir(file_path) and is_path_within(NOVEL_DIR, file_path):
        media_exts = (IMAGE_MEDIA_EXTENSIONS | VIDEO_MEDIA_EXTENSIONS | AUDIO_MEDIA_EXTENSIONS)
        media_files = []
        try:
            for f in os.listdir(file_path):
                if os.path.splitext(f)[1].lower() in media_exts:
                    media_files.append(f)
        except OSError:
            pass
        return jsonify({
            'success': True,
            'has_issues': True,
            'missing_txt': True,
            'missing': [],
            'extra': [],
            'duplicate': [],
            'media_files_count': len(media_files),
            'markers_count': 0,
            'message': '该配图文件夹缺少对应的 TXT 文件',
        })

    filename = os.path.basename(file_path)
    full_path = os.path.join(NOVEL_DIR, filename)

    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': '文件不存在'})

    result = detect_media_issues(full_path, media_type)
    logger.info(
        f"媒体检测 {os.path.basename(full_path)}: "
        f"缺失={len(result.get('missing_in_txt', []))}, "
        f"多余={len(result.get('extra_markers', []))}, "
        f"重复={len(result.get('duplicate_markers', []))}"
    )

    missing_list = []
    for mtype, f in result.get('missing_in_txt', []):
        missing_list.append({
            'type': mtype,
            'filename': f['filename'],
            'number': f['number'],
        })

    extra_list = []
    for mtype, m in result.get('extra_markers', []):
        extra_list.append({'type': mtype, 'marker': m})

    duplicate_list = []
    for mtype, d in result.get('duplicate_markers', []):
        duplicate_list.append({
            'type': mtype,
            'marker': d['raw'],
            'count': d['count'],
        })

    return jsonify({
        'success': True,
        'has_issues': result['has_issues'],
        'missing_txt': False,
        'missing': missing_list,
        'extra': extra_list,
        'duplicate': duplicate_list,
        'media_files_count': len(result['media_files']),
        'markers_count': len(result['markers']),
    })

#==================== 扫描所有小说媒体问题 ====================
def run_media_scan_all_task(task_id, media_type):
    """后台执行全量媒体标记检测（含孤立配图文件夹、命名不规范的配图文件夹）。"""
    try:
        ignore_list = load_media_ignore_list()
        ignore_keys = {_media_path_key(item.get('file_path')) for item in ignore_list}

        # ===== 0) 先扫「命名不规范」的配图文件夹 =====
        # 这类目录里有媒体文件，但名字不是 *_images / *_配图，
        # 系统识别不到 → 配图直接丢失，且不会出现在孤立目录里。
        misnamed_results = []
        misnamed_ignored = 0
        for item in find_misnamed_media_folders():
            if _media_path_key(item['folder']) in ignore_keys:
                misnamed_ignored += 1
                continue
            misnamed_results.append({
                'title': item['folder_name'],
                'file_path': item['folder'],
                'img_folder': item['folder'],
                'error': 'misnamed',
                'message': item['reason'],
                'suggestion': item.get('suggestion'),
                'media_count': item.get('media_count', 0),
                'missing': 0,
                'extra': 0,
                'duplicate': 0,
                'missing_detail': [],
                'extra_detail': [],
                'duplicate_detail': [],
            })

        # ===== 1) 再扫孤立配图文件夹（有配图但无 TXT）=====
        orphans = find_orphan_media_folders()
        orphan_results = []
        orphan_ignored = 0
        for orphan in orphans:
            if _media_path_key(orphan['folder']) in ignore_keys:
                orphan_ignored += 1
                continue
            orphan_results.append({
                'title': f"{orphan['base_name']} (缺少TXT)",
                'file_path': orphan['folder'],
                'img_folder': orphan['folder'],
                'error': 'missing_txt',
                'missing': 0,
                'extra': 0,
                'duplicate': 0,
                'missing_detail': [],
                'extra_detail': [],
                'duplicate_detail': [],
            })

        # ===== 2) 再扫有 TXT 的小说 =====
        novels = [
            n for n in list(novel_data)
            if n.get('file_path') and os.path.exists(n.get('file_path'))
        ]

        total = len(novels) + len(orphans) + len(misnamed_results)
        scanned = len(orphans) + len(misnamed_results)  # 这两类已"检查完"
        _parts = []
        if misnamed_results:
            _parts.append(f'{len(misnamed_results)} 个命名不规范')
        if orphan_results:
            _parts.append(f'{len(orphan_results)} 个缺少TXT')
        update_background_task(
            task_id, total=total, current=scanned,
            message=(f'发现 {"，".join(_parts)} 的配图文件夹，开始检测小说...'
                     if _parts else '正在检测媒体标记...')
        )

        results = list(misnamed_results) + list(orphan_results)
        processed = 0
        ignored_count = orphan_ignored + misnamed_ignored

        for novel in novels:
            file_path = novel.get('file_path')
            real_key = _media_path_key(file_path)

            if real_key in ignore_keys:
                ignored_count += 1
                scanned += 1
                update_background_task(
                    task_id, current=scanned,
                    message=f'已忽略：{os.path.basename(file_path)[:30]}'
                )
                continue

            result = detect_media_issues(file_path, media_type)
            if result['has_issues']:
                results.append({
                    'title': novel.get('title', os.path.basename(file_path)),
                    'file_path': file_path,
                    'missing': len(result.get('missing_in_txt', [])),
                    'extra': len(result.get('extra_markers', [])),
                    'duplicate': len(result.get('duplicate_markers', [])),
                    'missing_detail': result.get('missing_in_txt', []),
                    'extra_detail': result.get('extra_markers', []),
                    'duplicate_detail': result.get('duplicate_markers', []),
                })

            processed += 1
            scanned += 1
            update_background_task(
                task_id, current=scanned,
                message=f'检测中：{os.path.basename(file_path)[:30]}'
            )

        # 命名不规范 / 缺TXT 的排最前面，其余按问题数倒序
        _order = {'misnamed': 0, 'missing_txt': 1}
        results.sort(key=lambda x: (
            _order.get(x.get('error'), 2),
            -(x['missing'] + x['extra'] + x['duplicate'])
        ))

        finish_background_task(task_id, result={
            'success': True,
            'total_checked': processed,
            'ignored_count': ignored_count,
            'problem_count': len(results),
            'orphan_count': len(orphan_results),
            'misnamed_count': len(misnamed_results),
            'results': results,
        })
        logger.info(
            f"媒体检测完成 - 检查 {processed} 本, 命名不规范 {len(misnamed_results)} 个, "
            f"忽略 {ignored_count}, 发现问题 {len(results)} 处"
        )
    except Exception as e:
        traceback.print_exc()
        finish_background_task(task_id, error=e)


@app.route('/api/media/scan_all', methods=['POST'])
def api_media_scan_all():
    data = request.get_json(silent=True) or {}
    media_type = data.get('media_type', 'all')
    if media_type not in ('all', 'image', 'video', 'audio'):
        media_type = 'all'

    task_id = create_background_task('media_scan_all', message='准备扫描媒体标记...')
    threading.Thread(
        target=run_media_scan_all_task,
        args=(task_id, media_type),
        daemon=True
    ).start()
    return jsonify({'success': True, 'task_id': task_id})


@app.route('/api/task/<task_id>/progress')
def api_task_progress(task_id):
    task = get_background_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    total = task.get('total') or 0
    current = task.get('current') or 0
    progress = int(current / total * 100) if total else 0
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task.get('status'),
        'current': current,
        'total': total,
        'progress': progress,
        'message': task.get('message', '')
    })


@app.route('/api/task/<task_id>/result')
def api_task_result(task_id):
    task = get_background_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if task.get('status') == 'running':
        return jsonify({'success': False, 'message': '任务尚未完成'}), 409
    if task.get('status') == 'error':
        return jsonify({'success': False, 'message': task.get('error') or '任务失败'}), 500

    result = task.get('result') or {}
    result.setdefault('success', True)
    return jsonify(result)


#==================== 获取配图文件夹 ====================
@app.route('/api/media/get_folder', methods=['POST'])
def api_media_get_folder():
    data = request.get_json(silent=True) or {}
    file_path = str(data.get('file_path', '') or '').strip()

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不能为空'})

    # 🔥 如果本身就是文件夹（孤立配图场景），直接返回
    if os.path.isdir(file_path) and is_path_within(NOVEL_DIR, file_path):
        return jsonify({'success': True, 'folder': os.path.realpath(file_path)})

    filename = os.path.basename(file_path)
    folder = get_image_folder_for_novel(filename)

    if folder and os.path.exists(folder):
        return jsonify({'success': True, 'folder': folder})
    return jsonify({'success': False, 'message': '配图文件夹不存在'})

#==================== 打开配图文件夹 ====================
@app.route('/api/media/open_folder', methods=['POST'])
def api_media_open_folder():
    data = request.get_json(silent=True) or {}
    folder = data.get('folder', '')
    try:
        folder = os.path.realpath(str(folder))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '路径不合法'})

    if not is_path_within(NOVEL_DIR, folder) or not os.path.isdir(folder):
        return jsonify({'success': False, 'message': '文件夹不存在或不可访问'})

    try:
        if sys.platform == 'win32':
            os.startfile(folder)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/media_detect')
def media_detect_page():
    return render_template('media_detect.html', novel_data=novel_data)

# ==================== 媒体检测忽略列表 ====================
MEDIA_IGNORE_FILE = os.path.join(DATA_DIR, 'media_ignore.json')


def _media_path_key(path):
    """归一化路径，用于忽略列表比对（兼容大小写、分隔符、相对路径）。"""
    try:
        return os.path.normcase(os.path.realpath(str(path or '')))
    except (TypeError, ValueError):
        return str(path or '')


def find_orphan_media_folders():
    """查找有配图文件夹但缺少对应 TXT 的孤立文件夹。

    只返回真正含有媒体文件的文件夹，避免噪音。
    """
    orphans = []
    if not os.path.isdir(NOVEL_DIR):
        return orphans

    # 已存在的 TXT 基名集合（小写，不含扩展名）
    txt_basenames = set()
    try:
        for f in os.listdir(NOVEL_DIR):
            if f.lower().endswith('.txt'):
                txt_basenames.add(os.path.splitext(f)[0].lower())
    except OSError as e:
        logger.warning(f"读取小说目录失败，无法检测孤立配图文件夹: {e}")
        return orphans

    media_exts = (IMAGE_MEDIA_EXTENSIONS | VIDEO_MEDIA_EXTENSIONS | AUDIO_MEDIA_EXTENSIONS)

    try:
        entries = os.listdir(NOVEL_DIR)
    except OSError as e:
        logger.warning(f"读取小说目录失败: {e}")
        return orphans

    for entry in entries:
        full = os.path.join(NOVEL_DIR, entry)
        if not os.path.isdir(full):
            continue

        base = None
        if entry.endswith('_images'):
            base = entry[:-len('_images')]
        elif entry.endswith('_配图'):
            base = entry[:-len('_配图')]
        else:
            continue

        if not base:
            continue
        if base.lower() in txt_basenames:
            continue

        # 检查文件夹里是否真的有媒体文件（递归，配图常按章节分子目录）
        has_media = False
        media_files = []
        try:
            for root, dirs, files in os.walk(full):
                if root.rstrip(os.sep).count(os.sep) - full.rstrip(os.sep).count(os.sep) >= 3:
                    dirs[:] = []
                for f in files:
                    if f.startswith('.'):
                        continue
                    if os.path.splitext(f)[1].lower() in media_exts:
                        has_media = True
                        media_files.append(f)
        except OSError:
            continue

        if has_media:
            orphans.append({
                'folder': full,
                'folder_name': entry,
                'base_name': base,
                'media_count': len(media_files),
            })

    return orphans


def find_misnamed_media_folders():
    """查找「命名不规范」的配图文件夹 —— 即含媒体文件、但名字不符合
    _images / _配图 约定的目录，系统因此识别不到它，配图就丢了。

    典型三种错法（都真实遇到过）：
      1. 少了前导下划线：`书名images`        → 应为 `书名_images`
      2. 用了别的前缀：   `书名_image` / `书名配图`（无下划线）
      3. 完全没有后缀：   `书名`              （与 TXT 同名的目录）

    第 3 种需要与 TXT 基名比对才能判断：目录名 == 某个 TXT 的基名，
    说明它是「本该带后缀的配图目录」而不是普通子目录。

    返回 list[dict]：folder / folder_name / suggestion / media_count / reason
    """
    results = []
    if not os.path.isdir(NOVEL_DIR):
        return results

    txt_basenames = set()
    try:
        entries = os.listdir(NOVEL_DIR)
        for f in entries:
            if f.lower().endswith('.txt'):
                txt_basenames.add(os.path.splitext(f)[0].lower())
    except OSError as e:
        logger.warning(f"读取小说目录失败，无法检测配图文件夹命名: {e}")
        return results

    media_exts = (IMAGE_MEDIA_EXTENSIONS | VIDEO_MEDIA_EXTENSIONS | AUDIO_MEDIA_EXTENSIONS)

    # 常见的错误后缀写法 → 正确写法
    bad_suffixes = [
        ('images', '_images'), ('_image', '_images'), ('image', '_images'),
        ('_imgs', '_images'), ('imgs', '_images'), ('_img', '_images'), ('img', '_images'),
        ('_插图', '_配图'), ('插图', '_配图'), ('_配图夹', '_配图'),
        ('配图', '_配图'),      # 无下划线
        ('_pics', '_配图'), ('pics', '_配图'),
        ('_图', '_配图'), ('图', '_配图'),
    ]

    for entry in entries:
        full = os.path.join(NOVEL_DIR, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith('.'):
            continue
        # 已规范命名的跳过
        if entry.endswith('_images') or entry.endswith('_配图'):
            continue

        # 递归统计媒体文件（限深 3 层）
        media_count = 0
        base_depth = full.rstrip(os.sep).count(os.sep)
        try:
            for root, dirs, files in os.walk(full):
                if root.rstrip(os.sep).count(os.sep) - base_depth >= 3:
                    dirs[:] = []
                for f in files:
                    if f.startswith('.'):
                        continue
                    if os.path.splitext(f)[1].lower() in media_exts:
                        media_count += 1
        except OSError:
            continue
        if media_count == 0:
            continue

        suggestion = None
        reason = None

        # 1) 与某个 TXT 基名完全相同 → 缺后缀
        if entry.lower() in txt_basenames:
            suggestion = entry + '_images'
            reason = '缺少 _images / _配图 后缀'
        else:
            # 2) 结尾看起来像配图后缀但少下划线/写错
            for bad, good in bad_suffixes:
                if entry.lower().endswith(bad):
                    head = entry[:-len(bad)]
                    if head:
                        suggestion = head + good
                        reason = '后缀写作 “%s”，应为 “%s”' % (bad, good)
                    break

        if reason is None:
            continue

        if suggestion and os.path.isdir(os.path.join(NOVEL_DIR, suggestion)):
            reason += '（建议的目标名已存在，改名会冲突）'

        results.append({
            'folder': full,
            'folder_name': entry,
            'suggestion': suggestion,
            'media_count': media_count,
            'reason': reason,
            'base_name': (_strip_media_suffix(suggestion) if suggestion else entry),
        })

    results.sort(key=lambda x: -x['media_count'])
    return results


def _strip_media_suffix(name):
    """去掉 _images / _配图 后缀"""
    for suf in ('_images', '_配图'):
        if name.endswith(suf):
            return name[:-len(suf)]
    return name

def load_media_ignore_list():
    """加载媒体检测忽略列表（保证返回 list）。"""
    data = load_json_file(MEDIA_IGNORE_FILE, [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get('file_path')]


def save_media_ignore_list(ignore_list):
    """保存媒体检测忽略列表。"""
    return save_json_file(MEDIA_IGNORE_FILE, list(ignore_list or []))

@app.route('/api/media/ignore/list', methods=['GET'])
def api_media_ignore_list():
    """获取忽略列表"""
    return jsonify({
        'success': True,
        'ignore_list': load_media_ignore_list()
    })


@app.route('/api/media/ignore/add', methods=['POST'])
def api_media_ignore_add():
    """添加忽略项"""
    data = request.get_json(silent=True) or {}
    file_path = str(data.get('file_path', '') or '').strip()
    reason = str(data.get('reason', '') or '').strip()

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不能为空'})

    # 校验路径是否在 NOVEL_DIR 内（允许文件夹路径，孤立配图场景）
    real_path = os.path.realpath(file_path)
    if not is_path_within(NOVEL_DIR, real_path):
        return jsonify({'success': False, 'message': '路径不合法'})

    ignore_list = load_media_ignore_list()
    new_key = _media_path_key(real_path)

    for item in ignore_list:
        if _media_path_key(item.get('file_path')) == new_key:
            return jsonify({'success': False, 'message': '已存在忽略列表中'})

    ignore_list.append({
        'file_path': real_path,
        'reason': reason,
        'added_at': datetime.now().isoformat(),
    })

    save_media_ignore_list(ignore_list)
    return jsonify({'success': True, 'message': '已添加到忽略列表'})


@app.route('/api/media/ignore/remove', methods=['POST'])
def api_media_ignore_remove():
    """移除忽略项"""
    data = request.get_json(silent=True) or {}
    file_path = str(data.get('file_path', '') or '').strip()

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不能为空'})

    target_key = _media_path_key(file_path)
    ignore_list = load_media_ignore_list()
    new_list = [item for item in ignore_list
                if _media_path_key(item.get('file_path')) != target_key]

    save_media_ignore_list(new_list)
    return jsonify({'success': True, 'message': '已从忽略列表中移除'})


@app.route('/api/media/ignore/clear', methods=['POST'])
def api_media_ignore_clear():
    """清空忽略列表"""
    save_media_ignore_list([])
    return jsonify({'success': True, 'message': '已清空忽略列表'})


@app.route('/api/media/ignore/update', methods=['POST'])
def api_media_ignore_update():
    """更新忽略项的备注原因"""
    data = request.get_json(silent=True) or {}
    file_path = str(data.get('file_path', '') or '').strip()
    reason = str(data.get('reason', '') or '').strip()

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不能为空'})

    target_key = _media_path_key(file_path)
    ignore_list = load_media_ignore_list()
    found = False
    for item in ignore_list:
        if _media_path_key(item.get('file_path')) == target_key:
            item['reason'] = reason
            found = True
            break

    if not found:
        return jsonify({'success': False, 'message': '忽略项不存在'})

    save_media_ignore_list(ignore_list)
    return jsonify({'success': True, 'message': '备注已更新'})


# ==================== 表情映射 API ====================
def load_emoji_mapping():
    default_mapping = {
        "微笑": "😊", "大笑": "😂", "偷笑": "😏", "得意": "😎",
        "调皮": "😜", "吐舌": "😝", "眨眼": "😉", "害羞": "😊",
        "尴尬": "😅", "冷汗": "😰", "惊讶": "😲", "惊恐": "😱",
        "流泪": "😢", "大哭": "😭", "伤心": "😔", "生气": "😠",
        "愤怒": "🤬", "抓狂": "🤯", "无语": "😑",
    }
    return load_json_file(EMOJI_MAPPING_FILE, default_mapping)


def load_image_mapping():
    default_mapping = {
        "抠鼻": "/static/emojis/koubi.png",
        "狗头": "/static/emojis/doge.png",
        "旺柴": "/static/emojis/wangchai.png"
    }
    return load_json_file(IMAGE_MAPPING_FILE, default_mapping)


@app.route('/api/emoji/image-mapping')
def get_image_mapping():
    return jsonify(load_image_mapping())


@app.route('/api/emoji/image-mapping/save', methods=['POST'])
def save_image_mapping():
    try:
        mapping = request.get_json()
        save_json_file(IMAGE_MAPPING_FILE, mapping)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/emoji/mapping')
def get_emoji_mapping():
    return jsonify(load_emoji_mapping())


# ===================== 跨行括号高亮 =====================
_FW_INDENT_RE = re.compile(r'(?m)^[ \t\u3000]+')


def _collapse_fullwidth_indent(content):
    """把每行开头的连续全角/半角空白压成最多两个 &emsp;

    TXT 正文常用整串全角空格做缩进/居中排版。若逐字符换成 &emsp;，
    行首会出现几十个全角宽、又不允许断行的占位符，把行撑出容器，
    移动端就表现为「这一章可以左右拖动」。这里只保留最多两个（约两字缩进）。
    """
    if not content:
        return content

    def _repl(match):
        return '&emsp;&emsp;' if match.group(0) else ''

    return _FW_INDENT_RE.sub(_repl, content)


def highlight_crossline_brackets(text):
    """给跨行的引号/括号加高亮 span

    注意：本函数会插入 HTML 标签，正文先做 HTML 转义，避免 TXT 里的
    <script>/<img onerror> 之类内容被浏览器当代码执行。
    """
    if not text:
        return text

    bracket_pairs = [
        ('“', '”', 'highlight-quote-double'),
        ('‘', '’', 'highlight-quote-single'),
        ('（', '）', 'highlight-bracket'),
        ('【', '】', 'highlight-square-bracket'),
        ('《', '》', 'highlight-book'),
        ('「', '」', 'highlight-quote-double'),
        ('『', '』', 'highlight-quote-single'),
        ('[', ']', 'highlight-square-bracket-1'),
        ('［', '］', 'highlight-square-bracket-1'),
        ('〖', '〗', 'highlight-hollow-bracket'),
    ]

    # 先转义，避免小说正文中的 <script>/<img onerror> 等被 |safe 输出后执行
    result = html_escape(text)

    for left, right, css_class in bracket_pairs:
        pattern = re.compile(
            f'{re.escape(left)}([^{re.escape(left)}{re.escape(right)}]*?){re.escape(right)}',
            re.DOTALL
        )

        def repl(match, left=left, right=right, css_class=css_class):
            content = match.group(1)
            if '\n' not in content:
                return match.group(0)

            content = _collapse_fullwidth_indent(content)

            # 关键：不要用 <br> 把整段压成一行。
            # 调用方会把结果按 '\n' 重新切成多行，每行渲染成独立的
            # <div class="content-line">，这样跨行引号的每一行都能各自
            # 应用 text-indent（用 <br> 的话第 2 行起算「续行」，没有缩进）。
            #
            # 每一行都包一个完整、闭合的 <span>，保证切行后每段 HTML 都合法。
            parts = content.split('\n')
            wrapped = []
            for idx, part in enumerate(parts):
                head = left if idx == 0 else ''
                tail = right if idx == len(parts) - 1 else ''
                wrapped.append(f'<span class="{css_class}">{head}{part}{tail}</span>')
            return '\n'.join(wrapped)

        result = pattern.sub(repl, result)

    return result

# ==================== TXT 文件体检/修复 ====================

FULLWIDTH_LETTER_RE = re.compile(r'[Ａ-Ｚａ-ｚ]')
FULLWIDTH_DIGIT_RE = re.compile(r'[０-９]')
FULLWIDTH_SPACE_RE = re.compile(r'\u3000')
FULLWIDTH_COMMON_PUNCT_RE = re.compile(r'[，。！？；：\u201c\u201d\u2018\u2019（）《》【】、…—]')
FULLWIDTH_SYMBOL_RE = re.compile(r'[＂＃＄％＆＇＊＋－．／＜＝＞＠［＼］＾＿｀｛｜｝～]')
CJK_RE = re.compile(r'[\u4e00-\u9fff]')
COMMON_CN_PUNCT_RE = re.compile(r'[，。！？；：\u201c\u201d\u2018\u2019（）《》【】、…—]')
CONTROL_RE = re.compile(r'[\x01-\x08\x0b\x0c\x0e-\x1f]')
ZERO_WIDTH_RE = re.compile(r'[\u200b\u200c\u200d\ufeff]')
# 双重编码乱码：UTF-8 被按 latin1/gbk 解读后的典型残留。
# 要求至少连续两组匹配，避免把正常文本里单个 Ã/Â 误判为乱码。
MOJIBAKE_RE = re.compile(r'(?:锟斤拷|烫烫烫|屯屯屯|ï»¿|[\x80-\xff]{3,})')
UNICODE_LINE_SEP_RE = re.compile(r'[\u2028\u2029]')
PRIVATE_USE_RE = re.compile(r'[\ue000-\uf8ff]')
ASCII_PRINTABLE_RE = re.compile(r'[\x20-\x7e]')
# 单次扫描：零宽 / 控制 / 空字符 / 替换字符 / 私用区
SUSPICIOUS_SCAN_RE = re.compile(
    '[\x00\ufffd'
    '\x01-\x08\x0b\x0c\x0e-\x1f'
    '​‌‍﻿'
    '\ue000-\uf8ff]'
)
ASCII_PRINTABLE_RE = re.compile(r'[\x20-\x7e]')
# 单次扫描：零宽 / 控制 / 空字符 / 替换字符 / 私用区
SUSPICIOUS_SCAN_RE = re.compile(
    '[\x00\ufffd'
    '\x01-\x08\x0b\x0c\x0e-\x1f'
    '\u200b\u200c\u200d\ufeff'
    '\ue000-\uf8ff]'
)
# 采样字节数（受字符边界对齐，避免误判大文件）
ENCODING_SAMPLE_LIMIT = 2 * 1024 * 1024


def _score_candidate_text(text):
    """给候选编码解码出的文本打分，分越高越像正常中文 TXT。"""
    if not text:
        return -1e9, {}

    total = max(len(text), 1)
    cjk = len(CJK_RE.findall(text))
    common_punct = len(COMMON_CN_PUNCT_RE.findall(text))
    ascii_printable = len(ASCII_PRINTABLE_RE.findall(text))
    replacement = text.count('\ufffd')
    controls = len(CONTROL_RE.findall(text))
    zero_width = len(ZERO_WIDTH_RE.findall(text))
    mojibake = len(MOJIBAKE_RE.findall(text))
    private_use = len(PRIVATE_USE_RE.findall(text))

    # 「干净可读字符」占比：正确解码时正文几乎全是汉字/中文标点/空格/换行。
    clean = cjk + common_punct + ascii_printable
    clean_ratio = clean / total

    score = (
        cjk * 3.0
        + common_punct * 5.0
        + ascii_printable * 0.2
        + clean_ratio * 60.0
        - replacement * 80.0
        - controls * 40.0
        - zero_width * 30.0
        - mojibake * 60.0
        - private_use * 60.0
    )
    detail = {
        'cjk': cjk,
        'common_punctuation': common_punct,
        'ascii_printable': ascii_printable,
        'replacement': replacement,
        'controls': controls,
        'zero_width': zero_width,
        'mojibake': mojibake,
        'private_use': private_use,
    }
    return score / total * 1000.0, detail


def _align_utf8_boundary(chunk):
    """回退到最近的合法 UTF-8 起始边界，避免采样把多字节字符切成两半。"""
    for back in range(0, 5):
        end = len(chunk) - back
        if end <= 0:
            break
        try:
            chunk[:end].decode('utf-8')
            return chunk[:end]
        except UnicodeDecodeError:
            continue
    return chunk


def _looks_like_utf8(chunk):
    """判定字节流是否为合法 UTF-8；仅容忍尾部最多 4 字节的残缺字符。"""
    try:
        chunk.decode('utf-8')
        return True
    except UnicodeDecodeError as exc:
        return exc.start >= len(chunk) - 4


def _detect_text_encoding(raw_data):
    """检测 TXT 编码：BOM -> 严格 UTF-8 -> 多候选解码评分。"""
    sample = _align_utf8_boundary(raw_data[:ENCODING_SAMPLE_LIMIT])
    info = {
        'detected': 'utf-8',
        'confidence': 0.0,
        'is_utf8': True,
        'has_bom': False,
        'bom_type': None,
        'strict_utf8_ok': False,
        'candidates': [],
        'chardet': None,
    }

    if sample.startswith(b'\xef\xbb\xbf'):
        info.update({
            'detected': 'utf-8-sig',
            'confidence': 1.0,
            'is_utf8': True,
            'has_bom': True,
            'bom_type': 'utf-8',
            'strict_utf8_ok': True,
        })
        return info
    if sample.startswith(b'\xff\xfe'):
        info.update({
            'detected': 'utf-16-le',
            'confidence': 1.0,
            'is_utf8': False,
            'has_bom': True,
            'bom_type': 'utf-16-le',
            'strict_utf8_ok': False,
        })
        return info
    if sample.startswith(b'\xfe\xff'):
        info.update({
            'detected': 'utf-16-be',
            'confidence': 1.0,
            'is_utf8': False,
            'has_bom': True,
            'bom_type': 'utf-16-be',
            'strict_utf8_ok': False,
        })
        return info

    info['strict_utf8_ok'] = _looks_like_utf8(sample)

    try:
        detected = chardet.detect(sample[:100000]) or {}
        info['chardet'] = {
            'encoding': detected.get('encoding'),
            'confidence': detected.get('confidence', 0),
        }
    except Exception:
        info['chardet'] = None

    # 无 BOM 的 UTF-16 极少见（ASCII/西文文件误判成 utf-16 的重灾区），
    # 因此只有带 BOM 时才把 utf-16 纳入候选，避免抢占真实编码。
    candidates = ['utf-8', 'gb18030', 'gbk', 'big5']
    if raw_data.startswith(b'\xff\xfe') or raw_data.startswith(b'\xfe\xff'):
        candidates += ['utf-16-le', 'utf-16-be']
    chardet_encoding = (info['chardet'] or {}).get('encoding') or ''
    chardet_encoding = chardet_encoding.lower().replace('-', '')

    scored = []
    for enc in candidates:
        if enc.startswith('utf-8') and _looks_like_utf8(sample):
            text = sample.decode('utf-8', errors='ignore')
        else:
            try:
                text = sample.decode(enc)
            except UnicodeDecodeError:
                continue
        score, detail = _score_candidate_text(text)
        if enc == 'utf-8' and info['strict_utf8_ok']:
            score += 35.0
        if chardet_encoding:
            if enc in ('gbk', 'gb18030') and chardet_encoding in ('gb2312', 'gbk', 'gb18030'):
                score += 25.0
            elif enc == 'big5' and chardet_encoding == 'big5':
                score += 25.0
            elif enc == 'utf-8' and chardet_encoding in ('utf8', 'ascii'):
                score += 25.0
            elif enc == 'utf-16-le' and chardet_encoding in ('utf16le', 'utf16'):
                score += 25.0
            elif enc == 'utf-16-be' and chardet_encoding == 'utf16be':
                score += 25.0
        scored.append({'encoding': enc, 'score': round(score, 3), 'detail': detail})

    scored.sort(key=lambda x: x['score'], reverse=True)
    info['candidates'] = scored

    if info['strict_utf8_ok'] and (not scored or scored[0]['encoding'] == 'utf-8' or scored[0]['score'] < 30):
        info['detected'] = 'utf-8'
        info['is_utf8'] = True
        info['confidence'] = min(1.0, max(0.5, (scored[0]['score'] if scored else 50.0) / 200.0))
        return info

    if scored:
        best = scored[0]
        info['detected'] = best['encoding']
        info['is_utf8'] = best['encoding'] in ('utf-8', 'utf-8-sig')
        info['confidence'] = min(1.0, max(0.1, best['score'] / 300.0))
    else:
        info['detected'] = 'utf-8'
        info['is_utf8'] = True
        info['confidence'] = 0.0

    return info


def _count_line_endings(raw_data, encoding):
    """统计 LF / CRLF / CR；UTF-16 按双字节换行处理。

    使用 bytes.count 而非逐字节遍历，速度提升约 55 倍
    （逐字节 while 循环是体检性能瓶颈之一）。
    """
    enc = (encoding or '').lower()

    if enc.startswith('utf-16-le'):
        # LE：低字节在前。CRLF 为 0D 00 0A 00
        crlf = raw_data.count(b'\x0d\x00\x0a\x00')
        cr = raw_data.count(b'\x0d\x00') - crlf
        lf = raw_data.count(b'\x0a\x00') - crlf
    elif enc.startswith('utf-16-be'):
        # BE：高字节在前。CRLF 为 00 0D 00 0A
        crlf = raw_data.count(b'\x00\x0d\x00\x0a')
        cr = raw_data.count(b'\x00\x0d') - crlf
        lf = raw_data.count(b'\x00\x0a') - crlf
    else:
        crlf = raw_data.count(b'\x0d\x0a')
        lf = raw_data.count(b'\x0a') - crlf
        cr = raw_data.count(b'\x0d') - crlf

    types = []
    if lf:
        types.append('LF')
    if crlf:
        types.append('CRLF')
    if cr:
        types.append('CR')
    is_mixed = len(types) > 1

    if is_mixed:
        line_endings = 'mixed'
    elif types:
        line_endings = types[0]
    else:
        line_endings = 'unknown'

    if enc.startswith('utf-16-le'):
        missing_final_newline = not raw_data.endswith((b'\x0a\x00', b'\x0d\x00'))
    elif enc.startswith('utf-16-be'):
        missing_final_newline = not raw_data.endswith((b'\x00\x0a', b'\x00\x0d'))
    else:
        missing_final_newline = not raw_data.endswith((b'\x0a', b'\x0d'))

    return {
        'lf': lf,
        'crlf': crlf,
        'cr': cr,
        'types': types,
        'is_mixed': is_mixed,
        'line_endings': line_endings,
        'missing_final_newline': missing_final_newline,
        'unicode_separators': 0,
    }


def _issue(category, level, message, **extra):
    item = {
        'category': category,
        'type': category,
        'level': level,
        'message': message,
    }
    item.update(extra)
    return item


def _count_fullwidth(content):
    letters = FULLWIDTH_LETTER_RE.findall(content)
    digits = FULLWIDTH_DIGIT_RE.findall(content)
    spaces = FULLWIDTH_SPACE_RE.findall(content)
    common_punct = FULLWIDTH_COMMON_PUNCT_RE.findall(content)
    symbols = FULLWIDTH_SYMBOL_RE.findall(content)

    examples = []
    for group in (letters, digits, spaces, symbols, common_punct):
        for ch in group:
            if ch not in examples:
                examples.append(ch)
            if len(examples) >= 12:
                break
        if len(examples) >= 12:
            break

    # 全角空格(U+3000)是中文 TXT 常见的段首缩进，属于正常排版，不计为问题
    suspicious_total = len(letters) + len(digits) + len(symbols)
    return {
        'total': suspicious_total,
        'all_total': suspicious_total + len(spaces) + len(common_punct),
        'letters': len(letters),
        'digits': len(digits),
        'spaces': len(spaces),
        'symbols': len(symbols),
        'common_punctuation': len(common_punct),
        'examples': examples,
    }


def _convert_fullwidth_text(text):
    """全角转半角：处理字母/数字/空格/非常用标点，保留中文常用标点。"""
    preserve = set('，。！？；：\u201c\u201d\u2018\u2019（）《》【】、…—')
    translation = {}
    for code in range(0xFF01, 0xFF5F):
        ch = chr(code)
        if ch in preserve:
            continue
        translation[code] = chr(code - 0xFEE0)
    translation[ord('\u3000')] = ' '
    return text.translate(translation)


def check_txt_health(file_path):
    """检测 TXT 文件的编码、换行符和真正的乱码问题。

    只报告会影响阅读的问题：编码错误、乱码、异常控制字符、混合换行符。
    已移除纯装饰性检测（超长行/空行统计、行尾空白、末尾换行、Unicode 行分隔符）
    以及误报率高的全角字符告警。
    """
    result = {
        'file_path': file_path,
        'filename': os.path.basename(file_path),
        'issues': [],
        'encoding': None,
        'encoding_info': None,
        'has_bom': False,
        'line_endings': None,
        'line_ending_info': None,
        'total_lines': 0,
        'empty_lines': 0,
        'suspicious_chars': [],
        'fullwidth': {},
        'structure': {},
        'trailing_whitespace': {'count': 0, 'total_lines': 0},
        'file_size': 0,
        'is_readable': True,
        'error': None,
        'score': 100,
    }

    try:
        if not os.path.exists(file_path):
            result['is_readable'] = False
            result['error'] = '文件不存在'
            return result

        if not os.path.isfile(file_path):
            result['is_readable'] = False
            result['error'] = '不是有效文件'
            return result

        result['file_size'] = os.path.getsize(file_path)

        with open(file_path, 'rb') as f:
            raw_data = f.read()

        encoding_info = _detect_text_encoding(raw_data)
        encoding = encoding_info['detected']
        result['encoding_info'] = encoding_info
        result['encoding'] = encoding
        result['has_bom'] = encoding_info['has_bom']

        line_info = _count_line_endings(raw_data, encoding)
        result['line_ending_info'] = line_info
        result['line_endings'] = line_info['line_endings']

        content = None
        try:
            if encoding_info['bom_type'] == 'utf-16-le':
                content = raw_data[2:].decode('utf-16-le')
            elif encoding_info['bom_type'] == 'utf-16-be':
                content = raw_data[2:].decode('utf-16-be')
            else:
                content = raw_data.decode(encoding)
        except UnicodeDecodeError:
            content = raw_data.decode(encoding, errors='replace')
            result['issues'].append(_issue(
                'encoding', 'error',
                f'文件按 {encoding} 解码时出现非法字符，已使用替换模式读取'
            ))

        if content.startswith('\ufeff'):
            content = content[1:]

        # 行数只做粗略统计（content.count 比 split 全量建列表快得多）
        total_lines = content.count('\n') + content.count('\r') + 1
        result['total_lines'] = total_lines

        if not encoding_info['is_utf8']:
            result['issues'].append(_issue(
                'encoding', 'warning',
                f'文件不是 UTF-8 编码，检测到 {encoding}，建议转换为 UTF-8'
            ))
        if encoding_info['has_bom']:
            result['issues'].append(_issue(
                'encoding', 'info',
                f'文件包含 {encoding_info["bom_type"]} BOM 头'
            ))

        # 换行符：只报真正需要修的（混合 / 旧 Mac CR），CRLF 与末尾换行属正常，不告警
        if line_info['is_mixed']:
            result['issues'].append(_issue(
                'line_endings', 'warning',
                f'混合换行符：LF {line_info["lf"]} 个，CRLF {line_info["crlf"]} 个，CR {line_info["cr"]} 个'
            ))
        elif line_info['cr'] > 0:
            result['issues'].append(_issue(
                'line_endings', 'warning',
                f'使用了旧 Mac 换行符 CR（{line_info["cr"]} 个），建议统一为 LF'
            ))

        # 单次扫描统计零宽/控制/空字符/替换字符/私用区字符
        scan_counter = Counter(SUSPICIOUS_SCAN_RE.findall(content))

        zero_width_names = {
            '\u200b': '零宽空格',
            '\u200c': '零宽非连接符',
            '\u200d': '零宽连接符',
            '\ufeff': '零宽不换行空格(BOM残留)',
        }

        null_count = scan_counter.get('\x00', 0)
        if null_count:
            result['suspicious_chars'].append({
                'name': '空字符',
                'code': 'NULL (0x00)',
                'count': null_count,
                'severity': 'error',
                'description': '文件中的空白填充字符，可能导致阅读器显示异常',
                'suggestion': '选择清理可疑字符修复'
            })

        replacement_count = scan_counter.get('\ufffd', 0)
        if replacement_count:
            result['suspicious_chars'].append({
                'name': '乱码替换字符',
                'code': 'U+FFFD',
                'count': replacement_count,
                'severity': 'error',
                'description': '文件解码失败产生的替换符号，通常是编码不匹配导致',
                'suggestion': '尝试用正确编码重新打开，或选择转换为 UTF-8 修复'
            })

        control_total = sum(
            n for c, n in scan_counter.items()
            if len(c) == 1 and ord(c) < 0x20 and c not in ('\t', '\n', '\r')
        )
        if control_total:
            codes = ', '.join(
                '0x%02X' % ord(c) for c in scan_counter
                if len(c) == 1 and ord(c) < 0x20 and c not in ('\t', '\n', '\r')
            )
            result['suspicious_chars'].append({
                'name': '不可见控制字符',
                'code': codes,
                'count': control_total,
                'severity': 'warning',
                'description': '文件中的格式控制符号（如换页符、退格符等），可能造成排版错乱',
                'suggestion': '选择清理可疑字符修复'
            })

        zw_names = {
            '\u200b': '零宽空格', '\u200c': '零宽非连接符',
            '\u200d': '零宽连接符', '\ufeff': '零宽不换行空格(BOM残留)',
        }
        zw_total = 0
        zw_parts = []
        for c in ('\u200b', '\u200c', '\u200d', '\ufeff'):
            n = scan_counter.get(c, 0)
            if n:
                zw_total += n
                zw_parts.append('%s\u00d7%d' % (zw_names[c], n))
        if zw_total:
            result['suspicious_chars'].append({
                'name': '零宽隐形字符',
                'code': ', '.join(zw_parts),
                'count': zw_total,
                'severity': 'warning',
                'description': '肉眼不可见的字符，会干扰搜索/复制，通常是复制粘贴引入',
                'suggestion': '选择清理可疑字符修复'
            })

        # 双重编码文件常被误判成 GBK/BIG5，按该编码解码会让乱码特征消失。
        # 此处用 UTF-8 容错解码再判一次，避免漏报。
        if not MOJIBAKE_RE.findall(content):
            try:
                alt = raw_data.decode('utf-8', errors='ignore')
            except Exception:
                alt = ''
            if MOJIBAKE_RE.findall(alt):
                content = alt
                result['issues'].append(_issue(
                    'encoding', 'warning',
                    '文件疑似被错误转码（双重编码），已按 UTF-8 重新读取以定位乱码'
                ))

        mojibake_matches = MOJIBAKE_RE.findall(content)
        if mojibake_matches:
            result['suspicious_chars'].append({
                'name': '典型乱码',
                'code': '、'.join(mojibake_matches[:5]),
                'count': len(mojibake_matches),
                'severity': 'error',
                'description': '检测到锟斤拷、烫烫烫等常见编码转换乱码',
                'suggestion': '尝试用正确编码重新打开；如无法恢复，可能需要原始文件'
            })

        # 评分：只对影响阅读的问题扣分，装饰性问题不参与计分
        score = 100
        has_encoding_error = any(
            i.get('level') == 'error' and i.get('category') == 'encoding'
            for i in result['issues']
        )
        if has_encoding_error:
            score -= 40
        elif not encoding_info['is_utf8']:
            score -= 15

        sev = {s.get('name'): s.get('severity') for s in result['suspicious_chars']}
        if sev.get('典型乱码') == 'error':
            score -= 30
        if sev.get('乱码替换字符') == 'error':
            score -= 30
        if sev.get('空字符') == 'error':
            score -= 30
        if sev.get('不可见控制字符'):
            score -= 5
        if sev.get('零宽隐形字符'):
            score -= 5

        if line_info['is_mixed'] or line_info['cr'] > 0:
            score -= 10

        result['score'] = max(0, min(100, score))

    except Exception as e:
        result['is_readable'] = False
        result['error'] = str(e)
        result['issues'].append(_issue('read_error', 'error', '读取失败：' + str(e)))
        result['score'] = 0

    return result


def fix_txt_file(file_path, fixes=None, create_backup=True):
    """修复 TXT 文件：编码、BOM、换行符、全角字符、可疑字符、行尾空白。"""
    if fixes is None:
        fix_set = {'encoding', 'bom', 'line_endings', 'suspicious_chars'}
    elif isinstance(fixes, dict):
        fix_set = set(fixes.keys())
        if fixes.get('line_endings'):
            fix_set.add('line_endings')
        if fixes.get('normalize_fullwidth'):
            fix_set.add('fullwidth')
    else:
        fix_set = set(fixes or [])

    result = {
        'success': False,
        'message': '',
        'backup_path': None,
        'changes': [],
        'source_encoding': None,
    }

    try:
        if not os.path.exists(file_path):
            result['message'] = '文件不存在'
            return result

        if create_backup:
            backup_path = file_path + '.backup_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            import shutil
            shutil.copy2(file_path, backup_path)
            result['backup_path'] = backup_path
            result['changes'].append('已创建备份：' + os.path.basename(backup_path))

        with open(file_path, 'rb') as f:
            raw_data = f.read()

        original_size = len(raw_data)
        enc_info = _detect_text_encoding(raw_data)
        source_encoding = enc_info['detected']
        result['source_encoding'] = source_encoding

        content = None
        try:
            if enc_info['bom_type'] == 'utf-16-le':
                content = raw_data[2:].decode('utf-16-le')
            elif enc_info['bom_type'] == 'utf-16-be':
                content = raw_data[2:].decode('utf-16-be')
            else:
                content = raw_data.decode(source_encoding)
        except UnicodeDecodeError:
            content = raw_data.decode(source_encoding, errors='replace')
            result['changes'].append('使用容错模式解码')

        if content.startswith('\ufeff'):
            content = content[1:]

        if ('bom' in fix_set or 'encoding' in fix_set) and enc_info['has_bom']:
            result['changes'].append('移除 BOM 头')

        if 'suspicious_chars' in fix_set or 'suspicious' in fix_set:
            original_content = content
            content = ZERO_WIDTH_RE.sub('', content)
            content = content.replace('\x00', '')
            if '\ufffd' in content:
                content = content.replace('\ufffd', '')
                result['changes'].append('移除替换字符')
            # 清理不可见控制字符（如 0x03 ETX）。
            # 保留 \t \n \r，它们是正常的制表符与换行符。
            control_before = len(CONTROL_RE.findall(content))
            if control_before:
                content = CONTROL_RE.sub('', content)
                result['changes'].append('移除 %d 个不可见控制字符' % control_before)
            # 清理私用区字符（常见于字体嵌入残留）
            private_before = len(PRIVATE_USE_RE.findall(content))
            if private_before:
                content = PRIVATE_USE_RE.sub('', content)
                result['changes'].append('移除 %d 个私用区字符' % private_before)
            if content != original_content:
                result['changes'].append('清理零宽/空字符等可疑字符')

        if 'fullwidth' in fix_set or 'normalize_fullwidth' in fix_set:
            original_content = content
            content = _convert_fullwidth_text(content)
            if content != original_content:
                result['changes'].append('全角字母/数字/空格/符号转为半角')

        if 'line_endings' in fix_set:
            original_content = content
            content = content.replace('\r\n', '\n').replace('\r', '\n')
            if content != original_content:
                result['changes'].append('换行符统一为 LF')

        if 'trailing_whitespace' in fix_set:
            original_content = content
            lines = content.split('\n')
            content = '\n'.join(line.rstrip() for line in lines)
            if content != original_content:
                result['changes'].append('移除行尾空白')

        # 勾选 encoding/bom 时写回 UTF-8；否则尽量保留原编码
        if 'encoding' in fix_set or 'bom' in fix_set:
            write_encoding = 'utf-8'
        else:
            write_encoding = source_encoding
            if write_encoding == 'utf-8-sig':
                write_encoding = 'utf-8-sig'
            elif write_encoding not in ('utf-8', 'gbk', 'gb18030', 'big5', 'ascii', 'latin-1'):
                write_encoding = 'utf-8'

        tmp_path = file_path + '.tmp'
        with open(tmp_path, 'w', encoding=write_encoding, newline='\n') as f:
            f.write(content)
        os.replace(tmp_path, file_path)

        new_size = os.path.getsize(file_path)
        result['success'] = True
        result['message'] = '修复完成，文件大小：%d -> %d 字节' % (original_size, new_size)
        if write_encoding == 'utf-8' and source_encoding not in ('utf-8', 'utf-8-sig'):
            result['changes'].append('编码转换为 UTF-8')
        elif write_encoding == 'utf-8-sig':
            result['changes'].append('保留 UTF-8 BOM')
        return result

    except Exception as e:
        try:
            if os.path.exists(file_path + '.tmp'):
                os.remove(file_path + '.tmp')
        except Exception:
            pass
        result['message'] = '修复失败：' + str(e)
        return result


def _resolve_novel_path(file_path):
    """将路径解析到 NOVEL_DIR 内；非法或越界返回 None。"""
    if not file_path:
        return None
    try:
        raw = str(file_path)
        if os.path.isabs(raw):
            candidate = os.path.realpath(raw)
        else:
            candidate = safe_join(NOVEL_DIR, safe_basename(raw))
        return candidate if is_path_within(NOVEL_DIR, candidate) else None
    except (TypeError, ValueError):
        return None


def _resolve_txt_path(file_path):
    """解析并确保是 NOVEL_DIR 内的 .txt 文件。"""
    candidate = _resolve_novel_path(file_path)
    if candidate and os.path.splitext(candidate)[1].lower() == '.txt':
        return candidate
    return None


@app.route('/api/txt/health_check', methods=['POST'])
def api_txt_health_check():
    """检测单个 TXT 文件健康状态"""
    data = request.get_json(silent=True) or {}
    file_path = _resolve_txt_path(data.get('file_path', ''))

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不合法或不是 TXT 文件'})

    result = check_txt_health(file_path)
    return jsonify({'success': True, 'result': result})


def run_txt_health_scan_all_task(task_id):
    """后台执行全量 TXT 健康检查。"""
    lock = _CrossProcessLock(TXT_HEALTH_SCAN_LOCK_FILE)
    lock.acquire()
    try:
        novels = [
            n for n in list(novel_data)
            if n.get('file_path') and os.path.exists(n.get('file_path'))
        ]
        total = len(novels)
        update_background_task(task_id, total=total, current=0, message='正在检测 TXT 文件...')

        results = []
        checked = 0
        problem_count = 0

        for novel in novels:
            file_path = novel.get('file_path')
            result = check_txt_health(file_path)
            checked += 1

            if result['issues'] or result['suspicious_chars'] or not result['is_readable']:
                problem_count += 1
                results.append({
                    'title': novel.get('title', os.path.basename(file_path)),
                    'file_path': file_path,
                    'filename': result['filename'],
                    'encoding': result['encoding'],
                    'has_bom': result['has_bom'],
                    'line_endings': result['line_endings'],
                    'total_lines': result['total_lines'],
                    'file_size': result['file_size'],
                    'issues': result['issues'],
                    'suspicious_chars': result['suspicious_chars'],
                    'is_readable': result['is_readable'],
                    'error': result['error']
                })

            update_background_task(
                task_id,
                current=checked,
                message=f'检测中：{os.path.basename(file_path)[:30]}'
            )

        def severity_score(item):
            score = 0
            for issue in item.get('issues', []):
                if issue['level'] == 'error':
                    score += 10
                elif issue['level'] == 'warning':
                    score += 5
            for sc in item.get('suspicious_chars', []):
                if sc['severity'] == 'error':
                    score += 20
                else:
                    score += 5
            return score

        results.sort(key=severity_score, reverse=True)
        finish_background_task(task_id, result={
            'success': True,
            'total_checked': checked,
            'problem_count': problem_count,
            'results': results
        })
        logger.info(
            f"TXT 体检完成 - 检查 {checked} 个文件, 发现问题 {problem_count} 个"
        )
    except Exception as e:
        traceback.print_exc()
        finish_background_task(task_id, error=e)
    finally:
        lock.release()


@app.route('/api/txt/health_scan_all', methods=['POST'])
def api_txt_health_scan_all():
    # 同一时间只允许一个扫描任务，避免重复点击导致并发读取同一批文件
    existing = find_running_task('txt_health_scan_all')
    if existing:
        return jsonify({
            'success': False,
            'duplicate': True,
            'task_id': existing,
            'message': '扫描正在进行中，请勿重复点击',
        })

    task_id = create_background_task('txt_health_scan_all', message='准备扫描 TXT 文件...')
    threading.Thread(
        target=run_txt_health_scan_all_task,
        args=(task_id,),
        daemon=True
    ).start()
    return jsonify({'success': True, 'task_id': task_id})


@app.route('/api/txt/fix', methods=['POST'])
def api_txt_fix():
    data = request.get_json(silent=True) or {}
    file_path = _resolve_txt_path(data.get('file_path', ''))
    fixes = data.get('fixes') or ['encoding', 'bom', 'line_endings', 'suspicious_chars']
    create_backup = data.get('create_backup', True)

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不合法或不是 TXT 文件'})

    result = fix_txt_file(file_path, fixes, create_backup)
    return jsonify(result)


@app.route('/api/txt/fix_all', methods=['POST'])
def api_txt_fix_all():
    data = request.get_json(silent=True) or {}
    raw_paths = data.get('file_paths', [])
    if not isinstance(raw_paths, list):
        raw_paths = []
    fixes = data.get('fixes') or ['encoding', 'bom', 'line_endings', 'suspicious_chars']
    create_backup = data.get('create_backup', True)

    if not raw_paths:
        return jsonify({'success': False, 'message': '未指定要修复的文件'})

    results = []
    success_count = 0
    fail_count = 0

    for raw_path in raw_paths:
        file_path = _resolve_txt_path(raw_path)
        if not file_path:
            results.append({
                'file_path': str(raw_path),
                'filename': safe_basename(raw_path),
                'success': False,
                'message': '文件路径不合法或不是 TXT 文件',
                'changes': [],
                'backup_path': None
            })
            fail_count += 1
            continue

        result = fix_txt_file(file_path, fixes, create_backup)
        results.append({
            'file_path': file_path,
            'filename': os.path.basename(file_path),
            'success': result['success'],
            'message': result['message'],
            'changes': result.get('changes', []),
            'backup_path': result.get('backup_path')
        })

        if result['success']:
            success_count += 1
        else:
            fail_count += 1

    return jsonify({
        'success': True,
        'total': len(raw_paths),
        'success_count': success_count,
        'fail_count': fail_count,
        'results': results
    })


@app.route('/api/txt/backup_list', methods=['POST'])
def api_txt_backup_list():
    """获取文件的备份列表"""
    data = request.get_json(silent=True) or {}
    file_path = _resolve_txt_path(data.get('file_path', ''))

    if not file_path:
        return jsonify({'success': False, 'message': '文件路径不合法或不是 TXT 文件'})

    backups = []
    dir_path = os.path.dirname(file_path)
    base_name = os.path.basename(file_path)

    try:
        for f in os.listdir(dir_path):
            if f.startswith(base_name + '.backup_'):
                backup_path = os.path.join(dir_path, f)
                if not is_path_within(NOVEL_DIR, backup_path):
                    continue
                stat = os.stat(backup_path)
                backups.append({
                    'filename': f,
                    'path': backup_path,
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })

        backups.sort(key=lambda x: x['created'], reverse=True)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

    return jsonify({'success': True, 'backups': backups})


@app.route('/api/txt/restore_backup', methods=['POST'])
def api_txt_restore_backup():
    """从备份恢复文件"""
    data = request.get_json(silent=True) or {}
    backup_path = _resolve_novel_path(data.get('backup_path', ''))

    if not backup_path or not os.path.isfile(backup_path) or '.backup_' not in os.path.basename(backup_path):
        return jsonify({'success': False, 'message': '备份文件不存在或路径不合法'})

    original_path = os.path.realpath(backup_path.rsplit('.backup_', 1)[0])
    if not is_path_within(NOVEL_DIR, original_path) or os.path.splitext(original_path)[1].lower() != '.txt':
        return jsonify({'success': False, 'message': '原始文件路径不合法'})

    try:
        import shutil
        shutil.copy2(backup_path, original_path)
        return jsonify({'success': True, 'message': '恢复成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/txt_health')
def txt_health_page():
    """TXT 体检页面"""
    return render_template('txt_health.html', novel_data=novel_data)

# ===================== 托盘 =====================
import threading
import webbrowser
import socket
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw


single_instance_socket = None


def get_app_url():
    """根据当前配置生成访问地址（0.0.0.0 时仍使用 127.0.0.1 打开浏览器）。"""
    host = str(CONFIG.get('app_host', '127.0.0.1') or '127.0.0.1')
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1'
    try:
        port = int(CONFIG.get('app_port', 5000))
    except (TypeError, ValueError):
        port = 5000
    return f"http://{host}:{port}"


def is_running():
    if CONFIG.get('debug_mode', False):
        return False
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        res = s.connect_ex(('127.0.0.1', 49999))
        s.close()
        return res == 0
    except:
        return False


def single_instance():
    global single_instance_socket
    
    if CONFIG.get('debug_mode', False):
        print("🔧 调试模式：跳过单实例检测")
        return
    
    if is_running():
        webbrowser.open(get_app_url())
        os._exit(0)
    
    def lock():
        global single_instance_socket
        try:
            single_instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            single_instance_socket.bind(('127.0.0.1', 49999))
            single_instance_socket.listen(1)
        except:
            pass
    
    threading.Thread(target=lock, daemon=True).start()


def create_icon():
    icon_path = os.path.join(os.path.dirname(__file__), "static", "images/novel-icon.png")
    try:
        return Image.open(icon_path)
    except:
        img = Image.new("RGB", (64, 64), (20, 30, 40))
        draw = ImageDraw.Draw(img)
        draw.ellipse((16, 16, 48, 48), fill=(66, 133, 244))
        return img


def open_web():
    webbrowser.open(get_app_url())


def open_novel_directory():
    try:
        novel_dir = CONFIG.get('novel_dir', '')
        if novel_dir and os.path.exists(novel_dir):
            if sys.platform == 'win32':
                os.startfile(novel_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', novel_dir])
            else:
                subprocess.Popen(['xdg-open', novel_dir])
            print(f"✅ 已打开小说目录: {novel_dir}")
        else:
            print(f"❌ 小说目录不存在: {novel_dir}")
    except Exception as e:
        print(f"❌ 打开小说目录失败: {e}")


def open_app_directory():
    try:
        app_dir = os.path.dirname(__file__)
        if os.path.exists(app_dir):
            if sys.platform == 'win32':
                os.startfile(app_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', app_dir])
            else:
                subprocess.Popen(['xdg-open', app_dir])
            print(f"✅ 已打开程序目录: {app_dir}")
        else:
            print(f"❌ 程序目录不存在: {app_dir}")
    except Exception as e:
        print(f"❌ 打开程序目录失败: {e}")


def open_emoji_editor():
    try:
        script_path = os.path.join(os.path.dirname(__file__), "emoji_editor_v2.py")
        mapping_path = os.path.join(os.path.dirname(__file__), "data", "image_mapping.json")
        emojis_folder = os.path.join(os.path.dirname(__file__), "static", "emojis")
        
        if os.path.exists(script_path):
            subprocess.Popen(
                [sys.executable, script_path, mapping_path, emojis_folder],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
        else:
            bat_path = os.path.join(os.path.dirname(__file__), "启动表情映射编辑器.bat")
            if os.path.exists(bat_path):
                subprocess.Popen(
                    [bat_path],
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                    shell=True
                )
            else:
                print(f"❌ 找不到 emoji 编辑器: {script_path}")
    except Exception as e:
        print(f"❌ 启动 emoji 编辑器失败: {e}")


def quit_app(icon, item):
    icon.stop()
    os._exit(0)


def restart_app(icon, item):
    icon.stop()
    subprocess.Popen([sys.executable] + sys.argv)
    os._exit(0)


def run_tray():
    if CONFIG.get('debug_mode', False):
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            print("🔧 调试模式：子进程，不启动托盘")
            return
        print("🔧 调试模式：主进程，启动托盘")
    
    single_instance()

    def make_callback(callback):
        def wrapper(icon, item):
            return callback(icon, item)
        return wrapper
    
    def make_simple_callback(callback):
        def wrapper(icon, item):
            return callback()
        return wrapper

    menu = Menu(
        MenuItem("📖 打开小说管理", make_simple_callback(open_web), default=True),
        Menu.SEPARATOR,
        MenuItem("📁 打开小说目录", make_simple_callback(open_novel_directory)),
        MenuItem("📂 打开程序目录", make_simple_callback(open_app_directory)),
        Menu.SEPARATOR,
        MenuItem("😊 打开emoji编辑器", make_simple_callback(open_emoji_editor)),
        Menu.SEPARATOR,
        MenuItem("🔄 重启程序", make_callback(restart_app)),
        MenuItem("❌ 退出程序", make_callback(quit_app))
    )

    icon = Icon(
        name="小说管理器",
        icon=create_icon(),
        title="小说管理工具\n左键打开界面 | 右键显示菜单",
        menu=menu
    )

    def on_left_click(icon, item):
        open_web()
    
    def on_right_click(icon, item):
        pass
    
    icon.on_left_click = on_left_click
    icon.on_right_click = on_right_click
    
    print("\n" + "=" * 50)
    print("📌 小说管理器已启动")
    print("📌 左键单击托盘图标打开界面")
    print("📌 右键单击托盘图标显示菜单")
    print("=" * 50 + "\n")
    
    icon.run()


# ==================== 主入口 ====================
if __name__ == '__main__':
    is_reloader = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    
    print()
    cprint("╔" + "═" * 58 + "╗", 'CYAN', bold=True)
    cprint("║" + " " * 18 + "📚 小说管理系统 v2.0" + " " * 18 + "║", 'CYAN', bold=True)
    cprint("╠" + "═" * 58 + "╣", 'CYAN', bold=True)
    
    if CONFIG.get('debug_mode', False):
        cprint("║" + " 🔧 运行模式: 调试模式 (DEBUG)" + " " * 28 + "║", 'WARNING', bold=True)
    else:
        cprint("║" + " 🚀 运行模式: 生产模式 (PRODUCTION)" + " " * 24 + "║", 'GREEN', bold=True)
    
    cprint("╠" + "═" * 58 + "╣", 'CYAN', bold=True)
    cprint(f"║ 📁 小说目录: {CONFIG['novel_dir'][:40]}{'...' if len(CONFIG['novel_dir']) > 40 else ''}", 'BLUE')
    cprint(f"║ 🌐 服务地址: http://{CONFIG.get('app_host', '127.0.0.1')}:{CONFIG.get('app_port', 5000)}", 'BLUE')
    cprint(f"║ 💾 缓存文件: {CACHE_FILE}", 'BLUE')
    cprint(f"║ 📋 日志文件: {LOG_FILE}", 'BLUE')
    
    if os.path.exists(CACHE_FILE):
        cache_size = os.path.getsize(CACHE_FILE) / 1024 / 1024
        cprint(f"║ 💿 缓存大小: {cache_size:.2f} MB ({len(novel_data)} 本小说)", 'GREEN')
    else:
        cprint(f"║ 💿 缓存状态: 无缓存 (首次运行)", 'WARNING')
    
    cprint("╚" + "═" * 58 + "╝", 'CYAN', bold=True)
    print()
    
    if CONFIG.get('debug_mode', False):
        if is_reloader:
            print("🔧 调试模式：子进程启动，加载缓存...")
            check_interrupted_scan()
            load_cache()
        
        print()
        cprint("📋 详细配置信息", 'CYAN', bold=True)
        print("-" * 60)
        print(f"   小说目录: {CONFIG['novel_dir']}")
        print(f"   数据目录: {DATA_DIR}")
        print(f"   模板目录: {os.path.join(BASE_DIR, 'templates')}")
        print(f"   静态目录: {os.path.join(BASE_DIR, 'static')}")
        print(f"\n   编辑器路径: {CONFIG['editor_path']}")
        print(f"   单实例端口: 49999")
        print(f"\n   阅读设置:")
        print(f"     默认主题: {CONFIG.get('theme', 'auto')}")
        print(f"     字体大小: {CONFIG.get('font_size', 16)}px")
        print(f"     行高: {CONFIG.get('line_height', 1.8)}")
        print(f"     每页字数: {CONFIG.get('words_per_page', 8000)}")
        print(f"     每页小说数: {CONFIG.get('per_page', 100)}")
        print(f"\n   标签设置:")
        print(f"     自动标签: {'✅' if CONFIG.get('auto_tag_enabled', True) else '❌'}")
        print(f"     派生标签: {'✅' if CONFIG.get('enable_derived_tags', True) else '❌'}")
        print(f"     关键词库: {len(TAG_KEYWORDS)} 个")
        print(f"     别名映射: {len(TAG_ALIASES)} 组")
        print(f"     派生规则: {len(TAG_IMPLICATIONS)} 条")
        print(f"\n   扫描设置:")
        print(f"     启动自动扫描: {'✅' if CONFIG.get('auto_scan_on_start', True) else '❌'}")
        print(f"     扫描间隔: {CONFIG.get('scan_interval_hours', 0)} 小时")
        print(f"     最大文件: {CONFIG.get('max_file_size_mb', 100)} MB")
        print(f"     扫描子目录: {'✅' if CONFIG.get('scan_subdirectories', False) else '❌'}")
        print("\n" + "-" * 60)
        
        if not is_reloader:
            threading.Thread(target=run_tray, daemon=True).start()
        
        cprint("🚀 启动 Flask 服务器...", 'GREEN', bold=True)
        debug_host = str(CONFIG.get('app_host', '127.0.0.1') or '127.0.0.1')
        if debug_host not in ('127.0.0.1', 'localhost', '::1'):
            print("⚠️ 调试模式存在安全风险，已强制绑定 127.0.0.1")
            debug_host = '127.0.0.1'
        logger.info(
            f"程序启动(调试模式) - 服务 {debug_host}:{CONFIG.get('app_port', 5000)}, "
            f"小说目录: {CONFIG.get('novel_dir')}"
        )
        app.run(debug=True, host=debug_host, port=int(CONFIG.get('app_port', 5000)))
        sys.exit(0)
    
    # 必须在任何自动扫描启动之前：判断上次扫描是否被中断
    check_interrupted_scan()

    threading.Thread(target=run_tray, daemon=True).start()

    if not load_cache() and CONFIG.get('auto_scan_on_start', True):
        cprint("🔄 首次运行，开始后台扫描...", 'WARNING')
        thread = threading.Thread(target=scan_novel_files_background, args=(True,))
        thread.daemon = True
        thread.start()
    else:
        cprint(f"✅ 已加载 {len(novel_data)} 本小说缓存", 'GREEN')
        if CONFIG.get('auto_scan_on_start', True):
            cprint("🔍 后台检查文件更新...", 'BLUE')

        # ===== 启动时预加载最近阅读的书（可在配置页关闭或调整数量）=====
        # 桌面版内存充裕：开机后先把「你上次在读的书」的章节解析好，
        # 点进去就是现成的，不用等它读文件、切章节。
        preload_enabled = CONFIG.get('preload_recent_enabled', True)
        try:
            preload_count = int(CONFIG.get('preload_recent_count', 5) or 0)
        except (TypeError, ValueError):
            preload_count = 5
        preload_count = max(0, min(20, preload_count))

        def preload_recent():
            time.sleep(3)   # 让启动流程与后台扫描先跑起来，避免抢 IO
            try:
                records = load_reading_records()
                recent = sorted(
                    records.values(),
                    key=lambda r: r.get('timestamp', 0),
                    reverse=True
                )[:preload_count]
                loaded = 0
                for r in recent:
                    fp = r.get('file_path')
                    if not fp or not os.path.exists(fp) or fp in chapter_cache:
                        continue
                    parse_novel_details(fp)
                    loaded += 1
                if loaded:
                    print(f"⚡ 已预加载 {loaded} 本最近阅读书籍的章节")
            except Exception as e:
                print(f"⚠️ 预加载最近阅读失败：{e}")

        if preload_enabled and preload_count > 0:
            threading.Thread(target=preload_recent, daemon=True).start()
    
    def check_updates():
        time.sleep(2)
        if novel_data and CONFIG.get('auto_scan_on_start', True):
            scan_novel_files_background(full_scan=False)
    
    update_thread = threading.Thread(target=check_updates)
    update_thread.daemon = True
    update_thread.start()
    
    cprint("🚀 启动 Flask 服务器...", 'GREEN', bold=True)
    logger.info(
        f"程序启动 - 服务 {CONFIG.get('app_host', '127.0.0.1')}:{CONFIG.get('app_port', 5000)}, "
        f"小说目录: {CONFIG.get('novel_dir')}, 调试模式: {DEBUG_MODE}"
    )
    app.run(debug=False, 
            host=CONFIG.get('app_host', '127.0.0.1'), 
            port=CONFIG.get('app_port', 5000))
