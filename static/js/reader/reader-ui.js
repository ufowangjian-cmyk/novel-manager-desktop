// ============================================
// reader-ui.js - 阅读器交互控制（桌面版）
// 依赖：common.js, reader-core.js
// 使用场景：read_chapter.html
// 说明：桌面版是单用户本机运行，所有偏好存 localStorage，
// 但统一排版字段（字号/行高/高亮字体）同时写回 config.json，作为单一真相源（与配置页双向同步）。
window.novelPatchConfig = (function () {
    var timer = null, pending = {};
    return function (patch) {
        if (!patch) return;
        for (var k in patch) { if (Object.prototype.hasOwnProperty.call(patch, k)) pending[k] = patch[k]; }
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
            timer = null;
            var data = pending; pending = {};
            try {
                fetch('/config/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                }).catch(function () {});
            } catch (e) {}
        }, 400);
    };
})();
//       不调用 /api/save_preferences（桌面版没有该接口）。
// ============================================

(function() {
    'use strict';

    // 轻提示
    function showTip(text, color) {
        const old = document.getElementById('reader-font-tip');
        if (old) old.remove();

        const tip = document.createElement('div');
        tip.id = 'reader-font-tip';
        tip.textContent = text;
        tip.style.cssText = `
            position: fixed; top: 20px; right: 20px;
            background: ${color || '#4caf50'}; color: white;
            padding: 8px 16px; border-radius: 8px;
            z-index: 10000; font-size: 14px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            transition: opacity 0.3s ease;
        `;
        document.body.appendChild(tip);
        setTimeout(() => {
            tip.style.opacity = '0';
            setTimeout(() => tip.remove(), 300);
        }, 1200);
    }

    // ==================== 字号 ====================
    const FONT_MIN = 14;
    const FONT_MAX = 40;
    const FONT_STEP = 2;

    function getCurrentFontSize() {
        const content = document.querySelector('.reading-content');
        if (content) {
            const inline = parseFloat(content.style.fontSize);
            if (!isNaN(inline)) return inline;
            const computed = parseFloat(getComputedStyle(content).fontSize);
            if (!isNaN(computed)) return computed;
        }
        return 24;
    }

    function setFontSize(size) {
        const content = document.querySelector('.reading-content');
        if (!content) return;
        const val = Math.max(FONT_MIN, Math.min(FONT_MAX, Math.round(Number(size))));
        content.style.setProperty('font-size', val + 'px', 'important');
        localStorage.setItem('reader_font_size', val);
        if (window.novelPatchConfig) window.novelPatchConfig({ font_size: val });
        highlightFontBtn(val);
        syncSetDrawerSize(val);
    }

    // A- / A+ 步进
    function stepFontSize(delta) {
        setFontSize(getCurrentFontSize() + delta);
    }

    function syncSetDrawerSize(size) {
        const el = document.getElementById('setSizeVal');
        if (el) el.textContent = size;
    }

    function highlightFontBtn(size) {
        document.querySelectorAll('.font-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        const activeBtn = document.getElementById('font' + size);
        if (activeBtn) activeBtn.classList.add('active');
    }

    // ==================== 行高 / 段距 / 首行缩进 ====================
    function setLineHeight(value) {
        const v = Math.max(1.2, Math.min(2.6, parseFloat(value) || 1.8));
        document.documentElement.style.setProperty('--reader-line-height', v);
        localStorage.setItem('reader_line_height', v);
        if (window.novelPatchConfig) window.novelPatchConfig({ line_height: v });
        const el = document.getElementById('setLineHeightVal');
        if (el) el.textContent = v.toFixed(1);
    }

    function setParagraphSpacing(value) {
        const v = Math.max(0, Math.min(2, parseFloat(value)));
        if (isNaN(v)) return;
        document.documentElement.style.setProperty('--reader-paragraph-spacing', v + 'rem');
        localStorage.setItem('reader_paragraph_spacing', v);
        const el = document.getElementById('setParaSpacingVal');
        if (el) el.textContent = v.toFixed(1);
    }

    function toggleIndent(btn) {
        if (!btn) return;
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        document.documentElement.style.setProperty('--reader-text-indent', on ? '2em' : '0');
        localStorage.setItem('reader_indent_paragraph', on ? '1' : '0');
    }

    // ==================== 背景主题 ====================
    const READER_THEMES = ['default', 'paper', 'white', 'green', 'sepia', 'gray', 'night'];

    function applyReaderTheme(theme, opts) {
        const options = opts || {};
        const t = READER_THEMES.indexOf(theme) >= 0 ? theme : 'default';
        const box = document.querySelector('.reader-container') || document.body;
        if (box) box.setAttribute('data-reader-theme', t);

        document.querySelectorAll('#setThemes .set-theme').forEach(btn => {
            btn.classList.toggle('on', btn.getAttribute('data-rt') === t);
        });

        if (!options.silent) {
            localStorage.setItem('reader_theme', t);
        }
    }

    // ==================== 设置抽屉开关 ====================
    // ==================== 按住拖动翻页（抓手）====================
    // 参考 NAS 版实现：在正文区域按住拖动即可滚动页面（抓手手势）。
    // 桌面版无移动端，不兼容触屏，逻辑比 NAS 版更精简（去掉了圈选/触屏分支）。
    const DRAG_HOLD_DELAY = 150;   // ms，按住多久才算拖拽
    const DRAG_MOVE_THRESHOLD = 5; // px，超过多少位移才算拖拽
    let dragScrollEnabled = true;
    let textSelectEnabled = false; // 圈选文字模式：开启后禁用拖动翻页，允许自由选词/复制
    let dragState = null;
    let suppressNextClick = false;

    function isDragScrollOn() {
        return dragScrollEnabled;
    }

    // 与沉浸模式共用同一份可交互元素白名单：图片/链接/按钮上不启动拖拽
    const DRAG_EXCLUDE_SELECTOR = 'a, img, video, audio, button, input, select, textarea, label, .emoji, [data-img-id], .image-wrapper, .local-video-figure';

    function initDragScroll() {
        const wrapper = document.getElementById('contentWrapper');
        if (!wrapper) return;

        // mousedown：记录起点，启动按住计时器
        wrapper.addEventListener('mousedown', function (e) {
            if (!dragScrollEnabled) return;
            if (textSelectEnabled) return; // 圈选模式下不拦截，交给原生选词
            if (e.button !== 0) return; // 只响应主键
            if (e.target.closest(DRAG_EXCLUDE_SELECTOR)) return;
            // 关键：必须在 mousedown 阶段就掐掉原生选词，否则拖拽时会圈出一段文字
            e.preventDefault();
            dragState = {
                startY: e.clientY,
                lastY: e.clientY,
                startX: e.clientX,
                active: false,
                holdTimer: null
            };
            // 按住超过阈值时间才进入拖拽；期间若已移动超阈值则提前激活，
            // 这样「快速拖一下」不会被 150ms 延迟拖住
            dragState.holdTimer = setTimeout(function () {
                if (dragState && !dragState.active) {
                    activateDrag();
                }
            }, DRAG_HOLD_DELAY);
        });

        // mousemove：移动超阈值才激活拖拽；激活后跟随滚动
        wrapper.addEventListener('mousemove', function (e) {
            if (!dragState) return;
            const dy = e.clientY - dragState.startY;
            const dx = e.clientX - dragState.startX;
            if (!dragState.active) {
                // 明显是横向滑动时不误判为拖拽
                if (Math.abs(dx) > Math.abs(dy)) {
                    clearDragState();
                    return;
                }
                if (Math.abs(dy) < DRAG_MOVE_THRESHOLD) return;
                clearTimeout(dragState.holdTimer);
                activateDrag();
            }
            e.preventDefault();
            const deltaY = dragState.lastY - e.clientY; // 手指下移 → 内容上移
            dragState.lastY = e.clientY;
            window.scrollBy(0, deltaY);
        });

        // mouseup / 离开窗口：结束拖拽
        function endDrag() {
            if (!dragState) return;
            const wasActive = dragState.active;
            clearDragState();
            // 拖拽结束后浏览器还会派发一次 click，必须吞掉，
            // 否则会误触发「点击正文切换工具栏」
            if (wasActive) {
                suppressNextClick = true;
                setTimeout(function () { suppressNextClick = false; }, 0);
            }
        }
        wrapper.addEventListener('mouseup', endDrag);
        wrapper.addEventListener('mouseleave', endDrag);
        window.addEventListener('mouseup', endDrag);
        window.addEventListener('blur', endDrag);

        // 拖拽时阻止图片/文字原生拖拽，避免出现虚影
        wrapper.addEventListener('dragstart', function (e) {
            if (dragState && dragState.active) e.preventDefault();
        });
    }

    function activateDrag() {
        if (!dragState) return;
        dragState.active = true;
        document.body.classList.add('is-drag-scrolling');
    }

    function clearDragState() {
        if (!dragState) return;
        clearTimeout(dragState.holdTimer);
        dragState = null;
        document.body.classList.remove('is-drag-scrolling');
    }

    // 切换「按住拖动翻页」（抓手）。btn 缺省时仅翻转状态（供快捷键调用）
    function toggleDragScroll(btn) {
        if (!btn) return;
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        dragScrollEnabled = on;
        clearDragState();
        localStorage.setItem('reader_drag_scroll', on ? '1' : '0');
        // 互斥：开启拖动翻页则关闭圈选文字
        if (on) {
            textSelectEnabled = false;
            document.body.classList.remove('text-select-mode');
            const selBtn = document.getElementById('setTextSelect');
            if (selBtn) {
                selBtn.classList.remove('on');
                selBtn.setAttribute('aria-checked', 'false');
            }
            localStorage.setItem('reader_text_select', '0');
        }
    }

    // 切换「圈选文字」模式。开启后禁用拖动翻页，允许自由选词/复制
    function toggleTextSelect(btn) {
        if (!btn) return;
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        textSelectEnabled = on;
        document.body.classList.toggle('text-select-mode', on);
        localStorage.setItem('reader_text_select', on ? '1' : '0');
        // 互斥：开启圈选则关闭拖动翻页
        if (on) {
            dragScrollEnabled = false;
            clearDragState();
            const dragBtn = document.getElementById('setDragScroll');
            if (dragBtn) {
                dragBtn.classList.remove('on');
                dragBtn.setAttribute('aria-checked', 'false');
            }
            localStorage.setItem('reader_drag_scroll', '0');
        }
    }

    function openSetDrawer() {
        const drawer = document.getElementById('setDrawer');
        const mask = document.getElementById('setDrawerMask');
        if (!drawer) return;
        drawer.classList.add('active');
        if (mask) mask.classList.add('active');
    }

    function closeSetDrawer() {
        const drawer = document.getElementById('setDrawer');
        const mask = document.getElementById('setDrawerMask');
        if (drawer) drawer.classList.remove('active');
        if (mask) mask.classList.remove('active');
    }

    // 恢复默认：只重置排版项，不动字体/朗读
    function resetReaderSettings() {
        if (!confirm('恢复默认排版设置？')) return;
        const defaults = { size: 24, lh: 1.8, ps: 0.8, indent: true, theme: 'default' };

        setFontSize(defaults.size);

        const lh = document.getElementById('setLineHeight');
        if (lh) lh.value = defaults.lh;
        setLineHeight(defaults.lh);

        const ps = document.getElementById('setParaSpacing');
        if (ps) ps.value = defaults.ps;
        setParagraphSpacing(defaults.ps);

        const indentBtn = document.getElementById('setIndent');
        if (indentBtn) {
            indentBtn.classList.add('on');
            indentBtn.setAttribute('aria-checked', 'true');
        }
        document.documentElement.style.setProperty('--reader-text-indent', '2em');
        localStorage.setItem('reader_indent_paragraph', '1');

        applyReaderTheme(defaults.theme);
        showTip('✓ 已恢复默认排版');
    }

    // ==================== 沉浸模式 ====================
    let immersiveEnabled = true;
    let immersiveTimer = null;
    let immersiveHintShown = false;

    function setBarsHidden(hidden) {
        const top = document.getElementById('readerTop');
        const bottom = document.getElementById('readerBottom');
        if (top) top.classList.toggle('is-hidden', hidden);
        if (bottom) bottom.classList.toggle('is-hidden', hidden);
    }

    function areBarsHidden() {
        const top = document.getElementById('readerTop');
        return !!(top && top.classList.contains('is-hidden'));
    }

    function toggleImmersive() {
        if (!immersiveEnabled) return;
        const hide = !areBarsHidden();
        setBarsHidden(hide);

        // 首次呼出工具栏时给个提示
        if (!hide && !immersiveHintShown) {
            immersiveHintShown = true;
            const hint = document.getElementById('immersiveHint');
            if (hint) {
                hint.classList.add('show');
                setTimeout(() => hint.classList.remove('show'), 2000);
            }
        }

        // 显示工具栏后 3 秒自动收起
        if (!hide) {
            clearTimeout(immersiveTimer);
            immersiveTimer = setTimeout(() => setBarsHidden(true), 3000);
        }
    }

    function initImmersive() {
        const wrapper = document.getElementById('contentWrapper');
        if (!wrapper) return;

        // 点击正文：可交互元素一律放行，其余切换工具栏
        wrapper.addEventListener('click', function (e) {
            if (suppressNextClick) return; // 抓手拖拽结束的 click 不要触发工具栏切换
            if (e.target.closest('a, img, video, audio, button, input, select, textarea, label, .emoji, [data-img-id], .image-wrapper, .local-video-figure')) {
                return;
            }
            // 有文字被选中时不切换（方便复制）
            const sel = window.getSelection();
            if (sel && sel.toString().length > 0) return;

            toggleImmersive();
        });

        // 顶栏/底栏自身被点击时，重置自动收起计时
        [document.getElementById('readerTop'), document.getElementById('readerBottom')].forEach(el => {
            if (!el) return;
            el.addEventListener('click', () => {
                if (!areBarsHidden()) {
                    clearTimeout(immersiveTimer);
                    immersiveTimer = setTimeout(() => setBarsHidden(true), 3000);
                }
            });
        });

        initJumpButtons();
    }

    // ==================== 悬浮跳顶/跳底 ====================
    function initJumpButtons() {
        const jump = document.getElementById('readerJump');
        if (!jump) return;

        const update = () => {
            const y = window.scrollY || document.documentElement.scrollTop || 0;
            jump.hidden = y < 300;
        };

        window.addEventListener('scroll', update, { passive: true });
        update();
    }

    function jumpToTop() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function jumpToBottom() {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
    }

    // ==================== 抽屉初始化 ====================
    function initSetDrawer() {
        // 背景主题色块
        document.querySelectorAll('#setThemes .set-theme').forEach(btn => {
            btn.addEventListener('click', () => {
                applyReaderTheme(btn.getAttribute('data-rt'));
            });
        });

        // 从 localStorage 恢复排版设置
        const savedLh = parseFloat(localStorage.getItem('reader_line_height'));
        const cfgLh = (typeof window.readerCfgLineHeight !== 'undefined' && window.readerCfgLineHeight != null) ? window.readerCfgLineHeight : 1.8;
        const lh = !isNaN(savedLh) ? savedLh : cfgLh;
        const lhEl = document.getElementById('setLineHeight');
        if (lhEl) {
            lhEl.value = lh;
            const v = document.getElementById('setLineHeightVal');
            if (v) v.textContent = lh.toFixed(1);
        }
        document.documentElement.style.setProperty('--reader-line-height', lh);

        const savedPs = parseFloat(localStorage.getItem('reader_paragraph_spacing'));
        const psEl = document.getElementById('setParaSpacing');
        if (psEl && !isNaN(savedPs)) {
            psEl.value = savedPs;
            const v = document.getElementById('setParaSpacingVal');
            if (v) v.textContent = savedPs.toFixed(1);
        }
        if (!isNaN(savedPs)) {
            document.documentElement.style.setProperty('--reader-paragraph-spacing', savedPs + 'rem');
        }

        // 首行缩进开关状态：localStorage 优先，缺省回退服务端 CONFIG 默认（默认缩进）
        const savedIndent = localStorage.getItem('reader_indent_paragraph');
        const indentBtn = document.getElementById('setIndent');
        const indentOn = savedIndent !== null ? savedIndent !== '0' : (window.readerCfgIndent !== false);
        if (indentBtn) {
            indentBtn.classList.toggle('on', indentOn);
            indentBtn.setAttribute('aria-checked', indentOn ? 'true' : 'false');
        }

        // 按住拖动翻页（抓手）开关状态：默认开
        const savedDrag = localStorage.getItem('reader_drag_scroll');
        const dragBtn = document.getElementById('setDragScroll');
        const dragOn = savedDrag === null ? true : savedDrag !== '0';
        dragScrollEnabled = dragOn;
        if (dragBtn) {
            dragBtn.classList.toggle('on', dragOn);
            dragBtn.setAttribute('aria-checked', dragOn ? 'true' : 'false');
        }

        // 圈选文字开关状态：默认关（默认走抓手模式）
        const savedSelect = localStorage.getItem('reader_text_select');
        const selBtn = document.getElementById('setTextSelect');
        const selOn = savedSelect !== null && savedSelect === '1';
        textSelectEnabled = selOn;
        document.body.classList.toggle('text-select-mode', selOn);
        if (selBtn) {
            selBtn.classList.toggle('on', selOn);
            selBtn.setAttribute('aria-checked', selOn ? 'true' : 'false');
        }
        // 两个开关互斥一致性：圈选开启时拖动必关
        if (selOn) {
            dragScrollEnabled = false;
            if (dragBtn) {
                dragBtn.classList.remove('on');
                dragBtn.setAttribute('aria-checked', 'false');
            }
        }

        // 字号数值同步
        syncSetDrawerSize(getCurrentFontSize());

        // 应用背景主题
        const theme = localStorage.getItem('reader_theme') || 'default';
        applyReaderTheme(theme, { silent: true });
    }

    // ==================== 应用已保存设置 ====================
    function applySavedFontSettings() {
        const savedSize = localStorage.getItem('reader_font_size');

        if (savedSize) {
            const content = document.querySelector('.reading-content');
            if (content) content.style.setProperty('font-size', savedSize + 'px', 'important');
            highlightFontBtn(savedSize);
            syncSetDrawerSize(savedSize);
        }
        // 删除首屏注入的 <style>（字号/排版），正文字体由 hl 体系（hl-font-body）接管，不在此移除
        document.querySelectorAll('style[data-font-style="preload"]').forEach(el => el.remove());
    }

    // ==================== 朗读功能 ====================
    let currentUtterance = null;
    let isPlaying = false;
    let currentPlayIndex = 0;
    let speechLines = [];

    function getCurrentPageText() {
        const lines = document.querySelectorAll('.content-line');
        const texts = [];
        lines.forEach(line => {
            const text = line.textContent || line.innerText;
            const trimmed = text.trim();
            if (trimmed.length > 0 && !/^[*＊—－~～……·•\-=]{3,}$/.test(trimmed) && trimmed.length > 1) {
                texts.push(trimmed);
            }
        });
        return texts;
    }

    function clearHighlightLine() {
        document.querySelectorAll('.content-line.speech-highlight').forEach(line => {
            line.classList.remove('speech-highlight');
        });
    }

    function highlightCurrentLine(index) {
        clearHighlightLine();
        if (index < 0 || index >= speechLines.length) return;
        const lines = document.querySelectorAll('.content-line');
        let lineIndex = 0;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const text = (line.textContent || line.innerText).trim();
            if (text.length > 0 && !/^[*＊—－~～……·•\-=]{3,}$/.test(text) && text.length > 1) {
                if (lineIndex === index) {
                    line.classList.add('speech-highlight');
                    line.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    break;
                }
                lineIndex++;
            }
        }
    }

    function stopSpeech() {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        currentUtterance = null;
        isPlaying = false;
        currentPlayIndex = 0;
        speechLines = [];
        const speechBtn = document.getElementById('speechBtn');
        if (speechBtn) {
            // 按钮在顶栏，是图标按钮：只换图标 + title，不塞文字
            speechBtn.textContent = '🔊';
            speechBtn.title = '朗读本章';
            speechBtn.classList.remove('speaking');
        }
        clearHighlightLine();
    }

    function speakNextLine(rate, pitch) {
        if (!isPlaying || currentPlayIndex >= speechLines.length) {
            stopSpeech();
            return;
        }
        const text = speechLines[currentPlayIndex];
        if (!text || text.length === 0) {
            currentPlayIndex++;
            speakNextLine(rate, pitch);
            return;
        }
        highlightCurrentLine(currentPlayIndex);
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = rate;
        utterance.pitch = pitch;
        utterance.lang = 'zh-CN';
        if (window.speechSynthesis.getVoices) {
            const voices = window.speechSynthesis.getVoices();
            const chineseVoice = voices.find(v => v.lang.includes('zh-CN'));
            if (chineseVoice) utterance.voice = chineseVoice;
        }
        utterance.onend = () => {
            setTimeout(() => {
                if (isPlaying) {
                    currentPlayIndex++;
                    speakNextLine(rate, pitch);
                }
            }, 200);
        };
        utterance.onerror = () => {
            currentPlayIndex++;
            speakNextLine(rate, pitch);
        };
        currentUtterance = utterance;
        window.speechSynthesis.speak(utterance);
    }

    function speakCurrentPage() {
        if (!('speechSynthesis' in window)) {
            alert('您的浏览器不支持语音朗读功能');
            return;
        }
        if (isPlaying) { stopSpeech(); return; }
        speechLines = getCurrentPageText();
        if (speechLines.length === 0) {
            alert('当前页面没有可朗读的文本内容');
            return;
        }
        isPlaying = true;
        currentPlayIndex = 0;
        const speechBtn = document.getElementById('speechBtn');
        if (speechBtn) {
            speechBtn.textContent = '⏹️';
            speechBtn.title = '停止朗读';
            speechBtn.classList.add('speaking');
        }
        const rate = parseFloat(document.getElementById('speechRateSelect')?.value || '1.0');
        const pitch = parseFloat(document.getElementById('speechPitchSelect')?.value || '1.0');
        speakNextLine(rate, pitch);
    }

    function initSpeech() {
        const speechBtn = document.getElementById('speechBtn');
        if (!speechBtn) return;

        // 桌面版单用户：朗读偏好只存 localStorage
        const rate = localStorage.getItem('speech_rate') || '1.0';
        const pitch = localStorage.getItem('speech_pitch') || '1.0';

        const rateSelect = document.getElementById('speechRateSelect');
        const pitchSelect = document.getElementById('speechPitchSelect');
        if (rateSelect) rateSelect.value = rate;
        if (pitchSelect) pitchSelect.value = pitch;
    }

    function setSpeechRate(value) {
        localStorage.setItem('speech_rate', value);
    }

    function setSpeechPitch(value) {
        localStorage.setItem('speech_pitch', value);
    }

    // ==================== 行号跳转 ====================
    function jumpToLine() {
        const input = document.getElementById('jumpLine');
        if (!input) return;
        let line = parseInt(input.value);
        if (isNaN(line) || line < 1) { alert('请输入有效的行号'); return; }
        const max = (typeof TOTAL_LINES !== 'undefined' && TOTAL_LINES) ? TOTAL_LINES : line;
        if (line > max) line = max;
        closeSetDrawer();
        window.location.href = '?line=' + line;
    }

    // ==================== 章节标题美化 ====================
    function styleChapterTitles() {
        const lines = document.querySelectorAll('.content-line');

        const level1Pattern = /^\s*(第(?:\d+|[〇零一二三四五六七八九十百千万]+)[册集卷部]|[上下前后中终序][册集卷部])\s*[：:·\s]*(.*)$/;
        const level2Pattern = /^\s*(第(?:\d+|[〇零一二三四五六七八九十百千万]+)[篇章]|[上下前后中终序][篇章]|楔子|引子|引言|前言|正文|番外|序言|后记|尾声)\s*[：:·\s]*(.*)$/;
        const level3Pattern = /^\s*(第(?:\d+|[〇零一二三四五六七八九十百千万]+)[节回幕目]|[上下前后中终序][节回幕目])\s*[：:·\s]*(.*)$/;

        lines.forEach(line => {
            const originalText = line.textContent;
            const trimmedText = originalText.replace(/^[\s\u3000]+|[\s\u3000]+$/g, '');
            if (trimmedText.length === 0) return;

            // ===== 分隔符检测（分类识别）=====
            const textWithoutSpaces = trimmedText.replace(/[\s\u3000]/g, '');

            let separatorType = null;
            let separatorDisplay = '';

            if (/^[…⋯]{2,}$/.test(textWithoutSpaces) || /^\.{3,}$/.test(textWithoutSpaces)) {
                separatorType = 'ellipsis';
                separatorDisplay = '……';
            }
            else if (/^[○●◎·•]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'dot';
                separatorDisplay = '·  ·  ·  ·  ·  ·';
            }
            else if (/^[＊*※◇♦♢★☆]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'star';
                separatorDisplay = '✦  ✦  ✦  ✦  ✦';
            }
            else if (/^[~～—–─＝=_\-]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'line';
                separatorDisplay = '';
            }
            else if (/^[♡♥☀☁☂✿❀🌸♪♫♩→←↑↓]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'flower';
                separatorDisplay = '✧  ✧  ✧  ✧  ✧';
            }
            else {
                const separatorChars = '[○●◎\\.·•＊*◇♦♢★☆~～—–─＝=_\\-♡♥☀☁☂✿❀🌸♪♫♩→←↑↓]';
                if (new RegExp(`^${separatorChars}{2,}$`).test(textWithoutSpaces)) {
                    separatorType = 'dot';
                    separatorDisplay = '·  ·  ·  ·  ·  ·';
                }
            }

            if (separatorType) {
                line.className = 'content-line separator';
                line.setAttribute('data-type', separatorType);
                line.innerHTML = separatorDisplay;
                return;
            }

            // ===== 标题检测 =====
            let levelClass = '';
            let match = null;

            if ((match = trimmedText.match(level1Pattern))) {
                levelClass = 'chapter-title-level1';
            } else if ((match = trimmedText.match(level2Pattern))) {
                levelClass = 'chapter-title-level2';
            } else if ((match = trimmedText.match(level3Pattern))) {
                levelClass = 'chapter-title-level3';
            }

            if (levelClass && match) {
                line.className = `content-line ${levelClass}`;

                const chapterPart = (match[1] || '').trim();
                const titlePart = (match[2] || '').trim();

                if (chapterPart && titlePart) {
                    line.innerHTML = `<span class="chapter-number">${chapterPart}</span><br>${titlePart}`;
                } else if (chapterPart) {
                    line.innerHTML = `<span class="chapter-number">${chapterPart}</span>`;
                }
            }
        });
    }

    // ==================== 图片错误处理 ====================
    

    // ==================== 键盘快捷键 ====================
    function initKeyboardShortcuts() {
        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;

            // 设置抽屉打开时，只保留 Esc，避免误触翻页
            const setDrawer = document.getElementById('setDrawer');
            if (setDrawer && setDrawer.classList.contains('active')) {
                if (e.key === 'Escape') {
                    closeSetDrawer();
                    e.preventDefault();
                }
                return;
            }

            if (e.key === 'ArrowLeft') {
                const prevBtn = document.querySelector('.bottom-bar .chapter-switch-btn:not(.disabled)');
                if (prevBtn && prevBtn.tagName === 'A') {
                    window.location.href = prevBtn.href;
                }
                e.preventDefault();
            }
            if (e.key === 'ArrowRight') {
                const links = document.querySelectorAll('.bottom-bar a.chapter-switch-btn');
                const nextBtn = links[links.length - 1];
                if (nextBtn) {
                    window.location.href = nextBtn.href;
                }
                e.preventDefault();
            }
            if (e.key === 'g' && !e.ctrlKey && !e.metaKey) {
                openSetDrawer();
                const jumpInput = document.getElementById('jumpLine');
                if (jumpInput) {
                    setTimeout(() => { jumpInput.focus(); jumpInput.select(); }, 320);
                }
                e.preventDefault();
            }
            if (e.key === 'Escape') {
                const active = document.activeElement;
                if (active && (active.tagName === 'INPUT' || active.tagName === 'SELECT')) {
                    active.blur();
                }
                closeSetDrawer();
                e.preventDefault();
            }
        });
    }

    // ===== 暴露全局 API =====
    window.setFontSize = setFontSize;
    window.stepFontSize = stepFontSize;
    window.setLineHeight = setLineHeight;
    window.setParagraphSpacing = setParagraphSpacing;
    window.toggleIndent = toggleIndent;
    window.applyReaderTheme = applyReaderTheme;
    window.openSetDrawer = openSetDrawer;
    window.closeSetDrawer = closeSetDrawer;
    window.resetReaderSettings = resetReaderSettings;
    window.initSetDrawer = initSetDrawer;
    window.toggleImmersive = toggleImmersive;
    window.initImmersive = initImmersive;
    window.initDragScroll = initDragScroll;
    window.toggleDragScroll = toggleDragScroll;
    window.toggleTextSelect = toggleTextSelect;
    window.jumpToTop = jumpToTop;
    window.jumpToBottom = jumpToBottom;
    window.applySavedFontSettings = applySavedFontSettings;
    window.speakCurrentPage = speakCurrentPage;
    window.stopSpeech = stopSpeech;
    window.initSpeech = initSpeech;
    window.setSpeechRate = setSpeechRate;
    window.setSpeechPitch = setSpeechPitch;
    window.jumpToLine = jumpToLine;
    window.styleChapterTitles = styleChapterTitles;
    
    window.initKeyboardShortcuts = initKeyboardShortcuts;

    console.log('✅ reader-ui.js 已加载（桌面版 / localStorage）');
})();
