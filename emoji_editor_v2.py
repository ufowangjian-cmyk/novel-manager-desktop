import json
import os
import sys
import tkinter as tk
import threading 
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
import re
from pathlib import Path
import ctypes
from PIL import Image, ImageTk, ImageSequence

class EmojiEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("表情映射表编辑器 - 完整版")
        # DPI 感知已在 main() 里、创建窗口之前开启；这里按屏幕缩放放大初始窗口，
        # 否则高分屏下 1300x700 物理像素的窗口会比以前显得更小
        self.dpi_scale = 1.0
        try:
            dpi_scale = self.root.winfo_fpixels('1i') / 96.0
            if 1.0 <= dpi_scale <= 4.0:
                self.dpi_scale = dpi_scale
        except Exception:
            pass
        self.root.geometry(f"{int(1300 * self.dpi_scale)}x{int(700 * self.dpi_scale)}")
        self.max_cache_size = 50
        self.gif_frames_cache = None
        self.gif_current_frame = 0
        self._select_timer = None
        self.gif_running = False
        self.preview_animation_id = None
        self._resize_timer = None
        self._search_timer = None
        self._current_load_key = None  # 跟踪当前加载的图片
        self.image_cache = {}           # 原始图片数据缓存
        self.scaled_cache = {}          # 缩放后的 PhotoImage 缓存（新增）
        self.MAX_SCALED_CACHE = 20      # 缩放缓存最大数量
        self._checker_tile = None       # 棋盘格小图（只生成一次）
        self._checker_photo = None      # 铺满画布的棋盘格底图
        self._checker_size = (0, 0)     # 底图对应的画布尺寸

        # ========== 字体修复 ==========
        import tkinter.font as tkfont
        
        available_fonts = list(tkfont.families())
        available_fonts_lower = [f.lower() for f in available_fonts]
        
        font_priorities = [
            ('Microsoft YaHei UI', '微软雅黑'),
            ('Microsoft YaHei', '微软雅黑'),
            ('微软雅黑', '微软雅黑'),
            ('Segoe UI', 'Segoe UI'),
            ('TkDefaultFont', '默认字体')
        ]
        
        font_name = 'TkDefaultFont'
        for check_name, display_name in font_priorities:
            if check_name in available_fonts or check_name.lower() in available_fonts_lower:
                try:
                    idx = available_fonts_lower.index(check_name.lower())
                    font_name = available_fonts[idx]
                except:
                    font_name = check_name
                print(f"使用字体: {font_name}")
                break
        
        self.default_font = (font_name, 10)
        self.small_font = (font_name, 9)
        self.bold_font = (font_name, 10, 'bold')
        self.text_font = (font_name, 10)
        
        self.root.option_add('*Font', self.default_font)
        self.root.option_add('*TLabel*Font', self.default_font)
        self.root.option_add('*TButton*Font', self.default_font)
        self.root.option_add('*TEntry*Font', self.default_font)
        self.root.option_add('*Text*Font', self.text_font)
        self.root.option_add('*Listbox*Font', self.default_font)
        
        style = ttk.Style()
        try:
            style.theme_use('vista')
        except:
            pass
        
        style.configure('.', font=self.default_font)
        style.configure('TLabel', font=self.default_font)
        style.configure('TButton', font=self.default_font)
        style.configure('TEntry', font=self.default_font)
        style.configure('Treeview', font=self.default_font, rowheight=int(28 * self.dpi_scale))
        style.configure('Treeview.Heading', font=self.bold_font)
        
        # ========== 数据初始化 ==========
        self.data = []
        self.current_file_path = None
        self.emojis_folder_path = None
        self.current_preview_image = None
        
        self.setup_ui()
        
        # 绑定快捷键
        self.root.bind('<Control-o>', lambda e: self.load_json())
        self.root.bind('<Control-s>', lambda e: self.save_json())
        self.root.bind('<Control-e>', lambda e: self.export_excel())
        # 只绑在表格上：绑在 root（等价于整个窗口）上，在搜索框里按 Delete 也会触发删除
        self.tree.bind('<Delete>', lambda e: self.delete_selected())
    
    def _cleanup_cache(self):
        """清理旧缓存"""
        if len(self.image_cache) > self.max_cache_size:
            keys_to_remove = list(self.image_cache.keys())[:len(self.image_cache) // 2]
            for key in keys_to_remove:
                try:
                    del self.image_cache[key]
                except KeyError:
                    pass

    def setup_ui(self):
        # 顶部工具栏
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        row1 = ttk.Frame(toolbar)
        row1.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        ttk.Button(row1, text="📂 打开 JSON", command=self.load_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="💾 保存 JSON", command=self.save_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="📊 导出 Excel", command=self.export_excel).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="📖 导入 Excel", command=self.import_excel).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(row1, text="📁 设置表情文件夹", command=self.set_emojis_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="🔍 对比文件夹", command=self.compare_with_folder).pack(side=tk.LEFT, padx=2)
        
        row2 = ttk.Frame(toolbar)
        row2.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        ttk.Button(row2, text="➕ 添加表情", command=self.add_emoji).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="✏️ 编辑关键词", command=self.edit_keywords).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="🗑️ 删除选中", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(row2, text="🔍 检查重复", command=self.check_duplicates).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="📈 统计信息", command=self.show_stats).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="🔄 刷新", command=self.refresh_table).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="🗑️ 清理孤立", command=self.find_orphan_keywords).pack(side=tk.LEFT, padx=2)
        
        # 搜索框
        search_frame = ttk.Frame(self.root)
        search_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        ttk.Label(search_frame, text="搜索:").pack(side=tk.LEFT, padx=2)
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self._on_search_change())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(search_frame, text="(搜索文件名或关键词)", font=self.small_font).pack(side=tk.LEFT, padx=5)
        
        self.status_label = ttk.Label(search_frame, text="", foreground="gray")
        self.status_label.pack(side=tk.RIGHT, padx=10)
        
        # 主内容区域
        main_panel = ttk.Frame(self.root)
        main_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧表格
        table_frame = ttk.Frame(main_panel)
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        columns = ('filename', 'keywords', 'count', 'status')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=20)
        
        self.tree.heading('filename', text='文件名', command=lambda: self.sort_by('filename'))
        self.tree.heading('keywords', text='关键词列表', command=lambda: self.sort_by('keywords'))
        self.tree.heading('count', text='关键词数量', command=lambda: self.sort_by('count'))
        self.tree.heading('status', text='状态', command=lambda: self.sort_by('status'))
        
        self.tree.column('filename', width=int(220 * self.dpi_scale))
        self.tree.column('keywords', width=int(500 * self.dpi_scale))
        self.tree.column('count', width=int(80 * self.dpi_scale), anchor='center')
        self.tree.column('status', width=int(100 * self.dpi_scale), anchor='center')
        
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        # 右侧预览面板
        preview_frame = ttk.Frame(main_panel, width=int(250 * self.dpi_scale))
        preview_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        preview_frame.pack_propagate(False)
        
        ttk.Label(preview_frame, text="📷 图片预览", font=self.bold_font).pack(anchor=tk.W, pady=(0, 10))
        
        self.preview_info_label = ttk.Label(preview_frame, text="", font=self.small_font, foreground="gray")
        self.preview_info_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.preview_canvas = tk.Canvas(preview_frame, bg='#f0f0f0', relief=tk.SUNKEN, bd=1)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        preview_controls = ttk.Frame(preview_frame)
        preview_controls.pack(fill=tk.X, pady=10)
        
        ttk.Button(preview_controls, text="🔄 刷新预览", command=self.refresh_preview).pack(side=tk.LEFT, padx=2)
        ttk.Button(preview_controls, text="📂 打开文件", command=self.open_preview_file).pack(side=tk.LEFT, padx=2)
        
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        self.tree.bind('<Double-Button-1>', lambda e: self.edit_keywords())
        self.preview_canvas.bind('<Configure>', self.on_canvas_resize)
        
        self.status_bar = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def _on_search_change(self):
        """搜索防抖"""
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(300, self.filter_table)
    
    def filter_table(self):
        """过滤表格"""
        self._search_timer = None
        self.refresh_table()
    
    def match_search(self, item):
        """检查项目是否匹配搜索"""
        search = self.search_var.get().strip().lower()
        if not search:
            return True
        if search in item['filename'].lower():
            return True
        for kw in item['keywords']:
            if search in kw.lower():
                return True
        return False
    
    def refresh_table(self):
        """刷新表格"""
        selected = self.tree.selection()
        selected_filename = None
        if selected:
            try:
                selected_filename = self.tree.item(selected[0])['values'][0]
            except:
                pass
        
        self.tree.configure(selectmode='none')
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        visible_count = 0
        for item in self.data:
            if not self.match_search(item):
                continue
            
            visible_count += 1
            status = "✅ 正常"
            if self.emojis_folder_path and not item.get('file_exists', True):
                status = "⚠️ 文件缺失"
            elif len(item['keywords']) == 0:
                status = "❌ 无关键词"
            
            self.tree.insert('', tk.END, values=(
                item['filename'],
                '，'.join(item['keywords']),
                len(item['keywords']),
                status
            ))
        
        if selected_filename:
            for item in self.tree.get_children():
                if self.tree.item(item)['values'][0] == selected_filename:
                    self.tree.selection_set(item)
                    self.tree.see(item)
                    break
        
        self.tree.configure(selectmode='extended')
        
        total_kw = sum(len(item['keywords']) for item in self.data)
        empty = sum(1 for item in self.data if not item['keywords'])
        
        search_text = self.search_var.get().strip()
        if search_text:
            self.status_label.config(text=f"搜索: {visible_count}/{len(self.data)} 文件 | {total_kw} 关键词 | {empty} 无关键词")
        else:
            self.status_label.config(text=f"总计: {len(self.data)} 文件 | {total_kw} 关键词 | {empty} 无关键词")
    
    @staticmethod
    def _file_cache_key(file_path):
        """基于「路径 + 修改时间」的缓存 key；文件被改动后自动失效"""
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            mtime = 0
        return f"{file_path}|{mtime}"
    
    def show_preview(self, filename):
        """显示预览"""
        self._stop_gif_animation()
        
        if not self.emojis_folder_path:
            self._show_preview_message("请先设置表情文件夹")
            return
        
        file_path = os.path.join(self.emojis_folder_path, filename)
        if not os.path.exists(file_path):
            self._show_preview_message("文件不存在")
            return
        
        try:
            cache_key = self._file_cache_key(file_path)
            
            # 检查缓存
            if cache_key in self.image_cache:
                self._display_cached_image(self.image_cache[cache_key])
                return
            
            # 异步加载
            self._current_load_key = cache_key
            thread = threading.Thread(
                target=lambda: self._load_image_in_thread(file_path, cache_key),
                daemon=True
            )
            thread.start()
            
        except Exception as e:
            self._show_preview_message(f"加载失败:\n{str(e)}", is_error=True)
    
    def _load_image_in_thread(self, file_path, cache_key):
        """在后台线程加载图片 - 保持透明背景"""
        try:
            img = Image.open(file_path)
            file_size = os.path.getsize(file_path)
            is_animated = getattr(img, 'is_animated', False)
            
            if is_animated:
                frames = []
                for i, frame in enumerate(ImageSequence.Iterator(img)):
                    if i >= 15:
                        break
                    # GIF：保留原始模式，不转换（GIF支持透明）
                    # 只有P模式且需要透明时才转换
                    if frame.mode == 'P' and 'transparency' in frame.info:
                        frame = frame.convert('RGBA')
                    frames.append(frame.copy())
                
                img_data = {
                    'type': 'gif',
                    'frames': frames,
                    'info': img.info,
                    'file_path': file_path,
                    'cache_key': cache_key,
                    'size': (img.width, img.height)
                }
            else:
                # 静态图片：保留原始模式（RGBA保持透明）
                # 不要强制转换为RGB
                if img.mode == 'P':
                    # 调色板模式，尝试转换保留透明
                    if 'transparency' in img.info:
                        img = img.convert('RGBA')
                    else:
                        img = img.convert('RGB')
                # RGBA 模式保持原样，不转换
                
                img_data = {
                    'type': 'static',
                    'img': img.copy(),
                    'file_path': file_path,
                    'cache_key': cache_key,
                    'size': (img.width, img.height)
                }
            
            def update():
                if cache_key != self._current_load_key:
                    return
                
                info_text = f"{img.format} | {img_data['size'][0]}x{img_data['size'][1]} | {self.format_size(file_size)}"
                if is_animated:
                    info_text += f" | {len(frames)}帧"
                self.preview_info_label.config(text=info_text)
                
                self.image_cache[cache_key] = img_data
                self._cleanup_cache()
                self._display_cached_image(img_data)
            
            self.root.after(0, update)
            
        except Exception as e:
            self.root.after(0, lambda: self._show_preview_message(f"加载失败:\n{str(e)}", is_error=True))
        finally:
            try:
                img.close()
            except:
                pass
    
    
    def _display_cached_image(self, img_data):
        """显示缓存的图片 - 支持透明背景"""
        canvas_width = max(self.preview_canvas.winfo_width(), 30)
        canvas_height = max(self.preview_canvas.winfo_height(), 30)
        
        # 棋盘格只在画布尺寸变化时重建，并用独立 tag 保留（图片/文字统一用 "content" tag）
        self._draw_checkerboard(canvas_width, canvas_height)
        
        # 缓存 key 必须基于「文件路径+修改时间」；用 id() 会在对象被回收后复用同一 id，
        # 从而命中另一张图的缓存（串图）
        base_key = img_data['cache_key']
        scale_cache_key = f"{base_key}|{canvas_width}x{canvas_height}"
        
        if scale_cache_key in self.scaled_cache:
            cached = self.scaled_cache[scale_cache_key]
            self._apply_scaled_image(cached['photo'], cached['x'], cached['y'])
            return
        
        if img_data['type'] == 'static':
            img = img_data['img']
            scale = min(canvas_width / img.width, canvas_height / img.height, 1.0)
            new_width = max(int(img.width * scale), 1)
            new_height = max(int(img.height * scale), 1)
            
            def resize_in_thread():
                try:
                    # 使用合适的重采样方法
                    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img_resized)
                    
                    def apply():
                        x = (canvas_width - new_width) // 2
                        y = (canvas_height - new_height) // 2
                        
                        self.scaled_cache[scale_cache_key] = {
                            'photo': photo,
                            'x': x,
                            'y': y
                        }
                        self._evict_scaled_cache()
                        
                        self._apply_scaled_image(photo, x, y)
                    
                    self.root.after(0, apply)
                except Exception as e:
                    print(f"缩放失败: {e}")
            
            threading.Thread(target=resize_in_thread, daemon=True).start()
            
        else:
            self._play_gif_from_cache(
                img_data['frames'],
                img_data.get('info', {}),
                canvas_width,
                canvas_height,
                img_data
            )

    def _get_checker_tile(self):
        """生成 2x2 格的棋盘格小图（只生成一次）"""
        if self._checker_tile is None:
            cell = 16
            tile = Image.new('RGB', (cell * 2, cell * 2), '#ffffff')
            dark = Image.new('RGB', (cell, cell), '#dddddd')
            tile.paste(dark, (0, 0))
            tile.paste(dark, (cell, cell))
            self._checker_tile = tile
        return self._checker_tile
    
    def _draw_checkerboard(self, width, height):
        """铺棋盘格背景，让透明区域可见（按画布尺寸缓存，不再逐格画 Canvas 矩形）"""
        if self._checker_photo is not None and self._checker_size == (width, height):
            # 尺寸没变：底图还在就直接复用；万一被清掉了就补回来
            if not self.preview_canvas.find_withtag("checker"):
                self.preview_canvas.create_image(0, 0, anchor=tk.NW,
                                                 image=self._checker_photo, tags="checker")
                self.preview_canvas.tag_lower("checker")
            return
        
        tile = self._get_checker_tile()
        step = tile.width
        board = Image.new('RGB', (width, height), '#ffffff')
        for y in range(0, height, step):
            for x in range(0, width, step):
                board.paste(tile, (x, y))
        
        self._checker_photo = ImageTk.PhotoImage(board)
        self._checker_size = (width, height)
        self.preview_canvas.delete("checker")
        self.preview_canvas.create_image(0, 0, anchor=tk.NW,
                                         image=self._checker_photo, tags="checker")
        self.preview_canvas.tag_lower("checker")
    
    def _clear_canvas_content(self):
        """只清除图片/文字图层，保留棋盘格底图"""
        self.preview_canvas.delete("content")
    
    def _evict_scaled_cache(self):
        """缩放缓存超限时淘汰较早的条目，并保证最终不超上限"""
        while len(self.scaled_cache) > self.MAX_SCALED_CACHE:
            keys = list(self.scaled_cache.keys())
            for k in keys[:max(1, len(keys) // 2)]:
                del self.scaled_cache[k]
    
    def _apply_scaled_image(self, photo, x, y):
        """应用缩放后的图片（只清内容图层，保留棋盘格底图）"""
        self._clear_canvas_content()
        self.preview_canvas.create_image(x, y, anchor=tk.NW, image=photo, tags="content")
        self.current_preview_image = photo

    def _play_gif_from_cache(self, frames, info, canvas_width, canvas_height, img_data):
        """播放GIF - 优化版，预缩放所有帧"""
        if not frames:
            return
        
        img_width, img_height = frames[0].size
        scale = min(canvas_width / img_width, canvas_height / img_height, 1.0)
        new_width = max(int(img_width * scale), 1)
        new_height = max(int(img_height * scale), 1)
        x = (canvas_width - new_width) // 2
        y = (canvas_height - new_height) // 2
        
        # 生成GIF缩放缓存key（同样基于「文件路径+修改时间」，不能用 id()）
        gif_cache_key = f"{img_data['cache_key']}|gif|{new_width}x{new_height}"
        if gif_cache_key in self.scaled_cache:
            scaled_frames = self.scaled_cache[gif_cache_key]
        else:
            # 在后台线程缩放所有帧
            def scale_frames_in_thread():
                try:
                    scaled_frames = []
                    for frame in frames:
                        if scale != 1.0:
                            # 使用更快的缩放方法
                            frame = frame.resize((new_width, new_height), Image.Resampling.BICUBIC)
                        scaled_frames.append(ImageTk.PhotoImage(frame))
                    
                    def apply():
                        self.scaled_cache[gif_cache_key] = scaled_frames
                        self._evict_scaled_cache()
                        self._start_gif_animation(scaled_frames, info.get('duration', 100), x, y)
                    
                    self.root.after(0, apply)
                except Exception as e:
                    print(f"GIF缩放失败: {e}")
            
            threading.Thread(target=scale_frames_in_thread, daemon=True).start()
            return
        
        self._start_gif_animation(scaled_frames, info.get('duration', 100), x, y)

    def _start_gif_animation(self, frames, duration, x, y):
        """开始GIF动画"""
        self._stop_gif_animation()
        self.gif_frames_cache = frames
        self.gif_current_frame = 0
        self.gif_running = True
        self.gif_x = x
        self.gif_y = y
        
        def update_frame():
            if not self.gif_running or not self.gif_frames_cache:
                return
            
            frame = self.gif_frames_cache[self.gif_current_frame % len(self.gif_frames_cache)]
            self._clear_canvas_content()
            self.preview_canvas.create_image(self.gif_x, self.gif_y, anchor=tk.NW,
                                             image=frame, tags="content")
            self.current_preview_image = frame
            self.gif_current_frame += 1
            
            self.preview_animation_id = self.root.after(max(duration, 50), update_frame)
        
        update_frame()

    def _stop_gif_animation(self):
        """停止GIF动画"""
        self.gif_running = False
        if self.preview_animation_id:
            self.root.after_cancel(self.preview_animation_id)
            self.preview_animation_id = None
        self.gif_frames_cache = None

    def on_tree_select(self, event):
        """选择变化时更新预览 - 优化版"""
        self._stop_gif_animation()
        
        if self._select_timer:
            self.root.after_cancel(self._select_timer)
            self._select_timer = None
        
        selection = self.tree.selection()
        if not selection:
            self.clear_preview()
            return
        
        try:
            filename = self.tree.item(selection[0])['values'][0]
        except:
            return
        
        # 延迟100ms再加载，避免快速切换时反复加载
        self._select_timer = self.root.after(100, lambda: self._do_preview(filename))

    def _do_preview(self, filename):
        """实际执行预览加载"""
        self._select_timer = None
        self.show_preview(filename)

    def clear_preview(self):
        """清空预览 - 优化版"""
        self._stop_gif_animation()
        self.preview_info_label.config(text="")
        self._clear_canvas_content()
        canvas_width = max(self.preview_canvas.winfo_width(), 100)
        canvas_height = max(self.preview_canvas.winfo_height(), 100)
        self.preview_canvas.create_text(
            canvas_width // 2, canvas_height // 2,
            text="选中文件以预览", fill="gray", font=self.default_font, tags="content"
        )

    def on_canvas_resize(self, event):
        """画布大小变化 - 优化版"""
        if self._resize_timer:
            self.root.after_cancel(self._resize_timer)
        # 延迟300ms，避免频繁重绘
        self._resize_timer = self.root.after(300, self._delayed_resize)

    def _drop_scaled_cache(self, filename):
        """按「路径|修改时间」前缀精确清除某个文件的缩放缓存（不要用子串匹配文件名）"""
        if not self.emojis_folder_path:
            return
        prefix = f"{os.path.join(self.emojis_folder_path, filename)}|"
        for key in [k for k in self.scaled_cache if k.startswith(prefix)]:
            del self.scaled_cache[key]
    
    def _delayed_resize(self):
        """延迟重绘"""
        self._resize_timer = None
        selection = self.tree.selection()
        if selection and self.emojis_folder_path:
            filename = self.tree.item(selection[0])['values'][0]
            # 清除这个文件的缩放缓存，强制重新缩放
            self._drop_scaled_cache(filename)
            self.show_preview(filename)
    
    def refresh_preview(self):
        """手动刷新预览"""
        self._stop_gif_animation()
        selection = self.tree.selection()
        if selection and self.emojis_folder_path:
            filename = self.tree.item(selection[0])['values'][0]
            # 清除这个文件的缩放缓存，强制重新加载
            self._drop_scaled_cache(filename)
            # 清除原始缓存
            file_path = os.path.join(self.emojis_folder_path, filename)
            if os.path.exists(file_path):
                self.image_cache.pop(self._file_cache_key(file_path), None)
            self.show_preview(filename)

    def open_preview_file(self):
        """打开文件"""
        selection = self.tree.selection()
        if not selection or not self.emojis_folder_path:
            return
        filename = self.tree.item(selection[0])['values'][0]
        file_path = os.path.join(self.emojis_folder_path, filename)
        if os.path.exists(file_path):
            import subprocess
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', file_path])
            else:
                subprocess.run(['xdg-open', file_path])

    def _show_preview_message(self, message, is_error=False):
        """显示预览消息"""
        self.preview_info_label.config(text=message if not is_error else f"❌ {message}")
        self._clear_canvas_content()
        canvas_width = max(self.preview_canvas.winfo_width(), 100)
        canvas_height = max(self.preview_canvas.winfo_height(), 100)
        self.preview_canvas.create_text(
            canvas_width // 2, canvas_height // 2,
            text=message, fill="red" if is_error else "gray",
            font=self.default_font, tags="content"
        )    
   

    def format_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    # ========== 以下方法保持不变 ==========
    
    def set_emojis_folder(self):
        folder = filedialog.askdirectory(title="选择 emojis 文件夹")
        if folder:
            self.emojis_folder_path = folder
            self.update_status(f"已设置表情文件夹: {folder}")
            self.check_file_status()
            self.clear_preview()
    
    def check_file_status(self):
        if not self.emojis_folder_path or not self.data:
            return
        
        emoji_extensions = {'.gif', '.png', '.webp', '.jpg', '.jpeg'}
        existing_files = set()
        if os.path.exists(self.emojis_folder_path):
            for file in Path(self.emojis_folder_path).iterdir():
                if file.is_file() and file.suffix.lower() in emoji_extensions:
                    existing_files.add(file.name)
        
        for item in self.data:
            item['file_exists'] = item['filename'] in existing_files
        
        self.refresh_table()
    
    def compare_with_folder(self):
        if not self.emojis_folder_path:
            messagebox.showwarning("警告", "请先设置表情文件夹")
            return
        
        emoji_extensions = {'.gif', '.png', '.webp', '.jpg', '.jpeg'}
        folder_files = set()
        for file in Path(self.emojis_folder_path).iterdir():
            if file.is_file() and file.suffix.lower() in emoji_extensions:
                folder_files.add(file.name)
        
        mapped_files = set(item['filename'] for item in self.data)
        missing_files = folder_files - mapped_files
        orphan_files = mapped_files - folder_files
        
        result_msg = f"📊 对比结果：\n\n"
        result_msg += f"📁 文件夹中的文件: {len(folder_files)} 个\n"
        result_msg += f"📄 JSON 中已映射: {len(mapped_files)} 个\n\n"
        
        if missing_files:
            result_msg += f"❌ 遗漏的文件（文件夹有，JSON无）：{len(missing_files)} 个\n"
            for i, filename in enumerate(sorted(missing_files)[:20], 1):
                result_msg += f"   {i}. {filename}\n"
            result_msg += "\n"
        
        if orphan_files:
            orphan_keywords = 0
            for item in self.data:
                if item['filename'] in orphan_files:
                    orphan_keywords += len(item['keywords'])
            result_msg += f"⚠️ 孤立的映射（JSON有，文件夹无）：{len(orphan_files)} 个\n"
            result_msg += f"   涉及 {orphan_keywords} 个关键词\n"
            for i, filename in enumerate(sorted(orphan_files)[:20], 1):
                result_msg += f"   {i}. {filename}\n"
            result_msg += "\n"
        
        if not missing_files and not orphan_files:
            result_msg += "✅ 完美！完全匹配！\n"
        
        messagebox.showinfo("对比结果", result_msg)
        
        if missing_files and messagebox.askyesno("添加遗漏文件", f"是否添加 {len(missing_files)} 个遗漏的文件？"):
            for filename in missing_files:
                self.data.append({
                    'filename': filename,
                    'keywords': [],
                    'keywords_str': '',
                    'file_exists': True
                })
            self.data.sort(key=lambda x: x['filename'])
            self.refresh_table()
            self.update_status(f"已添加 {len(missing_files)} 个遗漏的文件")
        
        self.check_file_status()
    
    def find_orphan_keywords(self):
        if not self.emojis_folder_path:
            messagebox.showwarning("警告", "请先设置表情文件夹")
            return
        
        emoji_extensions = {'.gif', '.png', '.webp', '.jpg', '.jpeg'}
        existing_files = set()
        for file in Path(self.emojis_folder_path).iterdir():
            if file.is_file() and file.suffix.lower() in emoji_extensions:
                existing_files.add(file.name)
        
        orphan_items = [item for item in self.data if item['filename'] not in existing_files]
        
        if not orphan_items:
            messagebox.showinfo("检查结果", "✅ 没有孤立的映射！")
            return
        
        orphan_keywords = sum(len(item['keywords']) for item in orphan_items)
        
        result_msg = f"⚠️ 发现 {len(orphan_items)} 个孤立的文件映射，涉及 {orphan_keywords} 个关键词：\n\n"
        for i, item in enumerate(sorted(orphan_items, key=lambda x: x['filename'])[:30], 1):
            result_msg += f"   {i}. {item['filename']}\n"
            result_msg += f"      关键词：{', '.join(item['keywords'][:5])}\n"
            if len(item['keywords']) > 5:
                result_msg += f"      ... 还有 {len(item['keywords']) - 5} 个\n"
        
        if messagebox.askyesno("清理孤立映射", 
                               f"发现 {len(orphan_items)} 个孤立的映射，涉及 {orphan_keywords} 个关键词。\n\n"
                               "是否删除这些孤立的关键词映射？"):
            self.data = [item for item in self.data if item['filename'] in existing_files]
            self.refresh_table()
            self.update_status(f"已删除 {len(orphan_items)} 个孤立的映射，共 {orphan_keywords} 个关键词")
            messagebox.showinfo("完成", f"已清理 {len(orphan_items)} 个孤立的映射")
    
    def load_json(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(
                title="选择 JSON 文件",
                filetypes=[("JSON files", "*.json")]
            )
            if not file_path:
                return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            
            file_to_keywords = defaultdict(list)
            for keyword, file_path_value in mapping.items():
                filename = file_path_value.split('/')[-1]
                file_to_keywords[filename].append(keyword)
            
            self.data = []
            for filename, keywords in file_to_keywords.items():
                self.data.append({
                    'filename': filename,
                    'keywords': keywords,
                    'keywords_str': '，'.join(keywords),
                    'file_exists': True
                })
            
            self.data.sort(key=lambda x: x['filename'])
            self.current_file_path = file_path
            self.refresh_table()
            
            if self.emojis_folder_path:
                self.check_file_status()
            
            self.update_status(f"已加载 {len(self.data)} 个表情文件，共 {len(mapping)} 个关键词")
            self.clear_preview()
            
        except Exception as e:
            messagebox.showerror("错误", f"加载失败：{str(e)}")
    
    def save_json(self):
        if not self.data:
            messagebox.showwarning("警告", "没有数据可保存")
            return
        
        mapping = {}
        for item in self.data:
            filename = item['filename']
            for keyword in item['keywords']:
                if keyword in mapping:
                    if not messagebox.askyesno("重复关键词", f"关键词 '{keyword}' 已存在，是否覆盖？"):
                        continue
                mapping[keyword] = f"/static/emojis/{filename}"
        
        if not self.current_file_path:
            file_path = filedialog.asksaveasfilename(
                title="保存 JSON",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json")]
            )
            if not file_path:
                return
        else:
            file_path = self.current_file_path
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
            
            self.update_status(f"已保存，共 {len(mapping)} 个关键词")
            messagebox.showinfo("成功", f"保存成功！\n共 {len(mapping)} 个关键词")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{str(e)}")
    
    def export_excel(self):
        if not self.data:
            messagebox.showwarning("警告", "没有数据")
            return
        
        try:
            import pandas as pd
            file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
            if not file_path:
                return
            
            df_data = [{'文件名': item['filename'], '关键词': '，'.join(item['keywords']), '关键词数量': len(item['keywords'])} 
                       for item in self.data]
            pd.DataFrame(df_data).to_excel(file_path, index=False)
            messagebox.showinfo("成功", f"导出成功！")
        except ImportError:
            messagebox.showerror("错误", "请安装 pandas: pip install pandas openpyxl")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{str(e)}")
    
    def import_excel(self):
        file_path = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not file_path:
            return
        
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            
            if '文件名' not in df.columns or '关键词' not in df.columns:
                messagebox.showerror("错误", "Excel需要'文件名'和'关键词'列")
                return
            
            self.data = []
            for _, row in df.iterrows():
                filename = row['文件名']
                keywords_str = str(row['关键词']) if pd.notna(row['关键词']) else ""
                keywords = [kw.strip() for kw in re.split('[，,、\\s]+', keywords_str) if kw.strip() and kw.strip() != 'nan']
                self.data.append({'filename': filename, 'keywords': keywords, 'keywords_str': '，'.join(keywords), 'file_exists': True})
            
            self.refresh_table()
            self.clear_preview()
            messagebox.showinfo("成功", f"导入 {len(self.data)} 个文件")
        except Exception as e:
            messagebox.showerror("错误", f"导入失败：{str(e)}")
    
    def add_emoji(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("添加表情")
        dialog.geometry("450x250")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.option_add('*Font', self.default_font)
        
        ttk.Label(dialog, text="文件名:").pack(pady=5)
        filename_entry = ttk.Entry(dialog, width=40, font=self.default_font)
        filename_entry.pack(pady=5)
        
        ttk.Label(dialog, text="关键词（用逗号分隔）:").pack(pady=5)
        keywords_entry = ttk.Entry(dialog, width=40, font=self.default_font)
        keywords_entry.pack(pady=5)
        
        def confirm():
            filename = filename_entry.get().strip()
            if not filename:
                messagebox.showwarning("警告", "请输入文件名")
                return
            keywords = [kw.strip() for kw in re.split('[，,、\\s]+', keywords_entry.get().strip()) if kw.strip()]
            self.data.append({'filename': filename, 'keywords': keywords, 'keywords_str': '，'.join(keywords), 'file_exists': True})
            self.data.sort(key=lambda x: x['filename'])
            self.refresh_table()
            dialog.destroy()
        
        ttk.Button(dialog, text="确定", command=confirm).pack(pady=10)
    
    def edit_keywords(self):
        """编辑选中行的关键词 - 带联想功能"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选中要编辑的行")
            return
        
        filename = self.tree.item(selection[0])['values'][0]
        data_item = next((d for d in self.data if d['filename'] == filename), None)
        if not data_item:
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑关键词 - {filename}")
        dialog.geometry("650x500")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.option_add('*Font', self.default_font)
        
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ttk.Label(left_frame, text=f"文件名：{filename}", font=self.bold_font).pack(anchor=tk.W, pady=5)
        ttk.Label(left_frame, text="关键词（每行一个）:").pack(anchor=tk.W)
        
        text_frame = ttk.Frame(left_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        text_widget = tk.Text(text_frame, font=self.text_font, height=18, width=35, wrap=tk.WORD)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        text_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.configure(yscrollcommand=text_scrollbar.set)
        
        if data_item['keywords']:
            text_widget.insert('1.0', '\n'.join(data_item['keywords']))
        
        right_frame = ttk.Frame(main_frame, width=200)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10)
        right_frame.pack_propagate(False)
        
        ttk.Label(right_frame, text="💡 关键词联想", font=self.bold_font).pack(anchor=tk.W)
        ttk.Label(right_frame, text="（输入时自动更新）", font=self.small_font, foreground="gray").pack(anchor=tk.W)
        
        suggestion_listbox = tk.Listbox(right_frame, font=self.default_font, height=20, relief=tk.SUNKEN, borderwidth=1)
        suggestion_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        
        suggestion_scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=suggestion_listbox.yview)
        suggestion_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        suggestion_listbox.configure(yscrollcommand=suggestion_scrollbar.set)
        
        status_label = ttk.Label(right_frame, text="", font=self.small_font, foreground="blue")
        status_label.pack(anchor=tk.W, pady=5)
        
        all_keywords = set()
        keyword_count = {}
        for item in self.data:
            for kw in item['keywords']:
                all_keywords.add(kw)
                keyword_count[kw] = keyword_count.get(kw, 0) + 1
        
        def update_suggestions(event=None):
            try:
                cursor_pos = text_widget.index(tk.INSERT)
                line_start = f"{cursor_pos.split('.')[0]}.0"
                line_end = f"{cursor_pos.split('.')[0]}.end"
                current_line = text_widget.get(line_start, line_end).strip()
                
                if not current_line:
                    suggestion_listbox.delete(0, tk.END)
                    status_label.config(text="")
                    return
                
                matches = []
                for kw in all_keywords:
                    if current_line in kw or kw.startswith(current_line):
                        if kw == current_line:
                            score = 3
                        elif kw.startswith(current_line):
                            score = 2
                        else:
                            score = 1
                        matches.append((score, kw, keyword_count.get(kw, 1)))
                
                matches.sort(key=lambda x: (-x[0], -x[2], x[1]))
                
                suggestion_listbox.delete(0, tk.END)
                for score, kw, count in matches[:15]:
                    if count > 1:
                        suggestion_listbox.insert(tk.END, f"{kw}  (已用{count}次)")
                    else:
                        suggestion_listbox.insert(tk.END, kw)
                
                status_label.config(text=f"找到 {len(matches)} 个联想词")
                
            except Exception:
                pass
        
        def insert_suggestion(event=None):
            selection = suggestion_listbox.curselection()
            if not selection:
                return
            
            selected = suggestion_listbox.get(selection[0])
            if "  (已用" in selected:
                keyword = selected.split("  (已用")[0]
            else:
                keyword = selected
            
            cursor_pos = text_widget.index(tk.INSERT)
            line_start = f"{cursor_pos.split('.')[0]}.0"
            line_end = f"{cursor_pos.split('.')[0]}.end"
            text_widget.delete(line_start, line_end)
            text_widget.insert(line_start, keyword)
            
            next_line = f"{int(cursor_pos.split('.')[0]) + 1}.0"
            text_widget.mark_set(tk.INSERT, next_line)
            
            update_suggestions()
        
        def on_key_release(event):
            if event.keysym in ['Up', 'Down', 'Left', 'Right', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R']:
                return
            update_suggestions()
        
        text_widget.bind('<KeyRelease>', on_key_release)
        suggestion_listbox.bind('<Double-Button-1>', insert_suggestion)
        suggestion_listbox.bind('<Return>', insert_suggestion)
        
        def on_up_down(event):
            if event.keysym == 'Down':
                if suggestion_listbox.size() > 0:
                    suggestion_listbox.select_clear(0, tk.END)
                    suggestion_listbox.selection_set(0)
                    suggestion_listbox.activate(0)
                    suggestion_listbox.focus_set()
                return 'break'
            elif event.keysym == 'Up':
                if suggestion_listbox.size() > 0:
                    suggestion_listbox.select_clear(0, tk.END)
                    suggestion_listbox.selection_set(suggestion_listbox.size() - 1)
                    suggestion_listbox.activate(suggestion_listbox.size() - 1)
                    suggestion_listbox.focus_set()
                return 'break'
            return None
        
        text_widget.bind('<Down>', on_up_down)
        text_widget.bind('<Up>', on_up_down)
        
        def on_listbox_focus_out(event):
            text_widget.focus_set()
        
        suggestion_listbox.bind('<FocusOut>', on_listbox_focus_out)
        
        update_suggestions()
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        def save():
            content = text_widget.get('1.0', tk.END).strip()
            keywords = [line.strip() for line in content.split('\n') if line.strip()]
            data_item['keywords'] = keywords
            data_item['keywords_str'] = '，'.join(keywords)
            self.refresh_table()
            dialog.destroy()
        
        ttk.Button(button_frame, text="✅ 保存", command=save).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="❌ 取消", command=dialog.destroy).pack(side=tk.LEFT, padx=10)
        
        dialog.bind('<Control-s>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        text_widget.focus_set()
    
    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        if messagebox.askyesno("确认", f"删除 {len(selection)} 个表情？"):
            for item in selection:
                filename = self.tree.item(item)['values'][0]
                self.data = [d for d in self.data if d['filename'] != filename]
            self.refresh_table()
            self.clear_preview()
    
    def check_duplicates(self):
        keyword_map = {}
        duplicates = []
        for item in self.data:
            for keyword in item['keywords']:
                if keyword in keyword_map:
                    duplicates.append((keyword, keyword_map[keyword], item['filename']))
                else:
                    keyword_map[keyword] = item['filename']
        
        if duplicates:
            msg = "重复关键词：\n" + "\n".join([f"'{k}' 同时出现在 {f1} 和 {f2}" for k, f1, f2 in duplicates[:20]])
            messagebox.showwarning("重复", msg)
        else:
            messagebox.showinfo("结果", "✅ 无重复关键词")
    
    def show_stats(self):
        if not self.data:
            return
        total_kw = sum(len(item['keywords']) for item in self.data)
        empty = [item['filename'] for item in self.data if not item['keywords']]
        msg = f"总文件: {len(self.data)}\n总关键词: {total_kw}\n平均: {total_kw/len(self.data):.1f}\n无关键词: {len(empty)}"
        messagebox.showinfo("统计", msg)
    
    def sort_by(self, column):
        if column == 'filename':
            self.data.sort(key=lambda x: x['filename'])
        elif column == 'keywords':
            self.data.sort(key=lambda x: x['keywords_str'])
        elif column == 'count':
            self.data.sort(key=lambda x: len(x['keywords']), reverse=True)
        self.refresh_table()
    
    def update_status(self, msg):
        self.status_bar.config(text=msg)
        self.root.update_idletasks()

def main():
    # DPI 感知必须在创建任何窗口之前设置：窗口一旦建好再设置就无效，
    # 界面会被系统按位图拉伸（发虚）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    
    root = tk.Tk()
    app = EmojiEditor(root)
    
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
        if os.path.exists(json_path):
            app.load_json(json_path)
        else:
            app.update_status(f"JSON 文件不存在: {json_path}")
    
    if len(sys.argv) > 2:
        emojis_path = sys.argv[2]
        if os.path.exists(emojis_path):
            app.emojis_folder_path = emojis_path
            app.update_status(f"已自动加载表情文件夹: {emojis_path}")
            if app.data:
                app.check_file_status()
        else:
            app.update_status(f"表情文件夹不存在: {emojis_path}")
    
    root.mainloop()

if __name__ == '__main__':
    main()