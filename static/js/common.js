// ============================================
// common.js - 通用功能模块
// ============================================

(function() {
    'use strict';

    // ============================================
    // CSRF 保护：写请求自动带 X-CSRF-Token
    // ============================================
    const nativeFetch = window.fetch.bind(window);
    let csrfTokenPromise = null;

    function getCsrfToken() {
        if (!csrfTokenPromise) {
            csrfTokenPromise = nativeFetch('/api/csrf-token')
                .then(resp => resp.json())
                .then(data => data.csrf_token || '')
                .catch(() => '');
        }
        return csrfTokenPromise;
    }

    window.fetch = function(input, init) {
        init = init || {};
        const method = String(init.method || (input && input.method) || 'GET').toUpperCase();

        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            return getCsrfToken().then(token => {
                if (token) {
                    const headers = new Headers(init.headers || {});
                    if (!headers.has('X-CSRF-Token')) {
                        headers.set('X-CSRF-Token', token);
                    }
                    init = Object.assign({}, init, {headers});
                }
                return nativeFetch(input, init);
            });
        }

        return nativeFetch(input, init);
    };

    // ============================================
    // 1. 主题管理
    // ============================================

    // 根据系统主题判断
    function getSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // 应用主题（通用）
    function applyTheme(theme) {
        const body = document.body;
        if (theme === 'light') {
            body.classList.add('light-mode');
            body.classList.remove('dark-mode');
        } else {
            body.classList.add('dark-mode');
            body.classList.remove('light-mode');
        }
    }

    // 从服务器获取并应用主题
    function loadAndApplyTheme() {
        fetch('/config/get')
            .then(res => res.json())
            .then(config => {
                let theme = config.theme || 'dark';
                if (theme === 'auto') {
                    theme = getSystemTheme();
                }
                localStorage.setItem('theme', theme);
                applyTheme(theme);
            })
            .catch(err => {
                console.error('获取主题配置失败:', err);
                applyTheme('dark');
            });
    }

    // 监听系统主题变化
    function watchSystemTheme() {
        const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
        darkModeQuery.addEventListener('change', () => {
            fetch('/config/get')
                .then(res => res.json())
                .then(config => {
                    if (config.theme === 'auto') {
                        const theme = getSystemTheme();
                        applyTheme(theme);
                    }
                })
                .catch(err => console.error('检查主题配置失败:', err));
        });
    }


    // ============================================
    // 2. 通知系统（增强版）
    // ============================================

    function showNotification(message, type = 'info') {
        // 检查是否已有通知容器
        let container = document.getElementById('notificationContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notificationContainer';
            container.className = 'notification-container';
            document.body.appendChild(container);
            
            // 添加样式（如果还没有）
            if (!document.getElementById('notificationStyles')) {
                const style = document.createElement('style');
                style.id = 'notificationStyles';
                style.textContent = `
                    .notification-container {
                        position: fixed;
                        top: 20px;
                        right: 20px;
                        z-index: 9999;
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                        max-width: 400px;
                    }
                    .notification {
                        padding: 12px 20px;
                        border-radius: 8px;
                        color: white;
                        font-size: 14px;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                        animation: slideIn 0.3s ease;
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        gap: 10px;
                    }
                    .notification.success { background: #48bb78; }
                    .notification.error { background: #f56565; }
                    .notification.warning { background: #ed8936; }
                    .notification.info { background: #4299e1; }
                    
                    @keyframes slideIn {
                        from { transform: translateX(100%); opacity: 0; }
                        to { transform: translateX(0); opacity: 1; }
                    }
                    @keyframes slideOut {
                        from { transform: translateX(0); opacity: 1; }
                        to { transform: translateX(100%); opacity: 0; }
                    }
                `;
                document.head.appendChild(style);
            }
        }
        
        const icons = { 
            success: '✅', 
            error: '❌', 
            warning: '⚠️',
            info: 'ℹ️' 
        };
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        const iconSpan = document.createElement('span');
        iconSpan.textContent = icons[type] || 'ℹ️';
        const messageSpan = document.createElement('span');
        messageSpan.textContent = message;
        notification.appendChild(iconSpan);
        notification.appendChild(messageSpan);
        notification.onclick = () => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        };
        
        container.appendChild(notification);
        
        // 自动消失
        setTimeout(() => {
            if (notification.parentNode) {
                notification.style.animation = 'slideOut 0.3s ease';
                setTimeout(() => notification.remove(), 300);
            }
        }, 4000);
    }

    // ============================================
    // 3. 打开文件（通用）
    // ============================================

    function openFile(filePath) {
        const loadingOverlay = document.getElementById('loadingOverlay');
        if (loadingOverlay) loadingOverlay.style.display = 'flex';
        
        // 如果 filePath 包含 % 说明已经编码，否则进行编码
        let encodedPath = filePath;
        if (!filePath.includes('%')) {
            encodedPath = encodeURIComponent(filePath);
        }
        
        fetch(`/open_file_ajax/${encodedPath}`, {method: 'POST'})
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (loadingOverlay) loadingOverlay.style.display = 'none';
                if (data.success) {
                    showNotification('文件已打开', 'success');
                } else {
                    showNotification(`打开失败：${data.error || '未知错误'}`, 'error');
                }
            })
            .catch(error => {
                if (loadingOverlay) loadingOverlay.style.display = 'none';
                console.error('打开文件失败:', error);
                showNotification(`请求失败：${error.message}`, 'error');
            });
    }


    // ============================================
    // 3. 加载动画
    // ============================================

    function showLoading(show) {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.style.display = show ? 'flex' : 'none';
        }
    }

    // ============================================
    // 4. 轮播图（背景图片轮播）
    // ============================================

    const CAROUSEL_CONFIG = {
        imageCount: 50,
        imagePrefix: '/static/images/header-bg-',
        imageSuffix: '.webp',
        intervalTime: 8000,
        transitionDuration: 1200,
        borderRadius: '15px'
    };

    let cachedImages = null;
    let currentImageIndex = -1;
    let slideshowInterval = null;
    let isTransitioning = false;

    // 生成候选图片列表
    function generateCandidateImages() {
        const images = [];
        for (let i = 1; i <= CAROUSEL_CONFIG.imageCount; i++) {
            images.push(`${CAROUSEL_CONFIG.imagePrefix}${i}${CAROUSEL_CONFIG.imageSuffix}`);
        }
        return images;
    }

    // 检查单张图片是否存在
    function imageExists(url) {
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => resolve(true);
            img.onerror = () => resolve(false);
            img.src = url;
        });
    }

    // 批量检测图片存在性
    async function getExistingImages() {
        if (cachedImages) return cachedImages;
        
        const candidates = generateCandidateImages();
        const existing = [];
        
        // 分批检测，避免同时发送太多请求
        const batchSize = 10;
        for (let i = 0; i < candidates.length; i += batchSize) {
            const batch = candidates.slice(i, i + batchSize);
            const results = await Promise.all(batch.map(async (url) => {
                if (await imageExists(url)) return url;
                return null;
            }));
            existing.push(...results.filter(url => url !== null));
        }
        
        cachedImages = existing;
        return existing;
    }

    // 创建背景容器
    function getBackgroundContainer(header) {
        let container = header.querySelector('.header-bg-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'header-bg-container';
            container.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                z-index: 0;
                border-radius: ${CAROUSEL_CONFIG.borderRadius};
            `;
            
            const bg1 = document.createElement('div');
            const bg2 = document.createElement('div');
            bg1.className = 'header-bg-layer header-bg-layer-1';
            bg2.className = 'header-bg-layer header-bg-layer-2';
            bg1.style.cssText = bg2.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                transition: opacity ${CAROUSEL_CONFIG.transitionDuration}ms ease-in-out;
                opacity: 0;
                border-radius: ${CAROUSEL_CONFIG.borderRadius};
            `;
            
            container.appendChild(bg1);
            container.appendChild(bg2);
            
            if (getComputedStyle(header).position === 'static') {
                header.style.position = 'relative';
            }
            header.style.borderRadius = CAROUSEL_CONFIG.borderRadius;
            header.style.overflow = 'hidden';
            
            header.insertBefore(container, header.firstChild);
            
            header.bgLayers = {
                container: container,
                layer1: bg1,
                layer2: bg2,
                activeLayer: 1
            };
        }
        return header.bgLayers;
    }

    // 淡入背景图片
    function fadeInBackground(layers, imageUrl, targetLayer) {
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                targetLayer.style.backgroundImage = `url('${imageUrl}')`;
                setTimeout(() => {
                    targetLayer.style.opacity = '1';
                    setTimeout(resolve, CAROUSEL_CONFIG.transitionDuration);
                }, 50);
            };
            img.onerror = () => {
                console.error(`图片加载失败: ${imageUrl}`);
                resolve();
            };
            img.src = imageUrl;
        });
    }

    // 切换背景图片
    async function switchBackground(layers, newImageUrl) {
        if (isTransitioning) return;
        isTransitioning = true;
        
        const activeLayer = layers.activeLayer === 1 ? layers.layer1 : layers.layer2;
        const inactiveLayer = layers.activeLayer === 1 ? layers.layer2 : layers.layer1;
        
        const img = new Image();
        img.onload = () => {
            inactiveLayer.style.backgroundImage = `url('${newImageUrl}')`;
            inactiveLayer.style.opacity = '0';
            void inactiveLayer.offsetHeight;
            activeLayer.style.opacity = '0';
            inactiveLayer.style.opacity = '1';
            layers.activeLayer = layers.activeLayer === 1 ? 2 : 1;
            setTimeout(() => {
                isTransitioning = false;
            }, CAROUSEL_CONFIG.transitionDuration);
        };
        img.onerror = () => {
            console.error(`图片加载失败: ${newImageUrl}`);
            isTransitioning = false;
        };
        img.src = newImageUrl;
    }

    // 获取下一张随机图片
    function getNextRandomImage(images) {
        if (images.length === 0) return null;
        if (images.length === 1) return images[0];
        let newIndex;
        do {
            newIndex = Math.floor(Math.random() * images.length);
        } while (newIndex === currentImageIndex);
        currentImageIndex = newIndex;
        return images[currentImageIndex];
    }

    // 启动幻灯片
    function startSlideshow(header, images, intervalTime = CAROUSEL_CONFIG.intervalTime) {
        if (slideshowInterval) {
            clearInterval(slideshowInterval);
        }
        const layers = getBackgroundContainer(header);
        slideshowInterval = setInterval(async () => {
            if (!header.isConnected) {
                clearInterval(slideshowInterval);
                return;
            }
            const nextImage = getNextRandomImage(images);
            if (nextImage) {
                await switchBackground(layers, nextImage);
            }
        }, intervalTime);
    }

    // 停止幻灯片
    

    // 初始化轮播图
    async function initCarousel(selector = '.header, .tag-manager-header', options = {}) {
        const {
            autoSlideshow = true,
            intervalTime = CAROUSEL_CONFIG.intervalTime
        } = options;
        
        const header = document.querySelector(selector);
        if (!header) {
            console.log('未找到轮播图容器');
            return;
        }
        
        try {
            const images = await getExistingImages();
            if (images.length > 0) {
                const layers = getBackgroundContainer(header);
                const randomImage = images[Math.floor(Math.random() * images.length)];
                currentImageIndex = images.indexOf(randomImage);
                
                const targetLayer = layers.layer1;
                layers.activeLayer = 1;
                await fadeInBackground(layers, randomImage, targetLayer);
                
                if (autoSlideshow) {
                    startSlideshow(header, images, intervalTime);
                }
                console.log(`轮播图已启动，共 ${images.length} 张图片`);
            } else {
                console.log('未找到背景图片');
            }
        } catch (error) {
            console.error('初始化轮播图失败:', error);
        }
    }

    // 手动切换到下一张
    

    // ============================================
    // 5. 折叠/展开卡片
    // ============================================

    function toggleCard(headerElement) {
        const card = headerElement.closest('.config-card');
        if (card) {
            card.classList.toggle('collapsed');
        }
    }

    // ============================================
    // 7. 导出/导入配置
    // ============================================

    function exportConfig(data, filename = 'config.json') {
        const dataStr = JSON.stringify(data, null, 2);
        const blob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        showNotification('导出成功', 'success');
    }

    function importConfig(callback) {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = function(e) {
            const file = e.target.files[0];
            const reader = new FileReader();
            reader.onload = function(evt) {
                try {
                    const data = JSON.parse(evt.target.result);
                    if (callback) callback(data);
                } catch (error) {
                    showNotification('导入失败: 文件格式错误', 'error');
                }
            };
            reader.readAsText(file);
        };
        input.click();
    }

    // ============================================
    // 8. 解析逗号分隔字符串
    // ============================================

    function parseCommaString(str) {
        if (!str) return [];
        return str.split(',').map(s => s.trim()).filter(s => s);
    }

    // ============================================
    // 9. 转义HTML
    // ============================================

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ============================================
    // 10. 暴露全局API
    // ============================================

    // 主题
    window.getSystemTheme = getSystemTheme;
    window.applyTheme = applyTheme;
    window.loadAndApplyTheme = loadAndApplyTheme;
    window.watchSystemTheme = watchSystemTheme;

    // 通知 & 加载 & 文件
    window.showNotification = showNotification;
    window.showLoading = showLoading;
    window.openFile = openFile;  // 只保留这一个

    // 轮播图
    window.initCarousel = initCarousel;
    
    

    // 其他
    window.toggleCard = toggleCard;
    // window.openFile = openFile;  // ← 删除这一行（重复了）
    window.exportConfig = exportConfig;
    window.importConfig = importConfig;
    window.parseCommaString = parseCommaString;
    window.escapeHtml = escapeHtml;

    console.log('✅ common.js 已加载');

})();