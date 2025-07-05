import requests
import time
import random
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import queue
import os
import subprocess
import tempfile
import json
import re
import os.path
import pyperclip

WINDOW_WIDTH = 570
WINDOW_HEIGHT = 750


class BrowserManager:
    def __init__(self):
        self.browser_path = self.find_browser()
        self.user_agent = None
        self.cookies = {}

    def find_browser(self):
        paths = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        ]

        for path in paths:
            if os.path.exists(path):
                return path

        for browser in ['chrome', 'msedge', 'firefox']:
            try:
                path = subprocess.check_output(f"where {browser}", shell=True).decode().strip()
                if path:
                    return path.split('\n')[0]
            except:
                continue
        return None

    def get_user_agent_cookies(self, url):
        if not self.browser_path:
            return None, None

        user_data_dir = tempfile.mkdtemp()
        script_content = """
        console.log(JSON.stringify({
            userAgent: navigator.userAgent,
            cookies: document.cookie
        }));
        window.close();
        """

        script_file = os.path.join(tempfile.gettempdir(), 'browser_script.js')
        with open(script_file, 'w') as f:
            f.write(script_content)

        try:
            cmd = [
                self.browser_path,
                f'--user-data-dir={user_data_dir}',
                '--headless=new',
                '--disable-gpu',
                '--no-first-run',
                '--no-default-browser-check',
                f'--app={url}',
                f'--run-script={script_file}'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = result.stdout
            json_match = re.search(r'\{.*\}', output)
            if json_match:
                data = json.loads(json_match.group(0))
                self.user_agent = data.get('userAgent')
                cookies = {}
                for cookie in data.get('cookies', '').split(';'):
                    if '=' in cookie:
                        key, value = cookie.strip().split('=', 1)
                        cookies[key] = value
                self.cookies = cookies
                return self.user_agent, self.cookies
        except Exception as e:
            print(f"浏览器操作失败: {e}")
        return None, None


class DanbooruScraper:
    def __init__(self, base_url="https://safebooru.donmai.us"):
        self.base_url = base_url
        self.browser_manager = BrowserManager()
        self.user_agent = None
        self.cookies = {}
        self.session = requests.Session()
        self.queue = queue.Queue()
        self.data_file = 'tag_data.json'
        self.tag_data = self.load_data()

    def load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_data(self):
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.tag_data, f, ensure_ascii=False, indent=2)

    def get_tag_info(self, tag):
        normalized_tag = tag.replace(' ', '_')
        tag_key = normalized_tag

        if tag_key in self.tag_data:
            self.queue.put({
                'status': 'success',
                'result': self.tag_data[tag_key]
            })
            return

        url = f"{self.base_url}/wiki_pages/{normalized_tag}"
        response = self.safe_request(url)

        if not response or response.status_code != 200:
            self.queue.put({'status': 'info', 'message': '正在获取浏览器信息，请稍候...'})
            user_agent, cookies = self.browser_manager.get_user_agent_cookies(url)

            if user_agent and cookies:
                self.user_agent = user_agent
                self.cookies = cookies
                self.session.headers.update({'User-Agent': self.user_agent})
                response = self.safe_request(url)

        if not response or response.status_code != 200:
            self.queue.put({
                'status': 'error',
                'message': f"无法获取标签信息: {tag}\nHTTP状态码: {response.status_code if response else '无响应'}"
            })
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        synonyms = [a.text.strip().replace(' ', '_') for a in soup.find_all('a', class_='wiki-other-name')]

        wiki_body = soup.find('div', id='wiki-page-body')
        if not wiki_body:
            self.queue.put({'status': 'error', 'message': f"未找到标签信息: {tag}"})
            return

        content = self.process_wiki_content(wiki_body)

        meaning = ""
        for element in wiki_body.children:
            if element.name in ['h4', 'h5', 'h6']:
                break
            if element.name == 'p':
                meaning += self.convert_html_to_text(str(element)) + "\n\n"

        tag_info = {
            'tag': normalized_tag,
            'tag_translation': "",
            'synonyms': ", ".join(synonyms),
            'meaning': meaning.strip(),
            'meaning_translation': "",
            'sections': content
        }

        self.tag_data[tag_key] = tag_info
        self.save_data()

        self.queue.put({
            'status': 'success',
            'result': tag_info
        })

    def convert_html_to_text(self, html_content):
        # 直接处理HTML字符串，不使用BeautifulSoup
        result = ""
        indent_level = 0
        in_list = False
        in_list_item = False

        # 移除所有HTML注释
        html_content = re.sub(r'<!--.*?-->', '', html_content, flags=re.DOTALL)

        # 处理特殊结构
        html_content = re.sub(r'</?(div|span)[^>]*>', '', html_content)

        # 分割HTML标签
        tokens = re.split(r'(<[^>]+>)', html_content)

        for token in tokens:
            if token.startswith('<h6>') or token.startswith('<h5>') or token.startswith('<h4>'):
                # 标题
                text = re.sub(r'<[^>]+>', '', token).strip()
                result += f"{text}\n\n"
            elif token.startswith('<ul>') or token.startswith('<ol>'):
                # 列表开始
                in_list = True
                indent_level += 1
            elif token.startswith('</ul>') or token.startswith('</ol>'):
                # 列表结束
                in_list = False
                indent_level -= 1
                if indent_level == 0:
                    result += "\n"
            elif token.startswith('<li>'):
                # 列表项开始
                in_list_item = True
                indent = "    " * (indent_level - 1)
                result += f"{indent}• "
            elif token.startswith('</li>'):
                # 列表项结束
                in_list_item = False
                result += "\n"
            elif token.startswith('<a '):
                # 链接
                match = re.search(r'>(.*?)</a>', token)
                if match:
                    link_text = match.group(1).strip()
                    result += f"{link_text} "
            elif not token.startswith('<'):
                # 纯文本
                text = token.strip()
                if text:
                    if in_list_item:
                        result += f"{text} "
                    else:
                        result += f"{text}\n"

        # 清理多余的空格和换行
        result = re.sub(r'\n\s*\n', '\n\n', result)
        result = re.sub(r' +', ' ', result)

        return result.strip()

    def process_wiki_content(self, wiki_body):
        sections = {}
        current_section = None
        current_content = []

        for element in wiki_body.children:
            if element.name in ['h4', 'h5', 'h6']:
                section_title = element.get_text(strip=True)

                if "example" in section_title.lower():
                    current_section = None
                    current_content = []
                    continue

                if current_section:
                    sections[current_section] = "\n".join(current_content)
                    current_content = []
                current_section = section_title
            elif current_section and element.name in ['p', 'ul', 'ol']:
                text_content = self.convert_html_to_text(str(element))
                if text_content:
                    current_content.append(text_content)

        if current_section and current_content:
            sections[current_section] = "\n".join(current_content)

        return sections

    def safe_request(self, url, max_retries=2, delay=2):
        for i in range(max_retries):
            try:
                sleep_time = delay + random.uniform(0, 1)
                time.sleep(sleep_time)
                response = self.session.get(url, cookies=self.cookies, timeout=15)
                if "Just a moment" in response.text or "Cloudflare" in response.text:
                    return None
                return response
            except (requests.RequestException, ConnectionError) as e:
                print(f"请求失败 ({i + 1}/{max_retries}): {e}")
                time.sleep(3)
        return None

    def search_db(self, query):
        normalized_query = query.replace(' ', '_').lower()
        fuzzy_query = normalized_query.replace('_', ' ')

        results = []
        for tag_key, data in self.tag_data.items():
            tag_normalized = data['tag'].lower()
            tag_standard = data['tag'].replace('_', ' ')

            if (normalized_query in tag_normalized or
                    fuzzy_query in tag_normalized or
                    normalized_query in tag_standard or
                    fuzzy_query in tag_standard):
                results.append(data)
                continue

            if normalized_query in data.get('tag_translation', '').lower():
                results.append(data)
                continue

            synonyms = data.get('synonyms', '').lower().replace(' ', '_')
            if normalized_query in synonyms:
                results.append(data)
        return results

    def update_translation(self, tag, tag_translation, meaning_translation):
        tag_key = tag.replace(' ', '_')
        if tag_key in self.tag_data:
            self.tag_data[tag_key]['tag_translation'] = tag_translation
            self.tag_data[tag_key]['meaning_translation'] = meaning_translation
            self.save_data()
            return True
        return False

    def set_base_url(self, url):
        self.base_url = url

    def is_valid_tag(self, tag):
        pattern = r'^[a-zA-Z0-9_\-\.:]+$'
        return bool(re.match(pattern, tag))


class SectionFrame(ttk.Frame):
    def __init__(self, master, title, content, **kwargs):
        super().__init__(master, **kwargs)
        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        title_label = ttk.Label(self, text=title, font=('TkDefaultFont', 10))
        title_label.pack(anchor='nw', padx=5, pady=(0, 5))

        text_frame = ttk.Frame(self, relief='sunken', borderwidth=1)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            height=8,
            font=('TkDefaultFont', 9))
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.text_widget.insert(tk.END, content)
        self.text_widget.config(state=tk.DISABLED)


class EasyDanTagApp:
    def __init__(self, master):
        self.master = master
        master.title("EasyDanTag")
        master.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        master.resizable(False, True)

        self.scraper = DanbooruScraper()
        self.current_search = None
        self.search_timer_id = None
        self.create_widgets()
        self.master.after(100, self.check_queue)

    def create_widgets(self):
        config_frame = ttk.Frame(self.master, padding="10")
        config_frame.pack(fill=tk.X)

        ttk.Label(config_frame, text="站点:").grid(row=0, column=0, padx=5)
        self.site_var = tk.StringVar(value="https://safebooru.donmai.us")
        sites = [
            ("Safebooru", "https://safebooru.donmai.us"),
            ("Danbooru", "https://danbooru.donmai.us")
        ]

        for i, (text, url) in enumerate(sites):
            ttk.Radiobutton(config_frame, text=text, variable=self.site_var,
                            value=url, command=self.change_site).grid(row=0, column=i + 1, padx=5)

        browser_status = "可用" if self.scraper.browser_manager.browser_path else "未找到"
        ttk.Label(config_frame, text=f"浏览器状态: {browser_status}").grid(row=0, column=3, padx=(20, 5))

        search_frame = ttk.Frame(self.master, padding="10")
        search_frame.pack(fill=tk.X)

        ttk.Label(search_frame, text="搜索标签:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame, width=50)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 5), fill=tk.X, expand=True)
        self.search_entry.bind("<Return>", self.on_search_enter)
        self.search_entry.bind("<KeyRelease>", self.on_search_key_release)

        self.search_button = ttk.Button(search_frame, text="搜索", command=self.search_tag)
        self.search_button.pack(side=tk.LEFT, padx=(0, 5))

        result_frame = ttk.Frame(self.master)
        result_frame.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(result_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.info_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.info_tab, text="标签信息")

        self.canvas = tk.Canvas(self.info_tab)
        self.scrollbar = ttk.Scrollbar(self.info_tab, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.fixed_frame = ttk.Frame(self.scrollable_frame)
        self.fixed_frame.pack(fill=tk.X, padx=10, pady=10)

        tag_frame = ttk.LabelFrame(self.fixed_frame, text="标签", padding=5)
        tag_frame.pack(fill=tk.X, padx=5, pady=5)
        self.tag_label = ttk.Label(
            tag_frame,
            text="",
            font=('TkDefaultFont', 10),
            cursor="hand2"
        )
        self.tag_label.pack(anchor='w', padx=5, pady=2, fill=tk.X)
        self.tag_label.bind("<Button-1>", self.copy_tag_to_clipboard)

        tag_trans_frame = ttk.LabelFrame(self.fixed_frame, text="标签翻译", padding=5)
        tag_trans_frame.pack(fill=tk.X, padx=5, pady=5)
        self.tag_translation_entry = ttk.Entry(tag_trans_frame, width=50)
        self.tag_translation_entry.pack(fill=tk.X, padx=5, pady=2)

        synonyms_frame = ttk.LabelFrame(self.fixed_frame, text="同义词", padding=5)
        synonyms_frame.pack(fill=tk.X, padx=5, pady=5)
        self.synonyms_text = scrolledtext.ScrolledText(
            synonyms_frame,
            height=3,
            wrap=tk.WORD,
            font=('TkDefaultFont', 9))
        self.synonyms_text.pack(fill=tk.X, padx=5, pady=2)
        self.synonyms_text.config(state=tk.DISABLED)

        self.meaning_frame = ttk.LabelFrame(self.fixed_frame, text="释义", padding=5)
        self.meaning_frame.pack(fill=tk.X, padx=5, pady=5)
        self.meaning_text = scrolledtext.ScrolledText(
            self.meaning_frame,
            height=8,
            wrap=tk.WORD,
            font=('TkDefaultFont', 9))
        self.meaning_text.pack(fill=tk.X, padx=5, pady=2)
        self.meaning_text.config(state=tk.DISABLED)

        self.dynamic_frame = ttk.Frame(self.scrollable_frame)
        self.dynamic_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        meaning_trans_frame = ttk.LabelFrame(self.fixed_frame, text="释义翻译", padding=5)
        meaning_trans_frame.pack(fill=tk.X, padx=5, pady=5)
        self.meaning_translation_text = scrolledtext.ScrolledText(
            meaning_trans_frame,
            height=8,
            wrap=tk.WORD,
            font=('TkDefaultFont', 9))
        self.meaning_translation_text.pack(fill=tk.X, padx=5, pady=2)

        self.save_button = ttk.Button(self.scrollable_frame, text="保存翻译", command=self.save_translation,
                                      state=tk.DISABLED)
        self.save_button.pack(pady=10)

        self.db_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.db_tab, text="数据库搜索结果")

        columns = ("tag", "tag_translation")
        self.db_tree = ttk.Treeview(self.db_tab, columns=columns, show="headings")

        self.db_tree.heading("tag", text="标签名")
        self.db_tree.heading("tag_translation", text="翻译")

        self.db_tree.column("tag", width=300)
        self.db_tree.column("tag_translation", width=400)

        scrollbar = ttk.Scrollbar(self.db_tab, orient="vertical", command=self.db_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.db_tree.configure(yscrollcommand=scrollbar.set)

        self.db_tree.pack(fill=tk.BOTH, expand=True)
        self.db_tree.bind("<Double-1>", self.on_db_double_click)
        self.db_tree.bind("<Return>", self.on_db_double_click)
        self.db_tree.bind("<Up>", self.on_db_navigate)
        self.db_tree.bind("<Down>", self.on_db_navigate)

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.master, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.progress = ttk.Progressbar(self.master, mode='indeterminate', length=300)

    def copy_tag_to_clipboard(self, event):
        tag = self.tag_label.cget("text")
        if tag:
            pyperclip.copy(tag)
            self.status_var.set(f"已复制标签 '{tag}' 到剪贴板")

    def change_site(self):
        site_url = self.site_var.get()
        self.scraper.set_base_url(site_url)
        self.status_var.set(f"已切换到: {site_url}")

    def on_search_enter(self, event):
        self.search_tag()
        self.master.focus_set()

    def search_tag(self):
        query = self.search_entry.get().strip()
        if not query:
            messagebox.showwarning("输入错误", "请输入标签")
            return

        local_results = self.scraper.search_db(query)
        normalized_query = query.replace(' ', '_')

        if len(local_results) == 1 and local_results[0]['tag'] == normalized_query:
            self.display_tag_info(local_results[0])
            self.status_var.set(f"找到本地标签: {query}")
            self.notebook.select(self.info_tab)
            self.info_tab.focus_set()
        elif local_results:
            self.status_var.set(f"找到 {len(local_results)} 条本地记录")
            self.show_db_results(local_results, query)
            self.notebook.select(self.db_tab)

            if self.db_tree.get_children():
                first_item = self.db_tree.get_children()[0]
                self.db_tree.selection_set(first_item)
                self.db_tree.focus(first_item)
                self.db_tree.see(first_item)
                self.db_tree.focus_set()
        else:
            self.search_button.config(state=tk.DISABLED)
            self.progress.pack(side=tk.BOTTOM, fill=tk.X)
            self.progress.start(10)

            self.status_var.set(f"正在在线获取标签信息: {query}...")
            self.current_search = query

            threading.Thread(
                target=self.scraper.get_tag_info,
                args=(query,),
                daemon=True
            ).start()

    def show_db_results(self, results, query):
        for item in self.db_tree.get_children():
            self.db_tree.delete(item)

        # 添加在线搜索项作为第一项
        self.db_tree.insert("", tk.END, iid="online_search", values=(f"在线搜索：{query}", ""))

        # 添加本地匹配结果
        for i, result in enumerate(results):
            self.db_tree.insert("", tk.END, iid=i, values=(
                result['tag'],
                result.get('tag_translation', '')
            ))

    def process_search_result(self, result):
        self.progress.stop()
        self.progress.pack_forget()
        self.search_button.config(state=tk.NORMAL)
        self.save_button.config(state=tk.NORMAL)

        if result['status'] == 'success':
            self.display_tag_info(result['result'])
            self.status_var.set(f"成功获取标签信息: {self.current_search}")
            self.save_button.config(state=tk.NORMAL)
            self.notebook.select(self.info_tab)
            self.info_tab.focus_set()
        elif result['status'] == 'info':
            self.status_var.set(result['message'])
        else:
            self.status_var.set(result['message'])
            messagebox.showerror("错误", result['message'])

    def display_tag_info(self, tag_info):
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()

        self.tag_label.config(text=tag_info['tag'])
        self.tag_translation_entry.delete(0, tk.END)
        self.tag_translation_entry.insert(0, tag_info.get('tag_translation', ''))

        self.synonyms_text.config(state=tk.NORMAL)
        self.synonyms_text.delete(1.0, tk.END)
        self.synonyms_text.insert(tk.END, tag_info.get('synonyms', ''))
        self.synonyms_text.config(state=tk.DISABLED)

        self.meaning_text.config(state=tk.NORMAL)
        self.meaning_text.delete(1.0, tk.END)
        self.meaning_text.insert(tk.END, tag_info.get('meaning', ''))
        self.meaning_text.config(state=tk.DISABLED)

        self.meaning_translation_text.delete(1.0, tk.END)
        self.meaning_translation_text.insert(tk.END, tag_info.get('meaning_translation', ''))

        for section_title, section_content in tag_info.get('sections', {}).items():
            SectionFrame(
                self.dynamic_frame,
                title=section_title,
                content=section_content
            )

    def on_search_key_release(self, event):
        if self.search_timer_id:
            self.master.after_cancel(self.search_timer_id)
        self.search_timer_id = self.master.after(100, self.perform_auto_search)

    def perform_auto_search(self):
        query = self.search_entry.get().strip()
        if not query:
            return

        results = self.scraper.search_db(query)
        for item in self.db_tree.get_children():
            self.db_tree.delete(item)

        for i, result in enumerate(results):
            self.db_tree.insert("", tk.END, iid=i, values=(
                result['tag'],
                result.get('tag_translation', '')
            ))

        if results:
            self.status_var.set(f"找到 {len(results)} 条匹配记录（自动匹配）")
        else:
            self.status_var.set("未找到匹配记录（自动匹配）")

    def on_db_double_click(self, event=None):
        selected = self.db_tree.selection()
        if not selected:
            return

        item_id = selected[0]
        item = self.db_tree.item(item_id)

        # 检查是否是"在线搜索"项
        if item_id == "online_search":
            query = item['values'][0].split("：")[1]
            if not self.scraper.is_valid_tag(query):
                messagebox.showwarning("无效标签", f"'{query}' 不是有效的标签格式")
                return

            self.search_button.config(state=tk.DISABLED)
            self.progress.pack(side=tk.BOTTOM, fill=tk.X)
            self.progress.start(10)
            self.status_var.set(f"正在在线获取标签信息: {query}...")
            self.current_search = query

            threading.Thread(
                target=self.scraper.get_tag_info,
                args=(query,),
                daemon=True
            ).start()
        else:
            tag = item['values'][0]
            normalized_tag = tag.replace(' ', '_')
            if normalized_tag in self.scraper.tag_data:
                self.notebook.select(self.info_tab)
                self.display_tag_info(self.scraper.tag_data[normalized_tag])
                self.save_button.config(state=tk.NORMAL)
                self.info_tab.focus_set()

    def on_db_navigate(self, event):
        current_selection = self.db_tree.selection()
        if not current_selection:
            return

        current_item = current_selection[0]
        children = self.db_tree.get_children()

        if event.keysym == "Up":
            index = children.index(current_item)
            if index > 0:
                new_item = children[index - 1]
                self.db_tree.selection_set(new_item)
                self.db_tree.focus(new_item)
                self.db_tree.see(new_item)
        elif event.keysym == "Down":
            index = children.index(current_item)
            if index < len(children) - 1:
                new_item = children[index + 1]
                self.db_tree.selection_set(new_item)
                self.db_tree.focus(new_item)
                self.db_tree.see(new_item)
        return "break"

    def save_translation(self):
        tag = self.tag_label.cget("text")
        tag_translation = self.tag_translation_entry.get()
        meaning_translation = self.meaning_translation_text.get(1.0, tk.END).strip()

        if not tag:
            messagebox.showwarning("错误", "没有选中的标签")
            return

        normalized_tag = tag.replace(' ', '_')
        if self.scraper.update_translation(normalized_tag, tag_translation, meaning_translation):
            self.status_var.set("翻译已保存")
            messagebox.showinfo("成功", "翻译已保存")
        else:
            self.status_var.set("保存翻译失败")
            messagebox.showerror("错误", "保存翻译失败")

    def check_queue(self):
        try:
            while not self.scraper.queue.empty():
                result = self.scraper.queue.get_nowait()
                self.process_search_result(result)
        except queue.Empty:
            pass
        self.master.after(100, self.check_queue)


if __name__ == "__main__":
    root = tk.Tk()
    app = EasyDanTagApp(root)
    root.mainloop()
