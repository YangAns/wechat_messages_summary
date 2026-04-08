import sys
import os
import json
import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton,
                              QTextEdit, QComboBox, QMessageBox, QTabWidget,
                              QScrollArea, QFrame, QFileDialog, QCheckBox, QTimeEdit,
                              QInputDialog, QDialog, QListWidget, QSystemTrayIcon, QMenu)
from PySide6.QtCore import Signal, QThread, QTime, Qt
from PySide6.QtGui import QIcon, QAction
import argparse # 用于处理启动参数
from apscheduler.schedulers.background import BackgroundScheduler

# 导入 V3 核心逻辑
from wechat_summary import (resolve_group_id, fetch_chat_messages, fetch_all_chat_messages,
                               generate_ai_summary, save_summary_to_file,
                               auto_scheduled_task, send_summary_to_wechat)

class ModernStyle:
    BACKGROUND = "#ffffff"
    SECONDARY_BACKGROUND = "#f5f5f7"
    TEXT = "#1d1d1f"
    SECONDARY_TEXT = "#86868b"
    ACCENT = "#0066cc"
    BORDER = "#d2d2d7"
    FONT_FAMILY = "-apple-system, BlinkMacSystemFont, Microsoft YaHei, Segoe UI"

    @staticmethod
    def setup_widget(widget):
        widget.setStyleSheet(f"""
            QMainWindow {{
                background-color: {ModernStyle.BACKGROUND};
            }}
            QWidget {{
                background-color: {ModernStyle.BACKGROUND};
                color: {ModernStyle.TEXT};
                font-family: {ModernStyle.FONT_FAMILY};
            }}
            QLabel {{
                color: {ModernStyle.TEXT};
                font-size: 12px;
                padding: 0;
                margin: 0;
            }}
            QLineEdit, QSpinBox, QComboBox, QTimeEdit {{
                border: 1px solid {ModernStyle.BORDER};
                border-radius: 3px;
                padding: 3px 8px;
                background: white;
                height: 24px;
                font-size: 12px;
            }}
            QPushButton {{
                background-color: {ModernStyle.ACCENT};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 3px 12px;
                height: 24px;
                font-size: 12px;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: #0077ed;
            }}
            QPushButton#mainButton {{
                height: 32px;
                font-size: 13px;
                font-weight: 500;
            }}
            QTextEdit {{
                border: 1px solid {ModernStyle.BORDER};
                border-radius: 3px;
                padding: 8px;
                background: white;
                font-size: 12px;
            }}
            QTabWidget::pane {{
                border: none;
                background-color: {ModernStyle.BACKGROUND};
            }}
            QTabBar::tab {{
                padding: 6px 16px;
                margin-right: 2px;
                color: {ModernStyle.TEXT};
                border: none;
                background: none;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                color: {ModernStyle.ACCENT};
                border-bottom: 2px solid {ModernStyle.ACCENT};
            }}
            QScrollArea {{
                border: none;
            }}
            QFrame#configCard {{
                border: 1px solid {ModernStyle.BORDER};
                border-radius: 3px;
                background: white;
                padding: 12px;
                margin: 4px 0;
            }}
            QListWidget {{
                border: 1px solid {ModernStyle.BORDER};
                border-radius: 3px;
                background: white;
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid #f0f0f0;
            }}
            QListWidget::item:selected {{
                background: #f5f5f7;
                color: #0066cc;
            }}
        """)

# --- AI 配置相关组件 (完全对应 V2) ---

class CustomComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

class ConfigCard(QFrame):
    def __init__(self, service_name, config, parent=None):
        super().__init__(parent)
        self.service_name = service_name
        self.setObjectName("configCard")
        self.setup_ui(service_name, config)

    def setup_ui(self, service_name, config):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Header with Service Name Edit
        header = QHBoxLayout()
        header.addWidget(QLabel("服务名称:"))
        self.name_input = QLineEdit(service_name)
        self.name_input.setStyleSheet("font-weight: bold;")
        self.name_input.textChanged.connect(self.on_name_changed)
        header.addWidget(self.name_input)

        delete_btn = QPushButton("删除服务")
        delete_btn.setFixedWidth(80)
        delete_btn.setStyleSheet("background-color: #ff3b30;")
        delete_btn.clicked.connect(self.delete_service)
        header.addWidget(delete_btn)
        layout.addLayout(header)

        # Base URL
        layout.addWidget(QLabel("Base URL"))
        self.url_input = QLineEdit(config.get('base_url', ''))
        self.url_input.setPlaceholderText("https://api.openai.com/v1")
        self.url_input.textChanged.connect(self.auto_save)
        layout.addWidget(self.url_input)

        # API Key
        layout.addWidget(QLabel("API Key"))
        self.key_input = QLineEdit(config.get('api_key', ''))
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("请输入API密钥")
        self.key_input.textChanged.connect(self.auto_save)
        layout.addWidget(self.key_input)

        # Model Management
        layout.addWidget(QLabel("模型管理 (下拉选择当前启用模型)"))
        model_container = QHBoxLayout()
        self.model_combo = QComboBox() # 改为普通 ComboBox 以支持启用模型选择
        models = config.get('models', [config.get('model', 'qwen-plus')])
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(config.get('model', ''))
        self.model_combo.currentTextChanged.connect(self.auto_save)
        model_container.addWidget(self.model_combo, 1)

        add_m_btn = QPushButton("添加模型")
        add_m_btn.clicked.connect(self.add_model)
        model_container.addWidget(add_m_btn)

        del_m_btn = QPushButton("删除模型")
        del_m_btn.clicked.connect(self.delete_model)
        model_container.addWidget(del_m_btn)
        layout.addLayout(model_container)

    def on_name_changed(self, new_name):
        if not new_name.strip(): return
        # 这种逻辑需要特殊处理，因为 key 变了
        self.window().rename_service(self.service_name, new_name.strip())
        self.service_name = new_name.strip()

    def auto_save(self):
        self.window().save_service_config(self.service_name, self.get_current_config())

    def delete_service(self):
        if QMessageBox.question(self, "确认", f"确定删除 {self.service_name}?") == QMessageBox.Yes:
            self.window().delete_service_config(self.service_name)

    def add_model(self):
        name, ok = QInputDialog.getText(self, "添加模型", "请输入模型名称 (例如 gpt-4):")
        if ok and name.strip():
            if self.model_combo.findText(name.strip()) == -1:
                self.model_combo.addItem(name.strip())
            self.model_combo.setCurrentText(name.strip())
            self.auto_save()

    def delete_model(self):
        if self.model_combo.count() > 1:
            self.model_combo.removeItem(self.model_combo.currentIndex())
            self.auto_save()
        else:
            QMessageBox.warning(self, "警告", "至少保留一个模型")

    def get_current_config(self):
        models = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
        return {
            'api_key': self.key_input.text(),
            'base_url': self.url_input.text().strip(),
            'model': self.model_combo.currentText(),
            'models': models,
            'use_markdown': True
        }

class AddServiceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加新服务")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        self.name_in = QLineEdit(); layout.addWidget(QLabel("服务名称:")); layout.addWidget(self.name_in)
        self.key_in = QLineEdit(); layout.addWidget(QLabel("API Key:")); self.key_in.setEchoMode(QLineEdit.Password); layout.addWidget(self.key_in)
        self.url_in = QLineEdit(); layout.addWidget(QLabel("Base URL:")); layout.addWidget(self.url_in)
        self.model_in = QLineEdit(); layout.addWidget(QLabel("模型名称:")); layout.addWidget(self.model_in)

        btns = QHBoxLayout()
        save = QPushButton("保存"); save.clicked.connect(self.accept)
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(cancel); btns.addWidget(save)
        layout.addLayout(btns)

    def get_data(self):
        return {
            'name': self.name_in.text().strip(),
            'api_key': self.key_in.text().strip(),
            'base_url': self.url_in.text().strip(),
            'model': self.model_in.text().strip()
        }

# --- 提示词管理器 (完全对应 V2) ---

class PromptManager:
    def __init__(self, path):
        self.path = path
        self.prompts = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 兼容 V2 格式 (name: {content: ...}) 和 V3 格式 (name: content)
                for name, val in data.items():
                    if isinstance(val, dict):
                        self.prompts[name] = val.get('content', '')
                    else:
                        self.prompts[name] = val
        else:
            self.prompts = {"默认提示词": "你是一个专业的群聊总结助手..."}

    def save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.prompts, f, ensure_ascii=False, indent=4)

# --- 工作线程 ---

class SummaryWorker(QThread):
    finished = Signal(str)
    error = Signal(str)
    status = Signal(str)  # 新增状态信号

    def __init__(self, group_name, hours, mins, ai_config, prompt, limit=0, my_nickname=None):
        super().__init__()
        self.group_name = group_name
        self.duration = hours + (mins / 60.0)
        self.ai_config = ai_config
        self.prompt = prompt
        self.limit = limit
        self.my_nickname = my_nickname
        self.last_summary = ""
        self.last_saved_path = None
        self.last_start_dt = None
        self.last_end_dt = None

    def run(self):
        try:
            self.status.emit(f"正在查找群聊: {self.group_name}...")
            group_id = resolve_group_id(self.group_name)
            if not group_id:
                self.error.emit(f"未找到群聊: {self.group_name}")
                return

            self.status.emit(f"正在获取近 {self.duration:.1f} 小时的聊天消息...")
            end = datetime.datetime.now().timestamp()
            start = end - (self.duration * 3600)

            # 转换为 datetime 对象以便传递给总结函数
            start_dt = datetime.datetime.fromtimestamp(start)
            end_dt = datetime.datetime.fromtimestamp(end)

            if self.limit > 0:
                msgs = fetch_chat_messages(group_id, start, end, limit=self.limit)
                # 对手动限制条数的消息也进行升序排序
                msgs.sort(key=lambda x: x.get("timestamp", 0))
                self.status.emit(f"已获取 {len(msgs)} 条消息（限制 {self.limit} 条），正在调用 AI 生成总结...")
            else:
                msgs = fetch_all_chat_messages(group_id, start, end)
                self.status.emit(f"已获取全部 {len(msgs)} 条消息，正在调用 AI 生成总结...")

            if not msgs:
                self.error.emit("该时段内未发现有效的聊天消息")
                return

            self.last_start_dt = start_dt
            self.last_end_dt = end_dt

            res = generate_ai_summary(msgs, self.ai_config, self.prompt, my_nickname=self.my_nickname, start_dt=start_dt, end_dt=end_dt)
            self.last_summary = res
            self.last_saved_path = None

            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))

# --- 主窗口 ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("微信群聊总结工具 v2.0")
        self.setMinimumSize(800, 850)

        # 设置窗口图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "main.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            self.icon = QIcon(icon_path)
        else:
            self.icon = QIcon()

        # 获取主程序 V3 所在的完整绝对路径，确保配置文件读写正确
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.config_dir = os.path.join(self.base_path, "config")
        self.ai_path = os.path.join(self.config_dir, "ai_config.json")
        self.prompt_path = os.path.join(self.config_dir, "prompts.json")
        self.schedule_path = os.path.join(self.config_dir, "schedule_config.json")
        self.settings_path = os.path.join(self.config_dir, "settings.json")
        self.load_configs()
        self.prompt_mgr = PromptManager(self.prompt_path)

        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.apply_schedule()

        self.setup_ui()
        self.setup_tray() # 初始化托盘
        ModernStyle.setup_widget(self)

    def setup_tray(self):
        """设置系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.icon)

        # 托盘菜单
        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self.quit_app)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger: # 单击
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.activateWindow()

    def closeEvent(self, event):
        """重写关闭事件，点击关闭按钮时隐藏到托盘"""
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
            # 首次隐藏时弹出提示（可选）
            # self.tray_icon.showMessage("运行中", "程序已最小化到系统托盘", QSystemTrayIcon.Information, 2000)
        else:
            event.accept()

    def quit_app(self):
        """真正退出程序"""
        self.tray_icon.hide()
        QApplication.quit()

    def load_configs(self):
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)

        if os.path.exists(self.ai_path):
            with open(self.ai_path, 'r', encoding='utf-8') as f:
                self.ai_data = json.load(f)
        else:
            self.ai_data = {"services": {}, "last_service": ""}

        if os.path.exists(self.schedule_path):
            with open(self.schedule_path, 'r', encoding='utf-8') as f:
                self.schedule_data = json.load(f)
            self.schedule_data.setdefault("git_config", {
                "enabled": False,
                "repo": "",
                "token": "",
                "branch": "main"
            })
            self.schedule_data.setdefault("wechat_config", {
                "enabled": False,
                "webhook_url": "",
                "webhook_secret": ""
            })
        else:
            self.schedule_data = {
                "enabled": False,
                "group": "",
                "time": "09:00",
                "wechat_config": {
                    "enabled": False,
                    "webhook_url": "",
                    "webhook_secret": ""
                }
            }

        if os.path.exists(self.settings_path):
            with open(self.settings_path, 'r', encoding='utf-8') as f:
                self.settings_data = json.load(f)
        else:
            self.settings_data = {"my_nickname": "", "default_export_path": ""}

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self.create_summary_tab(), "群聊总结")
        self.tabs.addTab(self.create_ai_tab(), "AI服务配置")
        self.tabs.addTab(self.create_prompt_tab(), "提示词配置")
        self.tabs.addTab(self.create_schedule_tab(), "定时任务配置")
        self.tabs.addTab(self.create_settings_tab(), "常规设置")

    def create_summary_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 配置区域（带边框分组）
        config_group = QFrame()
        config_group.setObjectName("summaryConfig")
        config_group.setStyleSheet("QFrame#summaryConfig { border: 1px solid " + ModernStyle.BORDER + "; border-radius: 4px; padding: 10px; }")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(8)
        label_width = 80
        # 第一行：群聊名称 + AI服务
        r1 = QHBoxLayout()
        lbl1 = QLabel("群聊名称:"); lbl1.setFixedWidth(label_width)
        r1.addWidget(lbl1)
        self.group_in = QLineEdit()
        self.group_in.setPlaceholderText("输入群聊名称关键字，如：项目群")
        r1.addWidget(self.group_in, 2)
        r1.addSpacing(12)
        lbl2 = QLabel("AI 服务:"); lbl2.setFixedWidth(label_width)
        r1.addWidget(lbl2)
        self.ai_combo = QComboBox()
        self.refresh_ai_combo()
        r1.addWidget(self.ai_combo, 1)
        config_layout.addLayout(r1)

        # 第二行：获取范围 + 条数限制
        r2 = QHBoxLayout()
        lbl3 = QLabel("获取范围:"); lbl3.setFixedWidth(label_width)
        r2.addWidget(lbl3)
        self.h_spin = QSpinBox(); self.h_spin.setValue(24); self.h_spin.setRange(0, 720); self.h_spin.setMinimumWidth(60)
        r2.addWidget(self.h_spin)
        r2.addWidget(QLabel("小时"))
        r2.addSpacing(4)
        self.m_spin = QSpinBox(); self.m_spin.setRange(0, 59); self.m_spin.setMinimumWidth(60)
        r2.addWidget(self.m_spin)
        r2.addWidget(QLabel("分钟"))
        r2.addSpacing(12)
        lbl4 = QLabel("条数限制:"); lbl4.setFixedWidth(label_width)
        r2.addWidget(lbl4)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 10000)
        self.limit_spin.setValue(0)
        self.limit_spin.setMinimumWidth(80)
        r2.addWidget(self.limit_spin)
        r2.addWidget(QLabel("条（0 不限制）"))
        r2.addStretch()
        config_layout.addLayout(r2)

        layout.addWidget(config_group)

        # 生成总结按钮（独占一行）
        self.gen_btn = QPushButton("生成总结"); self.gen_btn.setObjectName("mainButton"); self.gen_btn.clicked.connect(self.on_generate)
        layout.addWidget(self.gen_btn)

        # 状态栏
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {ModernStyle.SECONDARY_TEXT}; font-size: 12px;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("预览:"))
        self.preview = QTextEdit(); self.preview.setReadOnly(True)
        layout.addWidget(self.preview)

        h_exp = QHBoxLayout()
        self.wx_btn = QPushButton("推送至微信")
        self.wx_btn.setEnabled(False)
        self.wx_btn.clicked.connect(self.on_push_to_wechat)
        h_exp.addStretch()
        h_exp.addWidget(self.wx_btn)
        self.export_btn = QPushButton("导出总结")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.on_export)
        h_exp.addWidget(self.export_btn)
        layout.addLayout(h_exp)

        return tab

    def create_ai_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.ai_scroll_content = QWidget()
        self.ai_scroll_layout = QVBoxLayout(self.ai_scroll_content)
        self.refresh_ai_cards()
        scroll.setWidget(self.ai_scroll_content)
        layout.addWidget(scroll)

        add_btn = QPushButton("添加新服务"); add_btn.clicked.connect(self.on_add_service)
        layout.addWidget(add_btn)
        return tab

    def create_prompt_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)

        split = QHBoxLayout()
        # List
        left = QVBoxLayout()
        h = QHBoxLayout(); h.addWidget(QLabel("提示词列表")); add_p = QPushButton("+"); add_p.setFixedSize(24, 24); add_p.clicked.connect(self.on_add_prompt); h.addWidget(add_p); left.addLayout(h)
        self.p_list = QListWidget(); self.p_list.addItems(self.prompt_mgr.prompts.keys()); self.p_list.currentItemChanged.connect(self.on_p_selection_changed); left.addWidget(self.p_list)
        split.addLayout(left, 1)

        # Edit
        right = QVBoxLayout()
        right.addWidget(QLabel("名称")); self.p_name_in = QLineEdit(); right.addWidget(self.p_name_in)
        right.addWidget(QLabel("内容")); self.p_edit = QTextEdit(); right.addWidget(self.p_edit)
        btns = QHBoxLayout()
        save_p = QPushButton("保存修改"); save_p.clicked.connect(self.on_save_prompt); btns.addWidget(save_p)
        del_p = QPushButton("删除提示词"); del_p.clicked.connect(self.on_del_prompt); btns.addWidget(del_p)
        right.addLayout(btns)
        split.addLayout(right, 2)

        layout.addLayout(split)
        return tab

    def create_schedule_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 定时任务开关
        self.sched_on = QCheckBox("启用每日定时总结")
        self.sched_on.setChecked(self.schedule_data.get("enabled", False))
        layout.addWidget(self.sched_on)

        # 任务基本配置
        task_group = QFrame()
        task_group.setStyleSheet(f"border: 1px solid {ModernStyle.BORDER}; border-radius: 4px; padding: 10px;")
        task_layout = QVBoxLayout(task_group)

        h1 = QHBoxLayout()
        h1.addWidget(QLabel("目标群聊:"))
        self.sched_g = QLineEdit(self.schedule_data.get("group", ""))
        h1.addWidget(self.sched_g)
        task_layout.addLayout(h1)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("执行时间:"))
        self.sched_t = QTimeEdit()
        self.sched_t.setTime(QTime.fromString(self.schedule_data.get("time", "09:00"), "HH:mm"))
        h2.addWidget(self.sched_t)
        task_layout.addLayout(h2)

        h_ai = QHBoxLayout()
        h_ai.addWidget(QLabel("AI 服务:"))
        self.sched_ai = QComboBox()
        self.sched_ai.addItems(self.ai_data.get('services', {}).keys())
        self.sched_ai.setCurrentText(self.schedule_data.get("ai_service", ""))
        h_ai.addWidget(self.sched_ai)
        task_layout.addLayout(h_ai)

        layout.addWidget(task_group)

        # Git 配置部分
        git_label = QLabel("GitHub 自动推送配置 (可选)")
        git_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(git_label)

        git_group = QFrame()
        git_group.setStyleSheet(f"border: 1px solid {ModernStyle.BORDER}; border-radius: 4px; padding: 10px;")
        git_layout = QVBoxLayout(git_group)

        git_cfg = self.schedule_data.get("git_config", {})
        self.git_on = QCheckBox("启用 GitHub 推送")
        self.git_on.setChecked(git_cfg.get("enabled", False))
        git_layout.addWidget(self.git_on)

        h3 = QHBoxLayout()
        h3.addWidget(QLabel("仓库 URL:"))
        self.git_repo = QLineEdit(git_cfg.get("repo", ""))
        self.git_repo.setPlaceholderText("https://github.com/user/repo")
        h3.addWidget(self.git_repo)
        git_layout.addLayout(h3)

        h4 = QHBoxLayout()
        h4.addWidget(QLabel("Access Token:"))
        self.git_token = QLineEdit(git_cfg.get("token", ""))
        self.git_token.setEchoMode(QLineEdit.Password)
        self.git_token.setPlaceholderText("ghp_xxxxxxxxxxxx")
        h4.addWidget(self.git_token)
        git_layout.addLayout(h4)

        h5 = QHBoxLayout()
        h5.addWidget(QLabel("推送分支:"))
        self.git_branch = QLineEdit(git_cfg.get("branch", "main"))
        h5.addWidget(self.git_branch)
        git_layout.addLayout(h5)

        layout.addWidget(git_group)

        # 微信推送配置
        wx_label = QLabel("微信推送配置 (可选)")
        wx_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(wx_label)

        wx_group = QFrame()
        wx_group.setStyleSheet(f"border: 1px solid {ModernStyle.BORDER}; border-radius: 4px; padding: 10px;")
        wx_layout = QVBoxLayout(wx_group)

        wx_cfg = self.schedule_data.get("wechat_config", {})
        self.wx_on = QCheckBox("启用定时总结后自动推送到微信")
        self.wx_on.setChecked(wx_cfg.get("enabled", False))
        wx_layout.addWidget(self.wx_on)

        h_wx_url = QHBoxLayout()
        h_wx_url.addWidget(QLabel("Webhook 地址:"))
        self.wx_webhook_url = QLineEdit(wx_cfg.get("webhook_url", ""))
        self.wx_webhook_url.setPlaceholderText("http://127.0.0.1:18731/hook/xxxx/send")
        h_wx_url.addWidget(self.wx_webhook_url)
        wx_layout.addLayout(h_wx_url)

        h_wx_secret = QHBoxLayout()
        h_wx_secret.addWidget(QLabel("Webhook 密钥:"))
        self.wx_webhook_secret = QLineEdit(wx_cfg.get("webhook_secret", ""))
        self.wx_webhook_secret.setEchoMode(QLineEdit.Password)
        self.wx_webhook_secret.setPlaceholderText("请输入 Webhook 密钥")
        h_wx_secret.addWidget(self.wx_webhook_secret)
        wx_layout.addLayout(h_wx_secret)

        layout.addWidget(wx_group)

        layout.addStretch()
        save_s = QPushButton("保存配置")
        save_s.clicked.connect(self.on_save_schedule)
        layout.addWidget(save_s)
        return tab

    # --- Actions ---

    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 个人信息配置
        nick_label = QLabel("个人信息")
        nick_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(nick_label)

        nick_group = QFrame()
        nick_group.setStyleSheet(f"border: 1px solid {ModernStyle.BORDER}; border-radius: 4px; padding: 10px;")
        nick_layout = QVBoxLayout(nick_group)

        h_nick = QHBoxLayout()
        h_nick.addWidget(QLabel("我的微信昵称（默认昵称）:"))
        self.nick_in = QLineEdit(self.settings_data.get('my_nickname', ''))
        self.nick_in.setPlaceholderText("未设置群昵称时用于识别 @我，设置了群昵称的群会自动识别")
        h_nick.addWidget(self.nick_in)
        nick_layout.addLayout(h_nick)
        layout.addWidget(nick_group)

        # 导出路径配置
        path_label = QLabel("导出设置")
        path_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(path_label)

        path_group = QFrame()
        path_group.setStyleSheet(f"border: 1px solid {ModernStyle.BORDER}; border-radius: 4px; padding: 10px;")
        path_layout = QVBoxLayout(path_group)

        h_path = QHBoxLayout()
        h_path.addWidget(QLabel("默认导出目录:"))
        self.path_in = QLineEdit(self.settings_data.get('default_export_path', ''))
        self.path_in.setPlaceholderText("留空则使用程序目录下的 summary 文件夹")
        h_path.addWidget(self.path_in)

        path_btn = QPushButton("选择...")
        path_btn.setFixedWidth(60)
        path_btn.clicked.connect(self.on_select_path)
        h_path.addWidget(path_btn)
        path_layout.addLayout(h_path)
        layout.addWidget(path_group)

        layout.addStretch()
        save_s = QPushButton("保存配置")
        save_s.clicked.connect(self.on_save_settings)
        layout.addWidget(save_s)
        return tab

    def on_select_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择默认导出根目录")
        if path:
            self.path_in.setText(path)

    def on_save_settings(self):
        self.settings_data['my_nickname'] = self.nick_in.text().strip()
        self.settings_data['default_export_path'] = self.path_in.text().strip()
        with open(self.settings_path, 'w', encoding='utf-8') as f:
            json.dump(self.settings_data, f, ensure_ascii=False, indent=4)
        QMessageBox.information(self, "成功", "设置已保存")

    def refresh_ai_combo(self):
        self.ai_combo.clear()
        self.ai_combo.addItems(self.ai_data.get('services', {}).keys())

    def refresh_ai_cards(self):
        while self.ai_scroll_layout.count() > 0:
            item = self.ai_scroll_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for name, cfg in self.ai_data.get('services', {}).items():
            self.ai_scroll_layout.addWidget(ConfigCard(name, cfg))
        self.ai_scroll_layout.addStretch()

    def on_generate(self):
        # 防止重复点击：如果上一个 worker 还在运行，直接忽略
        if hasattr(self, 'worker') and self.worker.isRunning():
            return

        group = self.group_in.text().strip()
        svc = self.ai_combo.currentText()
        if not group or not svc:
            QMessageBox.warning(self, "提示", "请输入群聊名称并选择 AI 服务")
            return

        # 时间范围校验
        if self.h_spin.value() == 0 and self.m_spin.value() == 0:
            QMessageBox.warning(self, "提示", "获取范围不能为 0 分钟")
            return

        # 禁用按钮防止并发
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("正在生成...")
        self.wx_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.status_label.setText("初始化中...")
        self.preview.setPlainText("")

        cfg = self.ai_data['services'][svc].copy()

        # 安全获取提示词，防止为空崩溃
        prompt_content = ""
        if self.p_edit.toPlainText().strip():
            prompt_content = self.p_edit.toPlainText()
        elif self.prompt_mgr.prompts:
            # 如果编辑器为空，尝试使用列表中选中的，或者第一个
            curr_item = self.p_list.currentItem()
            if curr_item:
                prompt_content = self.prompt_mgr.prompts.get(curr_item.text(), "")
            else:
                prompt_content = list(self.prompt_mgr.prompts.values())[0]

        if not prompt_content:
            QMessageBox.warning(self, "提示", "请先配置并选择一个有效的提示词")
            self.reset_generate_button()
            return

        my_nickname = self.settings_data.get('my_nickname', '').strip()
        self.worker = SummaryWorker(group, self.h_spin.value(), self.m_spin.value(), cfg, prompt_content, limit=self.limit_spin.value(), my_nickname=my_nickname)

        # 连接信号
        self.worker.status.connect(lambda s: self.status_label.setText(s))
        self.worker.finished.connect(self.on_summary_finished)
        self.worker.error.connect(self.on_summary_error)
        self.worker.start()

    def on_summary_finished(self, result):
        self.preview.setPlainText(result)
        self.status_label.setText("总结生成完成")
        is_valid_result = bool(result and not result.startswith("生成总结时出错"))
        self.wx_btn.setEnabled(is_valid_result)
        self.export_btn.setEnabled(is_valid_result)
        self.reset_generate_button()

    def on_summary_error(self, error_msg):
        QMessageBox.critical(self, "错误", error_msg)
        self.status_label.setText(f"执行失败: {error_msg}")
        self.preview.setPlainText("")
        self.wx_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.reset_generate_button()

    def reset_generate_button(self):
        # 恢复按钮状态
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("生成总结")

    def on_export(self):
        # 业务逻辑：导出总结时，默认使用 settings.json 中的导出路径作为初始目录
        default_dir = self.settings_data.get('default_export_path', '').strip()
        if not default_dir or not os.path.exists(default_dir):
            default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "summary")

        # 建议文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        suggested_name = f"{self.group_in.text()}_总结_{timestamp}.md"

        initial_path = os.path.join(default_dir, suggested_name)

        path, _ = QFileDialog.getSaveFileName(self, "导出总结", initial_path, "Markdown (*.md)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self.preview.toPlainText())
                QMessageBox.information(self, "成功", f"总结已成功导出至：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败：{e}")

    def on_push_to_wechat(self):
        summary = self.preview.toPlainText().strip()
        if not summary:
            QMessageBox.warning(self, "提示", "请先生成总结后再推送到微信")
            return

        wechat_cfg = self.schedule_data.get("wechat_config", {})
        webhook_url = wechat_cfg.get("webhook_url", "").strip()
        webhook_secret = wechat_cfg.get("webhook_secret", "").strip()
        if not webhook_url or not webhook_secret:
            QMessageBox.warning(self, "提示", "请先在定时任务配置页填写微信 Webhook 地址和密钥")
            return

        if not hasattr(self, 'worker') or not getattr(self.worker, 'last_start_dt', None) or not getattr(self.worker, 'last_end_dt', None):
            QMessageBox.warning(self, "提示", "缺少本次总结的时间范围信息，请重新生成后再推送")
            return

        pushed = send_summary_to_wechat(
            group_name=self.group_in.text().strip(),
            summary=summary,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            trigger_mode="manual",
            start_dt=self.worker.last_start_dt,
            end_dt=self.worker.last_end_dt,
            saved_path=getattr(self.worker, 'last_saved_path', None),
        )

        if pushed:
            QMessageBox.information(self, "成功", "已推送到微信")
        else:
            QMessageBox.warning(self, "失败", "推送到微信失败，请检查 Webhook 配置或服务状态")

    def on_add_service(self):
        d = AddServiceDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.get_data()
            name = data.pop('name')
            if name:
                data['models'] = [data['model']]
                data['use_markdown'] = True
                self.ai_data['services'][name] = data
                self.save_ai_data()
                self.refresh_ai_cards()
                self.refresh_ai_combo()

    def save_service_config(self, name, cfg):
        self.ai_data['services'][name] = cfg
        self.save_ai_data()

    def delete_service_config(self, name):
        if name in self.ai_data['services']:
            del self.ai_data['services'][name]
            self.save_ai_data()
            self.refresh_ai_cards()
            self.refresh_ai_combo()

    def rename_service(self, old_name, new_name):
        if old_name == new_name or not new_name: return
        if old_name in self.ai_data['services']:
            self.ai_data['services'][new_name] = self.ai_data['services'].pop(old_name)
            self.save_ai_data()
            self.refresh_ai_combo()

    def save_ai_data(self):
        with open(self.ai_path, 'w', encoding='utf-8') as f:
            json.dump(self.ai_data, f, ensure_ascii=False, indent=4)

    def on_add_prompt(self):
        name, ok = QInputDialog.getText(self, "新增提示词", "名称:")
        if ok and name:
            self.prompt_mgr.prompts[name] = ""
            self.p_list.addItem(name)
            self.prompt_mgr.save()

    def on_save_prompt(self):
        old_name = self.p_list.currentItem().text() if self.p_list.currentItem() else None
        new_name = self.p_name_in.text().strip()
        if old_name and new_name:
            # 如果重命名了
            if old_name != new_name:
                self.prompt_mgr.prompts[new_name] = self.p_edit.toPlainText()
                del self.prompt_mgr.prompts[old_name]
                self.p_list.currentItem().setText(new_name)
            else:
                self.prompt_mgr.prompts[new_name] = self.p_edit.toPlainText()

            self.prompt_mgr.save()
            QMessageBox.information(self, "成功", "已保存")

    def on_del_prompt(self):
        curr = self.p_list.currentItem()
        if curr and QMessageBox.question(self, "确认", f"删除 {curr.text()}?") == QMessageBox.Yes:
            del self.prompt_mgr.prompts[curr.text()]
            self.p_list.takeItem(self.p_list.currentRow())
            self.prompt_mgr.save()

    def on_p_selection_changed(self, curr, prev):
        if curr:
            name = curr.text()
            self.p_name_in.setText(name)
            self.p_edit.setPlainText(self.prompt_mgr.prompts.get(name, ""))

    def on_save_schedule(self):
        self.schedule_data = {
            "enabled": self.sched_on.isChecked(),
            "group": self.sched_g.text(),
            "time": self.sched_t.time().toString("HH:mm"),
            "ai_service": self.sched_ai.currentText(),
            "git_config": {
                "enabled": self.git_on.isChecked(),
                "repo": self.git_repo.text().strip(),
                "token": self.git_token.text().strip(),
                "branch": self.git_branch.text().strip() or "main"
            },
            "wechat_config": {
                "enabled": self.wx_on.isChecked(),
                "webhook_url": self.wx_webhook_url.text().strip(),
                "webhook_secret": self.wx_webhook_secret.text().strip(),
            }
        }
        with open(self.schedule_path, 'w', encoding='utf-8') as f:
            json.dump(self.schedule_data, f, ensure_ascii=False, indent=4)
        self.apply_schedule()
        QMessageBox.information(self, "成功", "定时任务、GitHub 与微信推送配置已更新")

    def apply_schedule(self):
        self.scheduler.remove_all_jobs()
        if not (self.schedule_data.get("enabled") and self.ai_data.get('services') and self.prompt_mgr.prompts):
            return

        t = self.schedule_data['time'].split(':')
        svc_name = self.schedule_data.get("ai_service")
        # 如果配置的服务不存在了，回退到第一个
        if not svc_name or svc_name not in self.ai_data['services']:
            svc_name = list(self.ai_data['services'].keys())[0]

        cfg = self.ai_data['services'][svc_name].copy()
        my_nickname = self.settings_data.get('my_nickname', '')
        prompt = list(self.prompt_mgr.prompts.values())[0]
        git_cfg = self.schedule_data.get("git_config")
        wechat_cfg = self.schedule_data.get("wechat_config")

        self.scheduler.add_job(
            auto_scheduled_task, 'cron',
            hour=int(t[0]), minute=int(t[1]),
            kwargs={
                'group_name': self.schedule_data['group'],
                'duration_hours': 24,
                'ai_config': cfg,
                'prompt_template': prompt,
                'git_config': git_cfg,
                'my_nickname': my_nickname,
                'wechat_config': wechat_cfg,
            },
            id='daily'
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="微信群聊总结助手")
    parser.add_argument("--minimized", action="store_true", help="启动时最小化到系统托盘")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    w = MainWindow()

    if args.minimized:
        w.hide() # 启动时隐藏
    else:
        w.show() # 默认显示

    sys.exit(app.exec())
