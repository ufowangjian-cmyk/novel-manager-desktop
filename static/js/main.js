// ===== 主题管理 =====
// 根据系统主题判断
function getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// 应用主题到主页


// 监听系统主题变化（当设置为 auto 时）


// ===== 扫描进度相关 =====
let scanning = false;
let progressInterval = null;

// 开始扫描
function startScan(fullScan = false) {
    if (scanning) return;
    
    scanning = true;
    const scanBtn = document.getElementById('scanBtn');
    const scanFullBtn = document.getElementById('scanFullBtn');
    const progressContainer = document.getElementById('progressContainer');
    
    if (scanBtn) scanBtn.disabled = true;
    if (scanFullBtn) scanFullBtn.disabled = true;
    if (progressContainer) progressContainer.style.display = 'block';
    
    const url = fullScan ? '/api/start_scan?full=true' : '/api/start_scan';
    
    fetch(url, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'started' || data.status === 'already_scanning') {
                progressInterval = setInterval(checkProgress, 500);
            }
        })
        .catch(error => console.error('扫描启动失败:', error));
}

// 检查进度
function checkProgress() {
    fetch('/api/scan_progress')
        .then(response => response.json())
        .then(data => {
            updateProgressUI(data);
            
            if (data.status === 'completed' || data.status === 'error') {
                clearInterval(progressInterval);
                scanning = false;
                
                const scanBtn = document.getElementById('scanBtn');
                const scanFullBtn = document.getElementById('scanFullBtn');
                if (scanBtn) scanBtn.disabled = false;
                if (scanFullBtn) scanFullBtn.disabled = false;
                
                if (data.status === 'completed') {
                    setTimeout(() => window.location.reload(), 1000);
                }
            }
        });
}

// 更新进度条UI
function updateProgressUI(data) {
    const progressFill = document.getElementById('progressFill');
    const progressMessage = document.getElementById('progressMessage');
    const progressTime = document.getElementById('progressTime');
    
    if (!progressFill) return;
    
    if (data.status === 'scanning') {
        progressFill.style.width = data.percentage + '%';
        if (progressMessage) progressMessage.textContent = data.message;
        
        if (progressTime && data.elapsed) {
            progressTime.textContent = `已用: ${formatTime(data.elapsed)} | 剩余: ${formatTime(data.remaining)}`;
        }
    } else if (data.status === 'completed') {
        progressFill.style.width = '100%';
        if (progressMessage) progressMessage.textContent = '扫描完成！';
        if (progressTime) progressTime.textContent = `共处理 ${data.total} 个文件`;
    } else if (data.status === 'error') {
        progressFill.style.width = '0%';
        if (progressMessage) progressMessage.textContent = '扫描出错：' + data.message;
        if (progressTime) progressTime.textContent = '';
    }
}

// 格式化时间
function formatTime(seconds) {
    if (seconds < 0) seconds = 0;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// 处理书名：括号换行 + 特殊词高亮（合并版）
function formatNovelTitlesAndHighlight() {
    // 需要高亮的特殊词（在这里添加新词）
    var specialWords = [
        '同人续写', '同人续', '同人', 
        '续写', '续写版', '增容',  '增容版',
        '番外篇',  '番外', '特别篇',  '独立篇', 
        '外传', '前传', '后传', 
        '修改',  '加料版', '修改版', 
        '改编版', '改编', '新编', '新编版', 
        '扩编',  '扩编版', '扩写',  '扩写版',  '狼增版',
        '改写版', '改写', 
        '修订版', '无绿版',  '非绿版', '精修版'
    ];
    
    // 处理书名
    document.querySelectorAll('.novel-title').forEach(function(el) {
        if (el.hasAttribute('data-processed')) return;
        
        var originalText = el.textContent;
        var hasBracket = /[（【]/.test(originalText);
        var result = originalText;
        
        // 第一步：处理括号换行
        if (hasBracket) {
            var firstBracketIndex = -1;
            for (var i = 0; i < originalText.length; i++) {
                if (originalText[i] === '（' || originalText[i] === '【') {
                    firstBracketIndex = i;
                    break;
                }
            }
            
            if (firstBracketIndex > 0) {
                var mainTitle = originalText.substring(0, firstBracketIndex);
                var bracketContent = originalText.substring(firstBracketIndex);
                result = mainTitle + '<br><span class="bracket-content">' + bracketContent + '</span>';
            } else if (firstBracketIndex === 0) {
                result = '<span class="bracket-content">' + originalText + '</span>';
            }
        }
        
        // 第二步：高亮特殊词
        for (var j = 0; j < specialWords.length; j++) {
            var word = specialWords[j];
            var regex = new RegExp('(' + word + ')', 'g');
            result = result.replace(regex, '<span class="faint-highlight">$1</span>');
        }
        
        el.innerHTML = result;
        el.setAttribute('data-processed', 'true');
    });
    
    // 处理作者（换行：作者名一行，括号内容单独一行，每行超出省略）
    document.querySelectorAll('.author-link').forEach(function(el) {
        if (el.hasAttribute('data-processed')) return;
        
        var originalText = el.textContent.trim();
        var hasBracket = /[（【[]/.test(originalText);
        
        if (hasBracket) {
            // 找到第一个括号的位置
            var firstBracketIndex = -1;
            for (var i = 0; i < originalText.length; i++) {
                if (originalText[i] === '（' || originalText[i] === '【' || originalText[i] === '[') {
                    firstBracketIndex = i;
                    break;
                }
            }
            
            if (firstBracketIndex > 0) {
                var mainAuthor = originalText.substring(0, firstBracketIndex);
                var bracketContent = originalText.substring(firstBracketIndex);
                // 换行，作者名和括号内容分别用 span 包裹，方便控制省略
                el.innerHTML = '<span class="author-name">' + mainAuthor + '</span><span class="bracket-content">' + bracketContent + '</span>';
            } else if (firstBracketIndex === 0) {
                // 只有括号的情况，整行作为括号内容
                var bracketContent = originalText;
                el.innerHTML = '<span class="bracket-content">' + bracketContent + '</span>';
            } else {
                // 没有括号，保持原样
                el.innerHTML = '<span class="author-name">' + originalText + '</span>';
            }
            
            el.setAttribute('data-processed', 'true');
        }
    });

}


// 页面加载时执行
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', formatNovelTitlesAndHighlight);
} else {
    formatNovelTitlesAndHighlight();
}

// 监听动态加载的内容（分页等）
var observer = new MutationObserver(function() {
    formatNovelTitlesAndHighlight();
});

var targetElement = document.querySelector('.bookshelf-wrapper');
if (targetElement) {
    observer.observe(targetElement, { childList: true, subtree: true });
} else {
    // 如果目标元素还没加载，等待一下
    setTimeout(function() {
        var el = document.querySelector('.bookshelf-wrapper');
        if (el) observer.observe(el, { childList: true, subtree: true });
    }, 1000);
}

// ===== 分页功能 =====
// 跳转到指定页码
function gotoPage(maxPage) {
    const pageInput = document.getElementById('gotoPage');
    if (!pageInput) return;
    
    let page = parseInt(pageInput.value);
    if (isNaN(page)) page = 1;
    if (page < 1) page = 1;
    if (page > maxPage) page = maxPage;
    
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('page', page);
    
    // 确保排序参数保留（如果没有则用默认值）
    if (!urlParams.has('sort')) {
        urlParams.set('sort', 'title');
    }
    if (!urlParams.has('order')) {
        urlParams.set('order', 'asc');
    }
    
    window.location.href = `?${urlParams.toString()}`;
}

// 初始化分页输入框
function initPagination(maxPage) {
    const gotoPageInput = document.getElementById('gotoPage');
    if (gotoPageInput) {
        gotoPageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                let page = parseInt(gotoPageInput.value);
                if (isNaN(page)) page = 1;
                if (page < 1) page = 1;
                if (page > maxPage) page = maxPage;
                
                const urlParams = new URLSearchParams(window.location.search);
                urlParams.set('page', page);
                
                // 确保排序参数保留
                if (!urlParams.has('sort')) {
                    urlParams.set('sort', 'title');
                }
                if (!urlParams.has('order')) {
                    urlParams.set('order', 'asc');
                }
                
                window.location.href = `?${urlParams.toString()}`;
            }
        });
    }
}

// ===== 动态显示全部作者/标签/网站 =====
// 获取当前搜索参数
function getCurrentParams() {
    const params = new URLSearchParams(window.location.search);
    ['author', 'tag', 'site', 'page'].forEach(key => params.delete(key));
    return params.toString();
}

// 通用加载全部项目函数
async function loadAllItems(url, containerId, type, createLink) {
    const container = document.querySelector(containerId);
    if (!container || container.getAttribute('data-loaded') === 'all') return;
    
    const showAllBtn = container.querySelector('.show-all');
    if (showAllBtn) {
        showAllBtn.textContent = '加载中...';
        showAllBtn.style.pointerEvents = 'none';
    }
    
    try {
        const response = await fetch(url);
        const data = await response.json();
        const items = data[type];
        const params = getCurrentParams();
        
        // 清空容器，只保留一个"全部"链接的引用
        const allLinkExists = container.querySelector('a.filter-tag[href*="?"]') || 
                              container.querySelector('a.filter-tag');
        container.innerHTML = '';
        
        // 重新添加"全部"按钮
        const allLink = document.createElement('a');
        allLink.href = `?${params}`;
        allLink.className = 'filter-tag';
        allLink.textContent = '全部';
        // 如果当前没有筛选条件，高亮"全部"
        if (!window.location.search.includes('author=') && 
            !window.location.search.includes('tag=') && 
            !window.location.search.includes('site=')) {
            allLink.classList.add('active');
        }
        container.appendChild(allLink);
        
        // 添加所有项目
        items.forEach(item => {
            if (item !== '全部') {
                container.appendChild(createLink(item, params));
            }
        });
        
        container.setAttribute('data-loaded', 'all');
        
        // 添加收起按钮
        const collapseBtn = document.createElement('a');
        collapseBtn.href = '#';
        collapseBtn.className = 'show-all';
        collapseBtn.textContent = '收起 ↑';
        collapseBtn.onclick = (e) => {
            e.preventDefault();
            collapseItems(containerId, type);
        };
        container.appendChild(collapseBtn);
        
    } catch (error) {
        console.error(`加载${type}失败:`, error);
        const btn = container.querySelector('.show-all');
        if (btn) {
            btn.textContent = `显示全部 →`;
            btn.style.pointerEvents = 'auto';
        }
    } finally {
        if (showAllBtn) showAllBtn.style.pointerEvents = 'auto';
    }
}

// 通用收起功能
async function collapseItems(containerSelector, itemKey, getActiveValue) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    
    container.innerHTML = '';
    container.removeAttribute('data-loaded');
    
    const urls = {
        authors: '/get_first_authors',
        tags: '/get_first_tags',
        sites: '/get_first_sites'
    };
    const limits = { authors: 100, tags: 50, sites: 20 };
    const displayNames = { authors: '作者', tags: '标签', sites: '网站' };
    const queryParams = { authors: 'author', tags: 'tag', sites: 'site' };
    
    const url = urls[itemKey];
    const limit = limits[itemKey];
    const displayName = displayNames[itemKey];
    const queryParam = queryParams[itemKey];
    
    try {
        const response = await fetch(url);
        const data = await response.json();
        
        const params = getCurrentParams();
        const activeValue = getActiveValue();
        
        // 添加"全部"按钮
        const allLink = document.createElement('a');
        allLink.href = `?${params}`;
        allLink.className = 'filter-tag';
        allLink.textContent = '全部';
        container.appendChild(allLink);
        
        // 添加项目
        const items = data[itemKey];
        items.forEach(item => {
            const link = document.createElement('a');
            link.href = `?${queryParam}=${encodeURIComponent(item)}${params ? '&' + params : ''}`;
            link.className = 'filter-tag';
            if (item === activeValue) link.classList.add('active');
            link.textContent = item;
            container.appendChild(link);
        });
        
        // 添加显示全部按钮
        const showAllBtn = document.createElement('a');
        showAllBtn.href = '#';
        showAllBtn.className = 'show-all';
        showAllBtn.textContent = `显示全部 ${data.total} 个${displayName} →`;
        showAllBtn.onclick = (e) => {
            e.preventDefault();
            const handlers = {
                authors: showAllAuthors,
                tags: showAllTags,
                sites: showAllSites
            };
            handlers[itemKey](e);
        };
        container.appendChild(showAllBtn);
        
    } catch (error) {
        console.error(`收起${itemKey}失败:`, error);
    }
}

// 显示全部作者
function showAllAuthors(event) {
    event.preventDefault();
    loadAllItems(
        '/get_all_authors',
        '#authorSection .filter-tags',
        'authors',
        (author, params, activeValue) => {
            const link = document.createElement('a');
            link.href = `?author=${encodeURIComponent(author)}${params ? '&' + params : ''}`;
            link.className = 'filter-tag';
            if (author === activeValue) link.classList.add('active');
            link.textContent = author;
            return link;
        },
        () => '{{ search_author }}'
    );
}

// 显示全部标签
function showAllTags(event) {
    event.preventDefault();
    loadAllItems(
        '/get_all_tags',
        '#tagSection .filter-tags',
        'tags',
        (tag, params, activeValue) => {
            const link = document.createElement('a');
            link.href = `?tag=${encodeURIComponent(tag)}${params ? '&' + params : ''}`;
            link.className = 'filter-tag';
            if (tag === activeValue) link.classList.add('active');
            link.textContent = tag;
            return link;
        },
        () => '{{ search_tag }}'
    );
}

// 显示全部网站
function showAllSites(event) {
    event.preventDefault();
    loadAllItems(
        '/get_all_sites',
        '#siteSection .filter-tags',
        'sites',
        (site, params, activeValue) => {
            const link = document.createElement('a');
            link.href = `?site=${encodeURIComponent(site)}${params ? '&' + params : ''}`;
            link.className = 'filter-tag';
            if (site === activeValue) link.classList.add('active');
            link.textContent = site;
            return link;
        },
        () => '{{ search_site }}'
    );
}

// 收起作者


// 收起标签


// 收起网站


// ===== 折叠/展开功能 =====
function toggleSection(titleElement) {
    const section = titleElement.closest('.filter-section');
    if (section) {
        section.classList.toggle('collapsed');
    }
}

// ===== 工具箱抽屉控制的三个工具区块（筛选搜索 / 最近阅读 / 扫描管理）=====
// 历史说明：早期首页顶部有 .tab-btn 标签按钮，由其专属的 initTabs() 负责切换与折叠；
// 该按钮在 UI 重构中被移除后，initTabs() 因找不到 .tab-btn 而提前 return，
// activeTab 的 localStorage 持久化形同虚设（刷新即丢）。现已将「加载时还原 + 抽屉点击切换」
// 统一收归到 initTabDrawer()（见下方）；「收起」按钮逻辑在 initTabHideButtons()。


// ===== 删除单条阅读记录 =====
function deleteSingleRecord(btn) {
    const filePath = btn.getAttribute('data-file-path');
    if (!filePath) return;

    // 显示加载状态
    const originalText = btn.textContent;
    btn.textContent = '⏳';
    btn.disabled = true;
    
    fetch('/api/delete_record', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ file_path: filePath })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 删除成功，移除卡片
            const wrapper = btn.closest('.recent-card-wrapper');
            if (wrapper) {
                wrapper.remove();
                showNotification('已删除阅读记录', 'success');
                
                // 如果没有记录了，刷新页面显示空状态
                const remainingCards = document.querySelectorAll('.recent-card-wrapper');
                if (remainingCards.length === 0) {
                    // 刷新页面以显示空状态
                    location.reload();
                } else {
                    // 更新计数显示
                    updateRecentCount();
                }
            }
        } else {
            showNotification(data.message || '删除失败', 'error');
            btn.textContent = originalText;
            btn.disabled = false;
        }
    })
    .catch(error => {
        console.error('删除失败:', error);
        showNotification('删除失败，请重试', 'error');
        btn.textContent = originalText;
        btn.disabled = false;
    });
}

// 更新最近阅读计数
function updateRecentCount() {
    const remainingCards = document.querySelectorAll('.recent-card-wrapper');
    const recentCountSpan = document.querySelector('.recent-count');
    if (recentCountSpan && remainingCards) {
        recentCountSpan.textContent = `共 ${remainingCards.length} 条`;
    }
}

// 暴露全局函数
window.startScan = startScan;
window.gotoPage = gotoPage;
window.showAllAuthors = showAllAuthors;
window.showAllTags = showAllTags;
window.showAllSites = showAllSites;



window.toggleSection = toggleSection;
window.deleteSingleRecord = deleteSingleRecord;  // 添加这一行

// ===== 抽屉功能（整合 日志 / 标签管理 / 配置）=====
function initDrawer() {
    const drawerBtn = document.getElementById('drawerBtn');
    const drawerPanel = document.getElementById('drawerPanel');
    const drawerOverlay = document.getElementById('drawerOverlay');
    const drawerCloseBtn = document.getElementById('drawerCloseBtn');
    
    if (!drawerBtn || !drawerPanel || !drawerOverlay) return;
    
    function openDrawer() {
        drawerPanel.classList.add('open');
        drawerOverlay.classList.add('open');
        drawerPanel.setAttribute('aria-hidden', 'false');
    }
    
    function closeDrawer() {
        drawerPanel.classList.remove('open');
        drawerOverlay.classList.remove('open');
        drawerPanel.setAttribute('aria-hidden', 'true');
    }
    
    drawerBtn.addEventListener('click', openDrawer);
    drawerOverlay.addEventListener('click', closeDrawer);
    if (drawerCloseBtn) {
        drawerCloseBtn.addEventListener('click', closeDrawer);
    }
    
    // ESC 关闭抽屉
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && drawerPanel.classList.contains('open')) {
            closeDrawer();
        }
    });
    
    // 暴露全局函数
    window.openDrawer = openDrawer;
    window.closeDrawer = closeDrawer;
}

// ===== 抽屉中的「视图类」入口（筛选/最近阅读/扫描）=====
// 顶部标签按钮已移除，这里让抽屉项直接切换对应面板并自动收起抽屉
function initTabDrawer() {
    const drawerTabItems = document.querySelectorAll('.drawer-item[data-tab]');
    const contentWrapper = document.getElementById('tabsContentWrapper');
    if (!drawerTabItems.length) return;

    function activateTab(tabId) {
        document.querySelectorAll('.tab-content').forEach(function(content) {
            content.classList.toggle('active', content.id === 'tab-' + tabId);
        });
        // 确保面板容器处于展开状态（避免被折叠隐藏）
        if (contentWrapper) contentWrapper.classList.remove('collapsed');
        try { localStorage.setItem('activeTab', tabId); } catch (e) {}
        // 切换后收起抽屉，露出内容
        if (typeof window.closeDrawer === 'function') window.closeDrawer();
    }

    // ===== 页面加载时恢复上次打开的工具区块 =====
    // initTabDrawer 是筛选搜索/最近阅读/扫描三类工具区块的唯一控制入口：
    // 抽屉点击切换与加载时还原都在这里完成，activeTab 写入 localStorage 后靠本段回写，
    // 刷新/重新进入页面不再丢失（主动点「收起 ✕」会清掉 activeTab，故不会复活）。
    try {
        const savedTab = localStorage.getItem('activeTab');
        if (savedTab && document.getElementById('tab-' + savedTab)) {
            document.querySelectorAll('.tab-content').forEach(function(content) {
                content.classList.toggle('active', content.id === 'tab-' + savedTab);
            });
            if (contentWrapper) contentWrapper.classList.remove('collapsed');
        }
    } catch (e) {}

    drawerTabItems.forEach(function(item) {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = item.getAttribute('data-tab');
            if (tabId) activateTab(tabId);
        });
    });
}

// ===== 区块隐藏按钮 =====
// 在每个 tab-content 面板右上角注入「收起」按钮，点击后隐藏该面板（书库表格不受影响）
function initTabHideButtons() {
    document.querySelectorAll('.tab-content').forEach(function(panel) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'tab-hide-btn';
        btn.textContent = '收起 ✕';
        btn.title = '隐藏此区块';
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            panel.classList.remove('active');
            try { localStorage.removeItem('activeTab'); } catch (err) {}
        });
        panel.insertBefore(btn, panel.firstChild);
    });
}

// ===== 主页初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    // 使用 common.js 的函数
    if (typeof loadAndApplyTheme === 'function') {
        loadAndApplyTheme();
        watchSystemTheme();
    }
    
    // 初始化轮播图
    if (typeof initCarousel === 'function') {
        initCarousel('.header', {
            autoSlideshow: true,
            intervalTime: 8000
        });
    }
    
    // 主页特有的初始化
    initDrawer();
    initTabDrawer();
    initTabHideButtons();
    
    const maxPageElement = document.getElementById('maxPage');
    if (maxPageElement) {
        const maxPage = parseInt(maxPageElement.value);
        if (!isNaN(maxPage)) {
            initPagination(maxPage);
        }
    }
    
    console.log('主页初始化完成');
});

// 在 index.html 的 script 标签中添加
(function() {
    const searchInput = document.getElementById('searchInput');
    const suggestionsBox = document.getElementById('searchSuggestions');
    let currentHighlight = -1;
    let suggestions = [];
    
    if (!searchInput || !suggestionsBox) return;
    
    // 防抖函数
    function debounce(fn, delay) {
        let timer = null;
        return function(...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    }
    
    // 获取建议
    async function fetchSuggestions(prefix) {
        if (!prefix || prefix.length < 1) {
            suggestionsBox.classList.remove('active');
            return;
        }
        
        try {
            const response = await fetch(`/api/search/suggest?q=${encodeURIComponent(prefix)}&limit=10`);
            const data = await response.json();
            
            if (data.suggestions && data.suggestions.length > 0) {
                suggestions = data.suggestions;
                renderSuggestions(suggestions, prefix);
                suggestionsBox.classList.add('active');
                currentHighlight = -1;
            } else {
                suggestionsBox.classList.remove('active');
            }
        } catch (e) {
            console.error('获取建议失败:', e);
            suggestionsBox.classList.remove('active');
        }
    }
    
    // 渲染建议
    function escapeSuggestionHtml(text) {
        return String(text ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderSuggestions(items, query) {
        const safeQuery = String(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(safeQuery, 'gi');

        suggestionsBox.innerHTML = items.map(item => {
            const raw = String(item ?? '');
            let html = '';
            let lastIndex = 0;
            raw.replace(regex, (match, offset) => {
                html += escapeSuggestionHtml(raw.slice(lastIndex, offset));
                html += `<span class="highlight">${escapeSuggestionHtml(match)}</span>`;
                lastIndex = offset + match.length;
                return match;
            });
            html += escapeSuggestionHtml(raw.slice(lastIndex));
            const attrValue = escapeSuggestionHtml(raw);
            return `<div class="suggestion-item" data-value="${attrValue}">${html}</div>`;
        }).join('');
    }
    
    // 选择建议
    function selectSuggestion(value) {
        searchInput.value = value;
        suggestionsBox.classList.remove('active');
        // 自动提交搜索
        document.getElementById('searchForm').submit();
    }
    
    // 键盘导航
    function handleKeydown(e) {
        const items = suggestionsBox.querySelectorAll('.suggestion-item');
        
        switch(e.key) {
            case 'ArrowDown':
                e.preventDefault();
                if (items.length) {
                    currentHighlight = (currentHighlight + 1) % items.length;
                    items.forEach((el, i) => {
                        el.classList.toggle('active', i === currentHighlight);
                    });
                }
                break;
                
            case 'ArrowUp':
                e.preventDefault();
                if (items.length) {
                    currentHighlight = (currentHighlight - 1 + items.length) % items.length;
                    items.forEach((el, i) => {
                        el.classList.toggle('active', i === currentHighlight);
                    });
                }
                break;
                
            case 'Enter':
                if (currentHighlight >= 0 && items[currentHighlight]) {
                    e.preventDefault();
                    selectSuggestion(items[currentHighlight].dataset.value);
                }
                break;
                
            case 'Escape':
                suggestionsBox.classList.remove('active');
                currentHighlight = -1;
                break;
        }
    }
    
    // 事件绑定
    searchInput.addEventListener('input', debounce(function(e) {
        const value = e.target.value.trim();
        if (value.length >= 1) {
            fetchSuggestions(value);
        } else {
            suggestionsBox.classList.remove('active');
        }
    }, 300));
    
    searchInput.addEventListener('keydown', handleKeydown);
    
    // 点击外部关闭
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.search-item')) {
            suggestionsBox.classList.remove('active');
        }
    });
    
    // 点击建议项
    suggestionsBox.addEventListener('click', function(e) {
        const item = e.target.closest('.suggestion-item');
        if (item) {
            selectSuggestion(item.dataset.value);
        }
    });
})();