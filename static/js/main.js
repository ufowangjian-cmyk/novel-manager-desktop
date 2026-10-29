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
let displayedProgress = 0;   // 进度条已显示的百分比，只增不减

// 同步胶囊里那个圆形扫描按钮的状态（扫描中转圈 + 不可点）
function syncScanButtons() {
    const statsScanBtn = document.getElementById('statsScanBtn');
    if (!statsScanBtn) return;
    statsScanBtn.disabled = scanning;
    statsScanBtn.classList.toggle('is-scanning', scanning);
    // 读屏友好：转圈时告诉辅助技术「正在扫描」
    if (scanning) {
        statsScanBtn.setAttribute('aria-busy', 'true');
    } else {
        statsScanBtn.removeAttribute('aria-busy');
    }
}

// 开始扫描
function startScan(fullScan = false) {
    if (scanning) {
        if (typeof showNotification === 'function') {
            showNotification('扫描任务已在运行中', 'warning');
        }
        return;
    }

    scanning = true;
    displayedProgress = 0;
    const scanBtn = document.getElementById('scanBtn');
    const scanFullBtn = document.getElementById('scanFullBtn');
    const progressContainer = document.getElementById('progressContainer');
    
    if (scanBtn) scanBtn.disabled = true;
    if (scanFullBtn) scanFullBtn.disabled = true;
    if (progressContainer) progressContainer.style.display = 'block';
    // 清掉上一次残留的百分比，避免新扫描刚弹出时先闪一下满格
    const fillEl = document.getElementById('progressFill');
    if (fillEl) fillEl.style.width = '0%';
    syncScanButtons();
    
    const url = fullScan ? '/api/start_scan?full=true' : '/api/start_scan';
    
    fetch(url, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'started' || data.status === 'already_scanning') {
                progressInterval = setInterval(checkProgress, 500);
            }
        })
        .catch(error => {
            console.error('扫描启动失败:', error);
            scanning = false;
            syncScanButtons();
            if (typeof showNotification === 'function') {
                showNotification('无法启动扫描', 'error');
            }
        });
}

// ===== 扫描完成后只换书架区，不整页刷新 =====
// 保留滚动位置、工具箱抽屉展开状态，避免整页重载的白屏和跳顶。
// 用当前 URL 重新请求首页（带分页/排序/筛选参数），只取其中的 .table-wrapper 换上去。
// 任何一步不顺利都返回 false，由调用方回退到整页刷新，不会停在半新半旧的状态。
async function refreshNovelList() {
    const oldWrap = document.querySelector('.table-wrapper');
    if (!oldWrap) return false;

    const prevScroll = window.scrollY;
    const oldMeta = document.getElementById('app-data');

    try {
        const fetchOpts = {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache' }
        };
        const parse = (h) => new DOMParser().parseFromString(h, 'text/html');

        const resp = await fetch(window.location.href, fetchOpts);
        if (!resp.ok) return false;
        let doc = parse(await resp.text());

        // 删书后总页数会变少，而桌面版后端没有页码越界纠正：
        // 停在超出范围的页码上会刷出空书架。这里退到新的最后一页再取一次，
        // 并用 replaceState 把地址栏一起改掉，后续操作不会继续带着越界页码。
        let newMeta = doc.getElementById('app-data');
        const newPages = parseInt((newMeta && newMeta.dataset.paginationPages) || '1', 10) || 1;
        const curPage = parseInt(new URLSearchParams(window.location.search).get('page') || '1', 10) || 1;
        if (curPage > newPages && newPages > 0) {
            const target = new URL(window.location.href);
            target.searchParams.set('page', newPages);
            const retry = await fetch(target.toString(), fetchOpts);
            if (!retry.ok) return false;
            doc = parse(await retry.text());
            history.replaceState(null, '', target.toString());
            newMeta = doc.getElementById('app-data');
        }

        const newWrap = doc.querySelector('.table-wrapper');
        if (!newWrap) return false;

        // 总页数可能变了（增删书）：meta 与全局变量一起更新，跳页才不会越界
        if (newMeta && oldMeta) {
            const pages = newMeta.dataset.paginationPages || '1';
            oldMeta.dataset.paginationPages = pages;
            window.paginationPages = parseInt(pages, 10) || 1;
        }

        oldWrap.replaceWith(newWrap);

        // 头部胶囊里的「共 N 本小说」
        const newCount = doc.querySelector('.count-info');
        const curCount = document.querySelector('.count-info');
        if (newCount && curCount) curCount.innerHTML = newCount.innerHTML;

        // 筛选提示条上的「共 N 本」（只在有筛选时存在）
        const newNotice = doc.querySelector('.filter-notice');
        const curNotice = document.querySelector('.filter-notice');
        if (newNotice && curNotice) curNotice.replaceWith(newNotice);

        // 新 DOM 需要重新跑一遍：书名格式化/高亮、分页输入框、列表区那几处直接绑定的事件
        if (typeof formatNovelTitlesAndHighlight === 'function') formatNovelTitlesAndHighlight();
        if (typeof initPagination === 'function') initPagination(window.paginationPages);
        if (typeof window.bindListInteractions === 'function') window.bindListInteractions();

        // 回到原来的滚动位置（新列表更短时浏览器会自动夹到底部）
        window.scrollTo(0, prevScroll);
        return true;
    } catch (err) {
        console.error('局部刷新书架失败，将回退整页刷新:', err);
        return false;
    }
}

// 检查进度
function checkProgress() {
    fetch('/api/scan_progress')
        .then(response => response.json())
        .then(data => {
            updateProgressUI(data);
            
            if (data.status === 'completed' || data.status === 'error') {
                clearInterval(progressInterval);
                progressInterval = null;
                scanning = false;

                const scanBtn = document.getElementById('scanBtn');
                const scanFullBtn = document.getElementById('scanFullBtn');
                if (scanBtn) scanBtn.disabled = false;
                if (scanFullBtn) scanFullBtn.disabled = false;

                syncScanButtons();

                if (data.status === 'completed') {
                    // 后端 message 里已经写好了「新增 3 本, 更新 2 本」这类明细，直接拿来当提示
                    if (typeof showNotification === 'function') {
                        showNotification(data.message || '扫描完成', 'success');
                    }
                    // 只换书架区，不整页刷新；失败才回退（延迟一点让提示先出来）
                    refreshNovelList().then(function (ok) {
                        if (!ok) setTimeout(() => window.location.reload(), 600);
                    });
                } else if (typeof showNotification === 'function') {
                    showNotification(data.message || '扫描出错', 'error');
                }

                // 进度条挂在「扫描管理」抽屉里，容器默认 display:none。
                // 以前扫完是整页 reload，靠重新渲染复位；改成局部刷新书架后
                // 没人替它复位，就会一直卡在抽屉里。这里自己收，留出时间看结果。
                hideProgress(data.status === 'completed' ? 1000 : 3000);
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
        // 只增不减：不同阶段 total 会变化，避免百分比倒退造成视觉抖动
        displayedProgress = Math.max(displayedProgress, data.percentage || 0);
        progressFill.style.width = displayedProgress + '%';
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

// 收起进度条（扫描结束/出错后调用）
// delay 用来让「100% / 扫描完成！」多停留一会儿再收
function hideProgress(delay = 1000) {
    setTimeout(() => {
        // 这期间用户又点了扫描：别把刚弹出来的新进度条藏掉
        if (scanning) return;
        const progressContainer = document.getElementById('progressContainer');
        if (progressContainer) progressContainer.style.display = 'none';
        const progressFill = document.getElementById('progressFill');
        if (progressFill) progressFill.style.width = '0%';
        displayedProgress = 0;
    }, delay);
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

// ===== 每日推荐：换一本（移植自 Docker 版） =====
// 与 Docker 版的差异：桌面版没有 SVG 图标库（用 emoji 代替），
// 也没有封面图（novel 里没有 cover_url），所以卡片是单列、无封面块。
const RandomNovel = (function () {
    let currentWorkId = '';
    let loading = false;

    const el = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatWordCount(count) {
        const n = parseInt(count, 10) || 0;
        if (!n) return '';
        return n >= 10000 ? (n / 10000).toFixed(1) + '万字' : n + '字';
    }

    // 与服务端 templates/_random_card.html 保持一致，改一边要同步另一边
    function buildRandomCardHTML(n) {
        const meta = [];
        meta.push(`<span class="random-meta-item">✍ ${escapeHtml(n.author || '未知作者')}</span>`);
        if (n.site && n.site !== '未知网站') {
            meta.push(`<span class="random-meta-item">🌐 ${escapeHtml(n.site)}</span>`);
        }
        const wc = formatWordCount(n.word_count);
        if (wc) meta.push(`<span class="random-meta-item">📄 ${wc}</span>`);
        if (n.progress) meta.push(`<span class="random-meta-item">📚 ${escapeHtml(n.progress)}</span>`);
        if (n.publish_date && n.publish_date !== '未知') {
            meta.push(`<span class="random-meta-item">📅 ${escapeHtml(n.publish_date)}</span>`);
        }

        const tagList = n.tags || [];
        const tags = tagList.slice(0, 8).map(t =>
            `<a href="?tag=${encodeURIComponent(t)}" class="tag-badge">${escapeHtml(t)}</a>`
        ).join('');
        const moreTags = tagList.length > 8
            ? `<span class="tag-badge tag-more">+${tagList.length - 8}</span>`
            : '';

        const intro = n.intro
            ? `<div class="random-intro-label">📖 简介 / 试读</div>
               <div class="random-intro">${escapeHtml(n.intro)}</div>`
            : `<div class="random-intro random-intro-empty">这本书没有可显示的简介，点开看看正文吧。</div>`;

        // 封面：有真图显示图；没有则「占位底图 + 书名首字」（与模板保持一致）
        const initial = escapeHtml((n.title || '书').slice(0, 1));
        const cover = n.cover_url
            ? `<div class="random-cover" data-initial="${initial}">
                   <img src="${escapeHtml(n.cover_url)}" alt="${escapeHtml(n.title)} 封面" loading="lazy" referrerpolicy="no-referrer"
                        onerror="var p=this.parentElement;if(!p.dataset.fb){p.dataset.fb=1;p.classList.add('random-cover-empty');p.textContent=p.dataset.initial;}">
               </div>`
            : `<div class="random-cover random-cover-empty" data-initial="${initial}">
                   <span class="random-cover-initial">${initial}</span>
               </div>`;

        return `
        <div class="random-card" data-work-id="${escapeHtml(n.work_id)}">
            ${cover}
            <div class="random-card-main">
                <h4 class="random-title">
                    <a href="${escapeHtml(n.detail_url)}">${escapeHtml(n.title)}</a>
                </h4>
                <div class="random-meta">${meta.join('')}</div>
                ${tags ? `<div class="random-tags">${tags}${moreTags}</div>` : ''}
            </div>
            <div class="random-intro-wrap">${intro}</div>
            <div class="random-card-actions">
                <a href="${escapeHtml(n.detail_url)}" class="random-btn">📄 查看详情</a>
                <a href="${escapeHtml(n.read_url)}" class="random-btn random-btn-primary">📖 开始阅读</a>
                <a href="javascript:void(0);" class="random-btn rc-open-file" data-file-path="${escapeHtml(n.file_path)}">📝 打开文件</a>
                ${n.has_images ? `<a href="javascript:void(0);" class="random-btn rc-open-folder" data-folder="${escapeHtml(n.image_folder)}">📁 打开文件夹</a>` : ''}
            </div>
        </div>`;
    }

    function render(novel) {
        const body = el('randomCardBody');
        if (!body || !novel) return;
        body.innerHTML = buildRandomCardHTML(novel);
        currentWorkId = novel.work_id || '';
    }

    function swap() {
        if (loading) return;
        const btn = el('randomRefreshBtn');
        const body = el('randomCardBody');
        if (!body) return;

        loading = true;
        if (btn) {
            btn.disabled = true;
            btn.textContent = '抽书中...';
        }
        body.classList.add('swapping');

        const params = new URLSearchParams();
        if (currentWorkId) params.set('exclude', currentWorkId);

        fetch('/api/random_novel?' + params.toString(), {
            headers: { 'Accept': 'application/json' }
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) throw new Error(data.message || '获取失败');
                render(data.novel);
            })
            .catch(err => {
                console.error('换一本失败:', err);
                if (typeof showNotification === 'function') {
                    showNotification('换一本失败，请重试', 'error');
                }
            })
            .finally(() => {
                loading = false;
                body.classList.remove('swapping');
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🔄 换一本';
                }
            });
    }

    // 打开配图文件夹：复用详情页同一个接口
    function openFolder(folder) {
        if (!folder) return;
        fetch('/api/media/open_folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder: folder })
        })
            .then(r => r.json())
            .then(data => {
                if (typeof showNotification !== 'function') return;
                if (data.success) {
                    showNotification('✅ 文件夹已打开', 'success');
                } else {
                    showNotification('打开失败：' + (data.message || '未知错误'), 'error');
                }
            })
            .catch(err => {
                console.error('打开文件夹失败:', err);
                if (typeof showNotification === 'function') {
                    showNotification('打开失败：' + err.message, 'error');
                }
            });
    }

    function init() {
        const section = el('randomSection');
        if (!section) return;

        // 记住首屏那本的 work_id，这样第一次「换一本」不会重复抽到它
        const card = section.querySelector('.random-card');
        if (card) currentWorkId = card.getAttribute('data-work-id') || '';

        const btn = el('randomRefreshBtn');
        if (btn) btn.addEventListener('click', swap);

        // 「打开文件 / 打开文件夹」用事件委托：「换一本」会整体替换卡片内容，
        // 直接给按钮绑事件会在换卡后失效
        section.addEventListener('click', function (e) {
            const fileBtn = e.target.closest('.rc-open-file');
            if (fileBtn) {
                e.preventDefault();
                const path = fileBtn.getAttribute('data-file-path');
                if (path && typeof openFile === 'function') openFile(path);
                return;
            }

            const folderBtn = e.target.closest('.rc-open-folder');
            if (folderBtn) {
                e.preventDefault();
                openFolder(folderBtn.getAttribute('data-folder'));
            }
        });
    }

    return { init, swap, render, buildRandomCardHTML };
})();

document.addEventListener('DOMContentLoaded', function () {
    RandomNovel.init();
});

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