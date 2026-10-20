// config.js - 精简版，删除重复的监听

// ============================================
// 浏览文件夹
// ============================================
function browseFolder(inputId) {
    const input = document.createElement('input');
    input.type = 'file';
    input.webkitdirectory = true;
    input.directory = true;
    input.onchange = function (e) {
        if (e.target.files.length > 0) {
            showNotification('请手动输入完整路径，浏览器限制无法获取完整路径', 'info');
        }
    };
    input.click();
}

// 浏览文件
function browseFile(inputId) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.exe';
    input.onchange = function (e) {
        if (e.target.files.length > 0) {
            showNotification('请手动输入完整路径，浏览器限制无法获取', 'info');
        }
    };
    input.click();
}

// ============================================
// 主题切换（实时预览，不落盘；保存由 saveAllConfig 统一处理）
// 修复：config.html 的 theme select onchange="onThemeChange()" 此前无定义，
// 切换主题会静默抛 ReferenceError，只能等保存/重载才生效
// ============================================
function onThemeChange() {
    var t = document.getElementById('theme').value;
    if (t === 'auto') {
        // auto 按当前系统偏好解析（与 common.js 的 getSystemTheme 同逻辑）
        t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    if (typeof applyTheme === 'function') {
        applyTheme(t);
    }
}

// ============================================
// 保存配置
// ============================================
async function saveAllConfig() {
    console.log('🔍 saveAllConfig 被调用');
    showLoading(true);

    const formData = {
        novel_dir: document.getElementById('novel_dir').value,
        editor_path: document.getElementById('editor_path').value,
        exclude_patterns: parseCommaString(document.getElementById('exclude_patterns').value),
        app_host: document.getElementById('app_host').value,
        app_port: parseInt(document.getElementById('app_port').value),
        font_size: parseInt(document.getElementById('font_size').value),
        line_height: parseFloat(document.getElementById('line_height').value),
        theme: document.getElementById('theme').value,
        auto_save_progress: document.getElementById('auto_save_progress').checked,
        show_word_count: document.getElementById('show_word_count').checked,
        scan_interval_hours: parseInt(document.getElementById('scan_interval_hours').value),
        max_file_size_mb: parseInt(document.getElementById('max_file_size_mb').value),
        scan_subdirectories: document.getElementById('scan_subdirectories').checked,
        per_page: parseInt(document.getElementById('per_page').value),
        words_per_page: parseInt(document.getElementById('words_per_page').value),
        max_tags_display: parseInt(document.getElementById('max_tags_display').value),
        date_format: document.getElementById('date_format').value,
        default_sort_by: document.getElementById('default_sort_by')?.value ?? 'title',
        default_sort_order: document.getElementById('default_sort_order')?.value ?? 'asc',
        auto_scan_on_start: document.getElementById('auto_scan_on_start').checked,
        auto_backup_enabled: document.getElementById('auto_backup_enabled').checked,
        backup_interval_days: parseInt(document.getElementById('backup_interval_days').value),
        max_backups: parseInt(document.getElementById('max_backups').value),
        debug_mode: document.getElementById('debug_mode').checked,
        auto_tag_enabled: document.getElementById('auto_tag_enabled')?.checked ?? true,
        enable_derived_tags: document.getElementById('enable_derived_tags')?.checked ?? true,
        // 自定义高亮标点符号字体（空字符串 = 跟随正文）
        body_font_family: document.getElementById('body_font_family')?.value ?? '',
        title_font_family: document.getElementById('title_font_family')?.value ?? '',
        double_quote_font_family: document.getElementById('double_quote_font_family')?.value ?? '',
        single_quote_font_family: document.getElementById('single_quote_font_family')?.value ?? '',
        bracket_font_family: document.getElementById('bracket_font_family')?.value ?? '',
        square_bracket_font_family: document.getElementById('square_bracket_font_family')?.value ?? '',
        square_bracket_1_font_family: document.getElementById('square_bracket_1_font_family')?.value ?? '',
        hollow_bracket_font_family: document.getElementById('hollow_bracket_font_family')?.value ?? '',
        book_font_family: document.getElementById('book_font_family')?.value ?? '',
        // 自定义高亮标点符号 加粗/斜体（从 B/I 按钮的 aria-pressed 读取）
        body_bold: document.getElementById('body_bold').getAttribute('aria-pressed') === 'true',
        body_italic: document.getElementById('body_italic').getAttribute('aria-pressed') === 'true',
        title_bold: document.getElementById('title_bold').getAttribute('aria-pressed') === 'true',
        title_italic: document.getElementById('title_italic').getAttribute('aria-pressed') === 'true',
        double_quote_bold: document.getElementById('double_quote_bold').getAttribute('aria-pressed') === 'true',
        double_quote_italic: document.getElementById('double_quote_italic').getAttribute('aria-pressed') === 'true',
        single_quote_bold: document.getElementById('single_quote_bold').getAttribute('aria-pressed') === 'true',
        single_quote_italic: document.getElementById('single_quote_italic').getAttribute('aria-pressed') === 'true',
        bracket_bold: document.getElementById('bracket_bold').getAttribute('aria-pressed') === 'true',
        bracket_italic: document.getElementById('bracket_italic').getAttribute('aria-pressed') === 'true',
        square_bracket_bold: document.getElementById('square_bracket_bold').getAttribute('aria-pressed') === 'true',
        square_bracket_italic: document.getElementById('square_bracket_italic').getAttribute('aria-pressed') === 'true',
        square_bracket_1_bold: document.getElementById('square_bracket_1_bold').getAttribute('aria-pressed') === 'true',
        square_bracket_1_italic: document.getElementById('square_bracket_1_italic').getAttribute('aria-pressed') === 'true',
        hollow_bracket_bold: document.getElementById('hollow_bracket_bold').getAttribute('aria-pressed') === 'true',
        hollow_bracket_italic: document.getElementById('hollow_bracket_italic').getAttribute('aria-pressed') === 'true',
        book_bold: document.getElementById('book_bold').getAttribute('aria-pressed') === 'true',
        book_italic: document.getElementById('book_italic').getAttribute('aria-pressed') === 'true',
        indent_paragraph: document.getElementById('indent_paragraph')?.checked || false
    };

    try {
        const response = await fetch('/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        const result = await response.json();

        if (result.success) {
            showNotification('配置已保存！点击"重载配置"生效', 'success');
            // 配置页保存后，把统一排版字段镜像到 localStorage，使阅读抽屉重开即与配置页一致。
            // config.json 是单一真相源：抽屉改动也会写回 config.json，二者双向同步（不再清除，避免误删抽屉临时覆盖）。
            try {
                localStorage.setItem('reader_font_size', String(formData.font_size != null ? formData.font_size : 24));
                localStorage.setItem('reader_line_height', String(formData.line_height != null ? formData.line_height : 1.8));
                var _scopes = ['body', 'title', 'double_quote', 'single_quote', 'bracket', 'square_bracket', 'square_bracket_1', 'hollow_bracket', 'book'];
                _scopes.forEach(function (sc) {
                    localStorage.setItem('reader_hl_' + sc + '_font', formData[sc + '_font_family'] ? formData[sc + '_font_family'] : '__default__');
                    localStorage.setItem('reader_hl_' + sc + '_bold', formData[sc + '_bold'] ? '1' : '0');
                    localStorage.setItem('reader_hl_' + sc + '_italic', formData[sc + '_italic'] ? '1' : '0');
                });
                localStorage.setItem('reader_indent_paragraph', formData.indent_paragraph ? '1' : '0');
            } catch (e) {}
        } else {
            showNotification('保存失败: ' + result.message, 'error');
        }
    } catch (error) {
        showNotification('保存失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ============================================
// 重载配置
// ============================================
async function reloadConfig() {
    showLoading(true);

    try {
        const response = await fetch('/config/reload', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showNotification('配置已重载', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('重载失败: ' + result.message, 'error');
        }
    } catch (error) {
        showNotification('重载失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ============================================
// 恢复默认配置
// ============================================
async function resetToDefault() {
    if (!confirm('确定要恢复默认配置吗？当前配置将被覆盖！')) return;

    showLoading(true);

    try {
        const response = await fetch('/config/reset', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showNotification('已恢复默认配置', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('恢复失败: ' + result.message, 'error');
        }
    } catch (error) {
        showNotification('恢复失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ============================================
// 导出/导入配置
// ============================================
function exportConfig() {
    const configData = {
        novel_dir: document.getElementById('novel_dir').value,
        editor_path: document.getElementById('editor_path').value,
        exclude_patterns: parseCommaString(document.getElementById('exclude_patterns').value),
        app_host: document.getElementById('app_host').value,
        app_port: parseInt(document.getElementById('app_port').value),
        font_size: parseInt(document.getElementById('font_size').value),
        line_height: parseFloat(document.getElementById('line_height').value),
        theme: document.getElementById('theme').value,
        auto_save_progress: document.getElementById('auto_save_progress').checked,
        show_word_count: document.getElementById('show_word_count').checked,
        scan_interval_hours: parseInt(document.getElementById('scan_interval_hours').value),
        max_file_size_mb: parseInt(document.getElementById('max_file_size_mb').value),
        scan_subdirectories: document.getElementById('scan_subdirectories').checked,
        per_page: parseInt(document.getElementById('per_page').value),
        words_per_page: parseInt(document.getElementById('words_per_page').value),
        max_tags_display: parseInt(document.getElementById('max_tags_display').value),
        date_format: document.getElementById('date_format').value,
        auto_scan_on_start: document.getElementById('auto_scan_on_start').checked,
        auto_backup_enabled: document.getElementById('auto_backup_enabled').checked,
        backup_interval_days: parseInt(document.getElementById('backup_interval_days').value),
        max_backups: parseInt(document.getElementById('max_backups').value),
        debug_mode: document.getElementById('debug_mode').checked,
    };

    const dataStr = JSON.stringify(configData, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `novel_config_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showNotification('配置已导出', 'success');
}

function importConfig() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = function (e) {
        const file = e.target.files[0];
        const reader = new FileReader();
        reader.onload = function (evt) {
            try {
                const config = JSON.parse(evt.target.result);
                document.getElementById('novel_dir').value = config.novel_dir || '';
                document.getElementById('editor_path').value = config.editor_path || '';
                document.getElementById('exclude_patterns').value = (config.exclude_patterns || []).join(', ');
                document.getElementById('app_host').value = config.app_host || '127.0.0.1';
                document.getElementById('app_port').value = config.app_port || 5000;
                document.getElementById('font_size').value = config.font_size || 16;
                document.getElementById('line_height').value = config.line_height || 1.8;
                document.getElementById('theme').value = config.theme || 'dark';
                document.getElementById('auto_save_progress').checked = config.auto_save_progress !== false;
                document.getElementById('show_word_count').checked = config.show_word_count !== false;
                document.getElementById('scan_interval_hours').value = config.scan_interval_hours || 0;
                document.getElementById('max_file_size_mb').value = config.max_file_size_mb || 100;
                document.getElementById('scan_subdirectories').checked = config.scan_subdirectories || false;
                document.getElementById('per_page').value = config.per_page || 100;
                document.getElementById('words_per_page').value = config.words_per_page || 8000;
                document.getElementById('max_tags_display').value = config.max_tags_display || 3;
                document.getElementById('date_format').value = config.date_format || 'YYYY-MM-DD';
                document.getElementById('auto_scan_on_start').checked = config.auto_scan_on_start !== false;
                document.getElementById('auto_backup_enabled').checked = config.auto_backup_enabled !== false;
                document.getElementById('backup_interval_days').value = config.backup_interval_days || 7;
                document.getElementById('max_backups').value = config.max_backups || 5;
                document.getElementById('debug_mode').checked = config.debug_mode === true;
                document.getElementById('auto_tag_enabled').checked = config.auto_tag_enabled !== false;
                document.getElementById('enable_derived_tags').checked = config.enable_derived_tags !== false;
                // 自定义高亮标点符号字体（select 设 value 即选中匹配 option）
                document.getElementById('body_font_family').value = config.body_font_family || '';
                document.getElementById('title_font_family').value = config.title_font_family || '';
                document.getElementById('double_quote_font_family').value = config.double_quote_font_family || '';
                document.getElementById('single_quote_font_family').value = config.single_quote_font_family || '';
                document.getElementById('bracket_font_family').value = config.bracket_font_family || '';
                document.getElementById('square_bracket_font_family').value = config.square_bracket_font_family || '';
                document.getElementById('square_bracket_1_font_family').value = config.square_bracket_1_font_family || '';
                document.getElementById('hollow_bracket_font_family').value = config.hollow_bracket_font_family || '';
                document.getElementById('book_font_family').value = config.book_font_family || '';
                // 自定义高亮标点符号 加粗/斜体（设置 B/I 按钮的 aria-pressed）
                document.getElementById('body_bold').setAttribute('aria-pressed', config.body_bold ? 'true' : 'false');
                document.getElementById('body_italic').setAttribute('aria-pressed', config.body_italic ? 'true' : 'false');
                document.getElementById('title_bold').setAttribute('aria-pressed', config.title_bold ? 'true' : 'false');
                document.getElementById('title_italic').setAttribute('aria-pressed', config.title_italic ? 'true' : 'false');
                document.getElementById('double_quote_bold').setAttribute('aria-pressed', config.double_quote_bold ? 'true' : 'false');
                document.getElementById('double_quote_italic').setAttribute('aria-pressed', config.double_quote_italic ? 'true' : 'false');
                document.getElementById('single_quote_bold').setAttribute('aria-pressed', config.single_quote_bold ? 'true' : 'false');
                document.getElementById('single_quote_italic').setAttribute('aria-pressed', config.single_quote_italic ? 'true' : 'false');
                document.getElementById('bracket_bold').setAttribute('aria-pressed', config.bracket_bold ? 'true' : 'false');
                document.getElementById('bracket_italic').setAttribute('aria-pressed', config.bracket_italic ? 'true' : 'false');
                document.getElementById('square_bracket_bold').setAttribute('aria-pressed', config.square_bracket_bold ? 'true' : 'false');
                document.getElementById('square_bracket_italic').setAttribute('aria-pressed', config.square_bracket_italic ? 'true' : 'false');
                document.getElementById('square_bracket_1_bold').setAttribute('aria-pressed', config.square_bracket_1_bold ? 'true' : 'false');
                document.getElementById('square_bracket_1_italic').setAttribute('aria-pressed', config.square_bracket_1_italic ? 'true' : 'false');
                document.getElementById('hollow_bracket_bold').setAttribute('aria-pressed', config.hollow_bracket_bold ? 'true' : 'false');
                document.getElementById('hollow_bracket_italic').setAttribute('aria-pressed', config.hollow_bracket_italic ? 'true' : 'false');
                document.getElementById('book_bold').setAttribute('aria-pressed', config.book_bold ? 'true' : 'false');
                document.getElementById('book_italic').setAttribute('aria-pressed', config.book_italic ? 'true' : 'false');

                showNotification('配置已导入，请保存生效', 'success');
            } catch (error) {
                showNotification('导入失败: 配置文件格式错误', 'error');
            }
        };
        reader.readAsText(file);
    };
    input.click();
}

// ============================================
// 键盘快捷键
// ============================================
document.addEventListener('keydown', function (e) {
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        saveAllConfig();
    }
    if (e.ctrlKey && e.key === 'r') {
        e.preventDefault();
        reloadConfig();
    }
});

// ============================================
// 索引管理
// ============================================
async function loadIndexStats() {
    const statsDiv = document.getElementById('indexStats');
    if (!statsDiv) return;

    try {
        const response = await fetch('/api/search/stats');
        const data = await response.json();
        if (data.doc_count !== undefined) {
            statsDiv.innerHTML = `
                <div>📚 索引文档数: <strong>${data.doc_count}</strong></div>
                <div>📁 索引目录: <code>${data.index_dir || '未知'}</code></div>
                <div>💾 索引大小: <strong>${data.index_size_mb || 0} MB</strong></div>
            `;
        } else {
            statsDiv.innerHTML = '<span>未找到索引</span>';
        }
    } catch (e) {
        statsDiv.innerHTML = '<span>获取状态失败</span>';
    }
}





// ============================================
// 页面初始化（只有一个 DOMContentLoaded 监听）
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    // 主题和轮播图由 HTML 中的脚本初始化
    // 这里只做配置页特有的事情
    
    // 卡片默认折叠状态由 config.html 的 initConfigPage 统一管理（后 4 张默认折叠），此处不再强制展开
    
    // 加载标签规则
    if (typeof loadTagRules === 'function') {
        loadTagRules();
    }
    
    // 加载索引状态
    setTimeout(loadIndexStats, 500);
});