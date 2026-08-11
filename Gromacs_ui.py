#!/usr/bin/env python3

import os
import sys
import subprocess
import time
import shutil
import re
import tempfile
import fnmatch
import json
from datetime import datetime

# 添加psutil库的导入
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

# 获取脚本所在目录（应用目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 保存用户运行命令的目录（工作目录）
WORK_DIR = os.getcwd()

# 定义读取工作目录文件的辅助函数
def get_work_file_path(filename):
    """获取工作目录中文件的完整路径"""
    return os.path.join(WORK_DIR, filename)

def get_script_file_path(filename):
    """获取脚本目录中文件的完整路径"""
    return os.path.join(SCRIPT_DIR, filename)

def list_work_files(extension=None):
    """列出工作目录中的文件"""
    files = os.listdir(WORK_DIR)
    if extension:
        files = [f for f in files if f.endswith(extension)]
    return files

print(f"脚本目录: {SCRIPT_DIR}")
print(f"工作目录: {WORK_DIR}")

# 添加分析工具对话框的导入
sys.path.append(SCRIPT_DIR)
try:
    from analysis_tools_dialog import AnalysisToolsDialog
    ANALYSIS_TOOLS_AVAILABLE = True
except ImportError:
    ANALYSIS_TOOLS_AVAILABLE = False
    AnalysisToolsDialog = None

# 使用示例：
# - 读取工作目录文件：open(get_work_file_path('data.txt'), 'r')
# - 输出到工作目录：open(get_work_file_path('output.txt'), 'w')
# - 列出工作目录文件：files = list_work_files('.txt')
# - 调用子脚本：call_edr_preview('arg1', 'arg2')

#######################################################################################
# EDR File Preview Dialog
# Dependencies: PyQt5, matplotlib, numpy, pandas, pexpect (optional)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QTabWidget, QLabel,
                             QLineEdit, QPushButton, QTextEdit, QComboBox,
                             QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
                             QFileDialog, QMessageBox, QScrollArea, QFrame,
                             QSplitter, QProgressBar, QPlainTextEdit, QSizePolicy,
                             QInputDialog, QTableWidget, QAbstractItemView, QTableWidgetItem,
                             QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTextCodec, QSize, QTimer, QRegExp
from PyQt5.QtGui import QFont, QClipboard, QTextCursor, QTextCharFormat, QColor, QPalette, QSyntaxHighlighter

try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
except ImportError:
    print("matplotlib is not installed. Please install it using pip: pip install matplotlib")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("numpy is not installed. Please install it using pip: pip install numpy")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("pandas is not installed. Please install it using pip: pip install pandas")
    sys.exit(1)

try:
    import pexpect
    PEXPECT_AVAILABLE = True
except ImportError:
    PEXPECT_AVAILABLE = False

# 添加 PyQt5 的 QtWidgets 导入
from PyQt5 import QtWidgets, QtCore, QtGui

# Wong色盲友好调色板
NATURE_COLORS = [
    '#000000',  # 黑色
    '#E69F00',  # 橙色
    '#56B4E9',  # 天蓝色
    '#009E73',  # 蓝绿色
    '#F0E442',  # 黄色
    '#0072B2',  # 蓝色
    '#D55E00',  # 红橙色
    '#CC79A7'   # 粉红色
]

####################################################################################
# MDP文件语法高亮器
####################################################################################

class MDPHighlighter(QSyntaxHighlighter):
    """MDP文件语法高亮器"""
    
    def __init__(self, document):
        super().__init__(document)

        # 注释格式（绿色斜体）
        commentFormat = QTextCharFormat()
        commentFormat.setForeground(QColor("#228B22"))
        commentFormat.setFontItalic(True)
        self.commentPattern = QRegExp(r";[^\n]*")

        # 参数名格式（蓝色粗体）
        paramFormat = QTextCharFormat()
        paramFormat.setForeground(QColor("#1E90FF"))
        paramFormat.setFontWeight(QFont.Bold)
        self.paramPattern = QRegExp(r"^[a-zA-Z0-9_-]+(?=\s*=)")

        # 参数值格式（红色普通）
        valueFormat = QTextCharFormat()
        valueFormat.setForeground(QColor("#B22222"))
        self.valuePattern = QRegExp(r"=\s*[^;]+")

        # 高亮规则
        self.highlightingRules = [
            (self.commentPattern, commentFormat),
            (self.paramPattern, paramFormat),
            (self.valuePattern, valueFormat),
        ]

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

####################################################################################
# 绘图组件
####################################################################################

class PlotWidget(QWidget):
    """ matplotlib 绘图组件 """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Time (ps)')
        self.ax.set_ylabel('Energy (kJ/mol)')
        self.ax.grid(True)
        self.canvas.draw()
    
    def plot_data(self, data_dict, options=None):
        """绘制数据"""
        self.ax.clear()
        
        if options is None:
            options = {}
        
        grid = options.get('grid', True)
        smooth = options.get('smooth', False)
        smooth_window = options.get('smooth_window', 10)
        log_scale = options.get('log_scale', False)
        linewidth = options.get('linewidth', 1.5)
        
        self.ax.grid(grid)
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        
        for idx, (term_name, data) in enumerate(data_dict.items()):
            time = data['time']
            values = data['values']
            
            if smooth and len(values) > smooth_window:
                np_values = np.array(values)
                cumsum = np.cumsum(np_values)
                cumsum[ smooth_window:] = cumsum[ smooth_window:] - cumsum[:- smooth_window]
                values = cumsum[ smooth_window - 1:] / smooth_window
            
            color = colors[idx % len(colors)]
            self.ax.plot(time, values, label=term_name, linewidth=linewidth, color=color)
        
        self.ax.set_xlabel('Time (ps)')
        self.ax.set_ylabel('Energy (kJ/mol)')
        self.ax.legend()
        
        if log_scale:
            self.ax.set_yscale('log')
        
        self.canvas.draw()

####################################################################################
# EDR能量数据提取线程
####################################################################################

def parse_edr_energy_terms(edr_file):
    """解析EDR文件，获取可用的能量项列表
    
    Args:
        edr_file: EDR文件路径
        
    Returns:
        dict: {索引号: 能量项名称}，如 {"11": "Potential", "15": "Temperature", ...}
    """
    import re
    
    term_dict = {}
    
    try:
        # 运行gmx energy -f <edr_file>获取可用能量项
        # 不需要传递输入，直接输出可用能量项列表
        proc = subprocess.Popen(
            ['gmx', 'energy', '-f', edr_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 发送空行退出
        stdout, stderr = proc.communicate(input="\n\n", timeout=30)
        
        output = stdout
        
        # 解析能量项
        # 格式: "1 Bond 2 Angle 3 Proper-Dih. 4 Per.-Imp.-Dih."
        # 每行有4个能量项
        lines = output.split('\n')
        
        for line in lines:
            # 匹配 "数字 名称" 的模式
            # 能量项名称可能包含: 字母、数字、点、连字符、括号等
            matches = re.findall(r'(\d+)\s+([\w\.\-\(\)]+)', line)
            for match in matches:
                term_num = match[0]
                term_name = match[1]
                term_dict[term_num] = term_name
        
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        pass
    
    return term_dict


class GromacsEnergyExtractor(QThread):
    """EDR能量数据提取线程类"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict, str)
    
    def __init__(self, edr_file, selected_terms):
        super().__init__()
        self.edr_file = edr_file
        self.selected_terms = selected_terms
    
    def run(self):
        """Extract energy data"""
        data_dict = {}
        error_msg = ""
        
        try:
            self.progress.emit("="*50)
            self.progress.emit("Starting energy data extraction...")
            self.progress.emit(f"EDR file: {self.edr_file}")
            self.progress.emit(f"Selected energy terms: {self.selected_terms}")
            
            import os
            import shutil
            
            gmx_path = shutil.which('gmx')
            self.progress.emit(f"gmx path: {gmx_path}")
            
            if not gmx_path:
                error_msg = "未找到gmx命令，请确保GROMACS已安装"
                self.progress.emit(error_msg)
                self.finished.emit(data_dict, error_msg)
                return
            
            if not os.path.exists(self.edr_file):
                error_msg = f"EDR file does not exist: {self.edr_file}"
                self.progress.emit(error_msg)
                self.finished.emit(data_dict, error_msg)
                return
            
            term_numbers = list(self.selected_terms.keys())
            self.progress.emit(f"Energy term numbers: {term_numbers}")
            
            import tempfile
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xvg', delete=False) as tmp_file:
                tmp_output = tmp_file.name
            
            self.progress.emit(f"Temporary output file: {tmp_output}")
            
            try:
                term_input = " ".join(term_numbers) + "\n\n"
                
                self.progress.emit(f"Sending input: {repr(term_input)}")
                
                if os.path.exists(tmp_output):
                    os.unlink(tmp_output)
                
                cmd = ['gmx', 'energy', '-f', self.edr_file, '-o', tmp_output, '-xvg', 'none']
                self.progress.emit(f"Executing command: {' '.join(cmd)}")
                
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                self.progress.emit("Waiting for gmx energy response...")
                stdout, stderr = proc.communicate(input=term_input, timeout=300)
                
                self.progress.emit(f"Command return code: {proc.returncode}")
                
                if stdout:
                    self.progress.emit(f"stdout (first 500 chars):\n{stdout[:500]}")
                else:
                    self.progress.emit("stdout: empty")
                
                if stderr:
                    self.progress.emit(f"stderr (first 500 chars):\n{stderr[:500]}")
                else:
                    self.progress.emit("stderr: empty")
                
                if proc.returncode != 0:
                    error_msg = f"gmx energy failed, return code: {proc.returncode}\nstderr: {stderr}"
                    self.progress.emit(f"Error: {error_msg}")
                    self.finished.emit(data_dict, error_msg)
                    return
                
                if not os.path.exists(tmp_output):
                    error_msg = f"Output file not generated: {tmp_output}"
                    self.progress.emit(error_msg)
                    self.finished.emit(data_dict, error_msg)
                    return
                
                file_size = os.path.getsize(tmp_output)
                self.progress.emit(f"Output file size: {file_size} bytes")
                
                if file_size == 0:
                    error_msg = "Output file is empty"
                    self.progress.emit(error_msg)
                    self.finished.emit(data_dict, error_msg)
                    return
                
                with open(tmp_output, 'r') as f:
                    output = f.read()
                
                self.progress.emit(f"Output file content length: {len(output)} chars")
                self.progress.emit(f"Output file (first 200 chars):\n{output[:200]}")
                
                time_data = []
                value_dict = {term_name: [] for term_name in self.selected_terms.values()}
                
                lines = output.split('\n')
                self.progress.emit(f"Total lines: {len(lines)}")
                
                data_lines_count = 0
                num_terms = len(self.selected_terms)
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('#') or line.startswith('@'):
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            time_val = float(parts[0])
                            time_data.append(time_val)
                            data_lines_count += 1
                            
                            for i, term_name in enumerate(self.selected_terms.values()):
                                if i + 1 < len(parts):
                                    val = float(parts[i + 1])
                                    value_dict[term_name].append(val)
                                else:
                                    value_dict[term_name].append(float('nan'))
                        except ValueError as e:
                            continue
                
                self.progress.emit(f"Data lines: {data_lines_count}")
                self.progress.emit(f"time_data length: {len(time_data)}")
                
                valid_time_length = len(time_data)
                for term_name, values in list(value_dict.items()):
                    actual_length = len(values)
                    if actual_length != valid_time_length:
                        self.progress.emit(f"Warning: {term_name} has {actual_length} values, expected {valid_time_length}. Truncating...")
                        value_dict[term_name] = values[:valid_time_length]
                
                for term_name, values in value_dict.items():
                    self.progress.emit(f"{term_name}: {len(values)} data points")
                    if values:
                        valid_values = [v for v in values if not np.isnan(v)]
                        if valid_values:
                            self.progress.emit(f"  Min: {min(valid_values)}, Max: {max(valid_values)}")
                
                for term_name, values in value_dict.items():
                    if values:
                        data_dict[term_name] = {
                            'time': time_data[:len(values)],
                            'values': values
                        }
                
                self.progress.emit(f"Successfully extracted {len(data_dict)} energy terms")
                self.progress.emit("="*50)
                
            finally:
                if os.path.exists(tmp_output):
                    os.unlink(tmp_output)
        
        except subprocess.TimeoutExpired:
            error_msg = "Data extraction timeout (300 seconds)"
            self.progress.emit(error_msg)
        except FileNotFoundError as e:
            error_msg = f"找不到文件: {e}"
            self.progress.emit(error_msg)
        except Exception as e:
            error_msg = str(e)
            import traceback
            self.progress.emit(f"错误: {traceback.format_exc()}")
        
        self.finished.emit(data_dict, error_msg)

####################################################################################
# 语言管理器和国际化支持
####################################################################################

class LanguageManager:
    """语言管理器类，负责UI的中英文切换"""
    
    def __init__(self):
        self.current_language = 'zh'  # 默认中文
        self.translations = {
            # 主窗口标题
            'window_title': {
                'zh': 'GROMACS Molecular Dynamics Interface',
                'en': 'GROMACS Molecular Dynamics Interface'
            },
            
            # 文件选择区域
            'file_selection': {
                'zh': '文件选择',
                'en': 'File Selection'
            },
            'working_directory': {
                'zh': '工作目录:',
                'en': 'Working Directory:'
            },
            'browse': {
                'zh': '浏览',
                'en': 'Browse'
            },
            'pdb_file': {
                'zh': 'PDB文件:',
                'en': 'PDB File:'
            },
            'gro_file': {
                'zh': 'GRO文件:',
                'en': 'GRO File:'
            },
            'top_file': {
                'zh': 'TOP文件:',
                'en': 'TOP File:'
            },
            'itp_file_optional': {
                'zh': 'ITP文件 (可选):',
                'en': 'ITP File (Optional):'
            },
            'auto_fill_files': {
                'zh': '自动填充文件',
                'en': 'Auto Fill Files'
            },
            
            # 模拟类型选择
            'simulation_type': {
                'zh': '模拟类型',
                'en': 'Simulation Type'
            },
            'select_simulation_type': {
                'zh': '选择模拟类型:',
                'en': 'Select Simulation Type:'
            },
            'gas_simulation': {
                'zh': '气相模拟',
                'en': 'Gas Phase Simulation'
            },
            'solution_simulation': {
                'zh': '溶液模拟',
                'en': 'Solution Simulation'
            },
            'crystal_simulation': {
                'zh': '晶体模拟',
                'en': 'Crystal Simulation'
            },
            'membrane_simulation': {
                'zh': '膜模拟',
                'en': 'Membrane Simulation'
            },
            'vacuum_simulation': {
                'zh': '真空模拟',
                'en': 'Vacuum Simulation'
            },
            'free_energy_calculation': {
                'zh': '自由能计算',
                'en': 'Free Energy Calculation'
            },
            
            # 工作流程状态
            'workflow_status': {
                'zh': '工作流程状态',
                'en': 'Workflow Status'
            },
            'workflow_progress': {
                'zh': '工作流程进度: {}/{} 已完成 - {}',
                'en': 'Workflow Progress: {}/{} Completed - {}'
            },
            'please_run_minimization': {
                'zh': '请先运行能量最小化',
                'en': 'Please run energy minimization first'
            },
            'can_run_next': {
                'zh': '可以运行{}',
                'en': 'Can run {}'
            },
            'workflow_complete': {
                'zh': '工作流程完成',
                'en': 'Workflow complete'
            },
            
            # 标签页名称
            'structure_centering': {
                'zh': '结构居中',
                'en': 'Structure Centering'
            },
            'energy_minimization': {
                'zh': '能量最小化',
                'en': 'Energy Minimization'
            },
            'nvt_equilibration': {
                'zh': 'NVT平衡',
                'en': 'NVT Equilibration'
            },
            'npt_equilibration': {
                'zh': 'NPT平衡',
                'en': 'NPT Equilibration'
            },
            'production_run': {
                'zh': '生产运行',
                'en': 'Production Run'
            },
            'command_generation': {
                'zh': '命令生成',
                'en': 'Command Generation'
            },
            
            # 右侧输出面板标签页
            # 'structure_centering_info': {
            #     'zh': '结构居中信息',
            #     'en': 'Structure Centering Info'
            # },
            'mdp_preview': {
                'zh': 'MDP预览',
                'en': 'MDP Preview'
            },
            'command_preview': {
                'zh': '命令预览',
                'en': 'Command Preview'
            },
            'realtime_output': {
                'zh': '实时输出',
                'en': 'Real-time Output'
            },
            'execution_log': {
                'zh': '执行日志',
                'en': 'Execution Log'
            },
            'file_status': {
                'zh': '文件状态',
                'en': 'File Status'
            },
            'language_settings': {
                'zh': '语言设置',
                'en': 'Language Settings'
            },
            
            # 按钮和控件
            'generate_mdp': {
                'zh': '生成{}MDP',
                'en': 'Generate {} MDP'
            },
            'start_execution': {
                'zh': '开始执行',
                'en': 'Start Execution'
            },
            'stop_execution': {
                'zh': '停止执行',
                'en': 'Stop Execution'
            },
            'clear_output': {
                'zh': '清空输出',
                'en': 'Clear Output'
            },
            'clear_log': {
                'zh': '清空日志',
                'en': 'Clear Log'
            },
            'update_file_status': {
                'zh': '更新文件状态',
                'en': 'Update File Status'
            },
            'file_preview': {
                'zh': '文件预览',
                'en': 'File Preview'
            },
            'structure_preview_vmd': {
                'zh': '结构预览 (VMD)',
                'en': 'Structure Preview (VMD)'
            },
            'save_mdp_file': {
                'zh': '保存MDP文件',
                'en': 'Save MDP File'
            },
            'select_existing_mdp': {
                'zh': '选择现有MDP文件',
                'en': 'Select Existing MDP File'
            },
            'generate_command': {
                'zh': '生成命令',
                'en': 'Generate Command'
            },
            'execute_command': {
                'zh': '执行命令',
                'en': 'Execute Command'
            },
            'copy_command': {
                'zh': '复制命令',
                'en': 'Copy Command'
            },
            'save_script': {
                'zh': '保存脚本',
                'en': 'Save Script'
            },
            
            # 状态信息
            'ready': {
                'zh': '就绪',
                'en': 'Ready'
            },
            'executing': {
                'zh': '正在执行...',
                'en': 'Executing...'
            },
            'execution_complete': {
                'zh': '执行完成',
                'en': 'Execution Complete'
            },
            'execution_failed': {
                'zh': '执行失败',
                'en': 'Execution Failed'
            },
            'status': {
                'zh': '状态:',
                'en': 'Status:'
            },
            
            # 语言切换界面
            'current_language': {
                'zh': '当前语言:',
                'en': 'Current Language:'
            },
            'chinese': {
                'zh': '中文',
                'en': 'Chinese'
            },
            'english': {
                'zh': '英文',
                'en': 'English'
            },
            'switch_language': {
                'zh': '切换语言',
                'en': 'Switch Language'
            },
            'language_switch_success': {
                'zh': '语言切换成功！界面已更新为{}',
                'en': 'Language switched successfully! Interface updated to {}'
            },
            'restart_note': {
                'zh': '注意：部分界面元素需要重启程序才能完全切换语言',
                'en': 'Note: Some UI elements require program restart for complete language switching'
            },
            
            # 参数相关
            'timestep': {
                'zh': '时间步长',
                'en': 'Time Step'
            },
            'nsteps': {
                'zh': '步数',
                'en': 'Number of Steps'
            },
            'temperature_coupling': {
                'zh': '温度耦合方法',
                'en': 'Temperature Coupling'
            },
            'pressure_coupling': {
                'zh': '压力耦合方法',
                'en': 'Pressure Coupling'
            },
            'pressure_coupling_type': {
                'zh': '压力耦合类型',
                'en': 'Pressure Coupling Type'
            },
            'reference_pressure': {
                'zh': '参考压力',
                'en': 'Reference Pressure'
            },
            'reference_temperature': {
                'zh': '参考温度',
                'en': 'Reference Temperature'
            },
            
            # 消息框
            'warning': {
                'zh': '警告',
                'en': 'Warning'
            },
            'error': {
                'zh': '错误',
                'en': 'Error'
            },
            'information': {
                'zh': '信息',
                'en': 'Information'
            },
            'success': {
                'zh': '成功',
                'en': 'Success'
            },
            'confirm': {
                'zh': '确认',
                'en': 'Confirm'
            },
            
            # 工作流程提示
            'workflow_hints': {
                'zh': {
                    '气相模拟': '工作流程: 结构文件 → 能量最小化 → NVT平衡 → 生产运行',
                    '溶液模拟': '工作流程: PDB → 结构处理 → 加盒子 → 溶剂化 → 加离子 → 能量最小化 → NVT → NPT → 生产运行',
                    '晶体模拟': '工作流程: 晶胞结构 → 能量最小化 → NVT平衡 → NPT平衡 → 生产运行',
                    '膜模拟': '工作流程: 膜体系结构 → 能量最小化 → NVT平衡 → NPT平衡(半各向同性) → 生产运行',
                    '真空模拟': '工作流程: 单分子结构 → 能量最小化 → 生产运行',
                    '自由能计算': '工作流程: 系统准备 → 能量最小化 → NVT平衡 → NPT平衡 → 多窗口生产运行'
                },
                'en': {
                    'Gas Phase Simulation': 'Workflow: Structure File → Energy Minimization → NVT Equilibration → NPT Equilibration → Production Run',
                    'Solution Simulation': 'Workflow: PDB → Structure Processing → Add Box → Solvation → Add Ions → Energy Minimization → NVT → NPT → Production Run',
                    'Crystal Simulation': 'Workflow: Crystal Structure → Energy Minimization → NVT Equilibration → NPT Equilibration → Production Run',
                    'Membrane Simulation': 'Workflow: Membrane System → Energy Minimization → NVT Equilibration → NPT Equilibration(Semi-isotropic) → Production Run',
                    'Vacuum Simulation': 'Workflow: Single Molecule → Energy Minimization → Production Run',
                    'Free Energy Calculation': 'Workflow: System Preparation → Energy Minimization → NVT Equilibration → NPT Equilibration → Multi-window Production Run'
                }
            }
        }
    
    def get_text(self, key, *args, **kwargs):
        """获取当前语言的文本"""
        if key in self.translations:
            text = self.translations[key].get(self.current_language, key)
            if args or kwargs:
                try:
                    return text.format(*args, **kwargs)
                except:
                    return text
            return text
        return key
    
    def set_language(self, language):
        """设置语言"""
        if language in ['zh', 'en']:
            self.current_language = language
            return True
        return False
    
    def get_current_language(self):
        """获取当前语言"""
        return self.current_language
    
    def get_language_name(self, lang_code):
        """获取语言名称"""
        names = {
            'zh': {'zh': '中文', 'en': 'Chinese'},
            'en': {'zh': '英文', 'en': 'English'}
        }
        return names.get(lang_code, {}).get(self.current_language, lang_code)

# 全局语言管理器实例
lang_manager = LanguageManager()

# Import EdrPreviewDialog for EDR file preview
EDR_PREVIEW_AVAILABLE = True

class EdrPreviewDialog(QtWidgets.QDialog):
    """EDR文件预览对话框，集成到GromacsUI中"""
    
    def __init__(self, edr_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"GROMACS EDR 文件分析 - {os.path.basename(edr_path)}")
        self.setGeometry(100, 100, 1200, 800)
        self.edr_file = edr_path
        
        # 动态解析EDR文件获取可用能量项
        self.available_terms = self.parse_edr_terms_from_file()
        
        # 如果动态解析失败，使用备用默认值
        if not self.available_terms:
            self.available_terms = self.get_default_terms()
        
        self.current_data = {}
        
        self.init_ui()
    
    def parse_edr_terms_from_file(self):
        """从EDR文件动态解析可用能量项"""
        import re
        
        term_dict = {}
        
        try:
            proc = subprocess.Popen(
                ['gmx', 'energy', '-f', self.edr_file],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = proc.communicate(input="\n\n", timeout=30)
            output = stdout
            
            # 解析能量项
            lines = output.split('\n')
            
            for line in lines:
                matches = re.findall(r'(\d+)\s+([\w\.\-\(\)]+)', line)
                for match in matches:
                    term_num = match[0]
                    term_name = match[1]
                    term_dict[term_num] = term_name
            
        except Exception as e:
            print(f"解析EDR能量项失败: {e}")
        
        return term_dict
    
    def get_default_terms(self):
        """获取默认能量项列表（备用）"""
        return {
            '1': 'Bond', '2': 'Angle', '3': 'Proper-Dih.', '4': 'Per.-Imp.-Dih.',
            '5': 'LJ-14', '6': 'Coulomb-14', '7': 'LJ-(SR)', '8': 'Disper.-corr.',
            '9': 'Coulomb-(SR)', '10': 'Coul.-recip.', '11': 'Potential', '12': 'Kinetic-En.',
            '13': 'Total-Energy', '14': 'Conserved-En.', '15': 'Temperature', '16': 'Pres.-DC',
            '17': 'Pressure', '18': 'Constr.-rmsd', '19': 'Vir-XX', '20': 'Vir-XY',
            '21': 'Vir-XZ', '22': 'Vir-YX', '23': 'Vir-YY', '24': 'Vir-YZ',
            '25': 'Vir-ZX', '26': 'Vir-ZY', '27': 'Vir-ZZ', '28': 'Pres-XX',
            '29': 'Pres-XY', '30': 'Pres-XZ', '31': 'Pres-YX', '32': 'Pres-YY',
            '33': 'Pres-YZ', '34': 'Pres-ZX', '35': 'Pres-ZY', '36': 'Pres-ZZ',
            '37': '#Surf*SurfTen', '38': 'T-System', '39': 'Lamb-System'
        }
    
    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QHBoxLayout(self)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 创建左侧控制面板
        control_panel = self.create_control_panel()
        
        # 创建右侧绘图区域
        plot_panel = self.create_plot_panel()
        
        splitter.addWidget(control_panel)
        splitter.addWidget(plot_panel)
        splitter.setSizes([350, 850])
        
        main_layout.addWidget(splitter)
        
        # 初始化轨迹分析相关属性
        self.trajectory_analysis_data = {}
        self.simulation_type = self.detect_simulation_type()
    
    def create_control_panel(self):
        """Create control panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # File selection
        file_group = QGroupBox("File Selection")
        file_layout = QVBoxLayout(file_group)
        
        self.file_label = QLabel(f"Selected: {os.path.basename(self.edr_file)}")
        self.file_label.setWordWrap(True)
        file_layout.addWidget(self.file_label)
        
        layout.addWidget(file_group)
        
        # Energy term selection
        terms_group = QGroupBox("Energy Term Selection")
        terms_layout = QVBoxLayout(terms_group)
        
        # Quick selection - dynamically based on available terms
        quick_layout = QGridLayout()
        
        self.quick_checkboxes = {}
        
        # Define preferred term names to look for
        preferred_names = ['Potential', 'Temperature', 'Pressure', 'Total-Energy', 'Kinetic-En.', 'Conserved-En.']
        
        # Find available terms that match preferred names
        quick_terms = []
        for term_num, term_name in self.available_terms.items():
            for pref_name in preferred_names:
                if pref_name.lower() in term_name.lower():
                    quick_terms.append((term_num, term_name))
                    break
        
        # Create checkboxes for first 6 available quick terms
        for idx, (term_num, term_name) in enumerate(quick_terms[:6]):
            row = idx // 2
            col = idx % 2
            checkbox = QCheckBox(term_name)
            checkbox.setChecked(False)
            self.quick_checkboxes[term_num] = checkbox
            quick_layout.addWidget(checkbox, row, col)
        
        terms_layout.addLayout(quick_layout)
        
        # All energy terms list
        self.terms_list = QtWidgets.QListWidget()
        self.terms_list.setSelectionMode(QtWidgets.QListWidget.MultiSelection)
        sorted_terms = sorted(self.available_terms.items(), key=lambda x: int(x[0]))
        for term_num, term_name in sorted_terms:
            self.terms_list.addItem(f"{term_num}: {term_name}")
        terms_layout.addWidget(self.terms_list)
        
        layout.addWidget(terms_group)
        
        # Plot options
        plot_group = QGroupBox("Plot Options")
        plot_layout = QVBoxLayout(plot_group)
        
        self.grid_check = QCheckBox("Show Grid")
        self.grid_check.setChecked(True)
        plot_layout.addWidget(self.grid_check)
        
        self.smooth_check = QCheckBox("Smooth Curve")
        plot_layout.addWidget(self.smooth_check)
        
        smooth_layout = QHBoxLayout()
        smooth_layout.addWidget(QLabel("Window Size:"))
        self.smooth_window = QSpinBox()
        self.smooth_window.setRange(2, 100)
        self.smooth_window.setValue(10)
        smooth_layout.addWidget(self.smooth_window)
        plot_layout.addLayout(smooth_layout)
        
        self.log_scale_check = QCheckBox("Log Scale")
        plot_layout.addWidget(self.log_scale_check)
        
        linewidth_layout = QHBoxLayout()
        linewidth_layout.addWidget(QLabel("Line Width:"))
        self.linewidth_spin = QDoubleSpinBox()
        self.linewidth_spin.setRange(0.5, 5.0)
        self.linewidth_spin.setValue(1.5)
        self.linewidth_spin.setSingleStep(0.5)
        linewidth_layout.addWidget(self.linewidth_spin)
        plot_layout.addLayout(linewidth_layout)
        
        layout.addWidget(plot_group)
        
        # Buttons
        buttons_layout = QVBoxLayout()
        
        self.extract_btn = QPushButton("Extract Data")
        self.extract_btn.clicked.connect(self.extract_energy_data)
        buttons_layout.addWidget(self.extract_btn)
        
        self.plot_btn = QPushButton("Plot Chart")
        self.plot_btn.clicked.connect(self.plot_data)
        self.plot_btn.setEnabled(False)
        buttons_layout.addWidget(self.plot_btn)
        
        self.save_plot_btn = QPushButton("Save Chart")
        self.save_plot_btn.clicked.connect(self.save_plot)
        self.save_plot_btn.setEnabled(False)
        buttons_layout.addWidget(self.save_plot_btn)
        
        self.export_data_btn = QPushButton("Export Data")
        self.export_data_btn.clicked.connect(self.export_data)
        self.export_data_btn.setEnabled(False)
        buttons_layout.addWidget(self.export_data_btn)
        
        layout.addLayout(buttons_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status text
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(100)
        self.status_text.setPlaceholderText("Status information will be displayed here...")
        layout.addWidget(self.status_text)
        
        layout.addStretch()
        return panel
    
    def create_plot_panel(self):
        """Create plot panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        
        # Plot tab
        plot_tab = QWidget()
        plot_layout = QVBoxLayout(plot_tab)
        
        self.plot_widget = PlotWidget()
        plot_layout.addWidget(self.plot_widget)
        
        self.tab_widget.addTab(plot_tab, "Chart")
        
        # Data tab
        data_tab = QWidget()
        data_layout = QVBoxLayout(data_tab)
        
        self.data_text = QTextEdit()
        self.data_text.setPlaceholderText("Data statistics will be displayed here...")
        self.data_text.setFont(QFont("Courier", 10))
        data_layout.addWidget(self.data_text)
        
        self.tab_widget.addTab(data_tab, "Data Statistics")
        
        layout.addWidget(self.tab_widget)
        
        return panel
    
    def extract_energy_data(self):
        """Extract energy data"""
        # Get selected terms
        selected_terms = self.get_selected_terms()
        
        if not selected_terms:
            QMessageBox.warning(self, "Warning", "Please select at least one energy term!")
            return
        
        # Show progress bar
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Create and start extraction thread
        self.extractor = GromacsEnergyExtractor(self.edr_file, selected_terms)
        self.extractor.progress.connect(self.update_status)
        self.extractor.finished.connect(self.on_extraction_finished)
        self.extractor.start()
    
    def get_selected_terms(self):
        """Get user selected energy terms"""
        selected = {}
        
        # From quick checkboxes
        for term_num, checkbox in self.quick_checkboxes.items():
            if checkbox.isChecked():
                selected[term_num] = self.available_terms[term_num]
        
        # From list
        for item in self.terms_list.selectedItems():
            text = item.text()
            term_num = text.split(':')[0]
            if term_num in self.available_terms:
                selected[term_num] = self.available_terms[term_num]
        
        return selected
    
    def on_extraction_finished(self, data_dict, error):
        """Handle data extraction completion"""
        self.progress_bar.setVisible(False)
        
        if error:
            QMessageBox.critical(self, "Error", f"Data extraction failed:\n{error}")
            return
        
        if not data_dict:
            QMessageBox.warning(self, "Warning", "No data extracted!")
            return
        
        self.current_data = data_dict
        self.plot_btn.setEnabled(True)
        self.save_plot_btn.setEnabled(True)
        self.export_data_btn.setEnabled(True)
        
        # Show data statistics
        self.show_data_statistics()
        
        self.update_status(f"Successfully extracted {len(data_dict)} energy terms")
    
    def show_data_statistics(self):
        """Show data statistics"""
        if not self.current_data:
            return
        
        stats_text = "Data Statistics:\n" + "="*50 + "\n\n"
        
        for term_name, data in self.current_data.items():
            values = data['values']
            time = data['time']
            
            stats_text += f"{term_name}:\n"
            stats_text += f"  Data points: {len(values)}\n"
            stats_text += f"  Time range: {time[0]:.2f} - {time[-1]:.2f} ps\n"
            stats_text += f"  Mean: {np.mean(values):.4f}\n"
            stats_text += f"  Std Dev: {np.std(values):.4f}\n"
            stats_text += f"  Min: {np.min(values):.4f}\n"
            stats_text += f"  Max: {np.max(values):.4f}\n"
            stats_text += "-" * 30 + "\n"
        
        self.data_text.setPlainText(stats_text)
    
    def plot_data(self):
        """Plot data"""
        if not self.current_data:
            QMessageBox.warning(self, "Warning", "No data to plot!")
            return
        
        plot_options = {
            'grid': self.grid_check.isChecked(),
            'smooth': self.smooth_check.isChecked(),
            'smooth_window': self.smooth_window.value(),
            'log_scale': self.log_scale_check.isChecked(),
            'linewidth': self.linewidth_spin.value()
        }
        
        self.plot_widget.plot_data(self.current_data, plot_options)
        self.update_status("Chart updated")
    
    def save_plot(self):
        """Save plot"""
        if not self.current_data:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Chart",
            "",
            "PNG files (*.png);;PDF files (*.pdf);;SVG files (*.svg);;All files (*.*)"
        )
        
        if file_path:
            try:
                self.plot_widget.figure.savefig(file_path, dpi=300, bbox_inches='tight')
                self.update_status(f"Chart saved to: {file_path}")
                QMessageBox.information(self, "Success", "Chart saved successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save chart:\n{str(e)}")
    
    def export_data(self):
        """Export data to CSV file"""
        if not self.current_data:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Data",
            "",
            "CSV files (*.csv);;All files (*.*)"
        )
        
        if file_path:
            try:
                # Find longest time series
                max_length = max(len(data['time']) for data in self.current_data.values())
                
                # Create CSV
                import csv
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    
                    # Write header
                    headers = ['Time (ps)']
                    for term_name in self.current_data.keys():
                        headers.append(term_name)
                    writer.writerow(headers)
                    
                    # Write data rows
                    for i in range(max_length):
                        row = []
                        time_added = False
                        
                        for term_name, data in self.current_data.items():
                            if i < len(data['time']):
                                if not time_added:
                                    row.append(data['time'][i])
                                    time_added = True
                                row.append(data['values'][i])
                            else:
                                if not time_added:
                                    row.append('')
                                    time_added = True
                                row.append('')
                        
                        writer.writerow(row)
                
                self.update_status(f"Data exported to: {file_path}")
                QMessageBox.information(self, "Success", "Data exported successfully!")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export data:\n{str(e)}")
    
    def update_status(self, message):
        """更新状态信息"""
        self.status_text.append(f"[{self.get_current_time()}] {message}")
        
        # 滚动到底部
        cursor = self.status_text.textCursor()
        cursor.movePosition(cursor.End)
        self.status_text.setTextCursor(cursor)
    
    def get_current_time(self):
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")
    
    def detect_simulation_type(self):
        """检测当前模拟类型"""
        # 尝试从工作目录中的文件推断模拟类型
        work_dir = os.path.dirname(self.edr_file)
        
        # 检查是否存在特定文件来推断模拟类型
        if os.path.exists(os.path.join(work_dir, 'em.gro')) and not os.path.exists(os.path.join(work_dir, 'nvt.gro')):
            return '真空模拟'  # 只有EM，没有NVT，可能是真空模拟
        elif os.path.exists(os.path.join(work_dir, 'nvt.gro')) and not os.path.exists(os.path.join(work_dir, 'npt.gro')):
            return '气相模拟'  # 有NVT，没有NPT，可能是气相模拟
        elif os.path.exists(os.path.join(work_dir, 'npt.gro')):
            # 有NPT，可能是溶液、晶体或膜模拟
            # 检查是否有溶剂化文件
            if os.path.exists(os.path.join(work_dir, 'solvated.gro')) or os.path.exists(os.path.join(work_dir, 'ionized.gro')):
                return '溶液模拟'
            else:
                return '晶体模拟'  # 默认为晶体模拟
        
        return '溶液模拟'  # 默认为溶液模拟
    
    def get_simulation_type_info(self, sim_type):
        """获取模拟类型的分析信息"""
        sim_info = {
            '真空模拟': {
                'description': '真空模拟（单分子/小分子团，无周期性边界）',
                'applicable_analyses': ['RMSD', '二面角', '回旋半径'],
                'caution_analyses': ['MSD'],
                'inapplicable_analyses': ['RDF', '氢键'],
                'msd_fit_range': (0.2, 0.9),
                'rmsd_default_align': 'System',
                'notes': '真空MSD仅反映布朗运动，扩散系数无凝聚态物理意义；RDF和氢键不适用',
                'msd_warning': '真空单分子MSD仅反映布朗运动，扩散系数无凝聚态物理意义'
            },
            '气相模拟': {
                'description': '气相模拟（多个气体分子，有周期性边界）',
                'applicable_analyses': ['RMSD', '二面角', 'MSD', '氢键', '回旋半径'],
                'caution_analyses': ['RDF'],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.2, 0.8),
                'rmsd_default_align': 'System',
                'notes': 'RDF可选，截断半径不应超过盒子半长的1/2',
                'msd_warning': ''
            },
            '溶液模拟': {
                'description': '溶液模拟（蛋白质/小分子在水中）',
                'applicable_analyses': ['RMSD', '二面角', 'RDF', 'MSD', '氢键', '回旋半径'],
                'caution_analyses': [],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.2, 0.8),
                'rmsd_default_align': 'Backbone',
                'notes': '适用于所有分析功能。RDF需选择溶质-溶剂原子对；氢键需区分分子内/分子间',
                'msd_warning': ''
            },
            '晶体模拟': {
                'description': '晶体模拟（固体材料）',
                'applicable_analyses': ['RMSD', '二面角', '回旋半径'],
                'caution_analyses': ['MSD', 'RDF'],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.3, 0.7),
                'rmsd_default_align': 'System',
                'notes': '晶体MSD主要反映原子振动（~0.01 nm²量级），非扩散；RDF即对分布函数g(r)',
                'msd_warning': '晶体中原子MSD主要反映振动而非扩散，数值通常很小'
            },
            '膜模拟': {
                'description': '膜模拟（生物膜/膜蛋白）',
                'applicable_analyses': ['RMSD', '二面角', 'RDF', 'MSD', '氢键', '回旋半径'],
                'caution_analyses': [],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.2, 0.8),
                'rmsd_default_align': 'Backbone',
                'notes': 'MSD需分别分析膜平面内（xy）和垂直方向（z）的扩散',
                'msd_warning': ''
            }
        }
        return sim_info.get(sim_type, sim_info['溶液模拟'])

    def open_trajectory_analysis(self):
        """打开轨迹分析对话框"""
        working_dir = os.path.dirname(self.edr_file) if self.edr_file else os.getcwd()
        dialog = TrajectoryAnalysisDialog(working_dir, self.simulation_type, self)
        dialog.exec_()


class TrajectoryAnalysisDialog(QtWidgets.QDialog):
    """轨迹后处理分析对话框"""
    
    def __init__(self, working_dir: str, simulation_type: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GROMACS 轨迹后处理分析")
        self.setGeometry(100, 100, 1200, 800)
        self.simulation_type = simulation_type
        self.working_dir = working_dir

        # 独立样式表，覆盖父窗口全局样式
        self.setStyleSheet("""
            QLabel { font-size: 12px; font-weight: normal; }
            QGroupBox { font-size: 13px; font-weight: bold; }
            QCheckBox { font-size: 12px; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { font-size: 12px; }
            QPushButton { font-size: 12px; }
        """)
        
        # 分析结果存储
        self.analysis_results = {}
        
        # 初始化界面
        self.init_ui()
        
        # 自动检测轨迹文件
        self.detect_trajectory_files()
    
    def init_ui(self):
        """初始化用户界面"""
        main_layout = QHBoxLayout(self)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧控制面板
        control_panel = self.create_control_panel()
        
        # 右侧结果面板
        result_panel = self.create_result_panel()
        
        splitter.addWidget(control_panel)
        splitter.addWidget(result_panel)
        splitter.setSizes([400, 800])
        
        main_layout.addWidget(splitter)
    
    def create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # 模拟类型信息
        sim_info_group = QGroupBox("模拟类型信息")
        sim_info_layout = QVBoxLayout(sim_info_group)
        sim_info_layout.setSpacing(4)

        self.sim_type_label = QLabel(f"模拟类型: {self.simulation_type}")
        self.sim_type_label.setStyleSheet("QLabel { font-weight: bold; color: #0066cc; font-size: 13px; }")
        sim_info_layout.addWidget(self.sim_type_label)

        sim_info = self.get_simulation_type_info(self.simulation_type)
        desc_label = QLabel(sim_info['description'])
        desc_label.setStyleSheet("QLabel { font-size: 11px; }")
        sim_info_layout.addWidget(desc_label)

        notes_label = QLabel(sim_info['notes'])
        notes_label.setWordWrap(True)
        notes_label.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        sim_info_layout.addWidget(notes_label)
        layout.addWidget(sim_info_group)

        # 轨迹文件选择
        file_group = QGroupBox("轨迹文件")
        file_layout = QGridLayout(file_group)
        file_layout.setSpacing(4)

        file_items = [
            ("轨迹文件(.xtc/.trr):", "trajectory_file_edit", "browse_trajectory_btn", self.browse_trajectory_file),
            ("拓扑文件(.tpr):", "topology_file_edit", "browse_topology_btn", self.browse_topology_file),
            ("索引文件(.ndx):", "index_file_edit", "browse_index_btn", self.browse_index_file),
        ]
        for row, (label, edit_attr, btn_attr, handler) in enumerate(file_items):
            lbl = QLabel(label)
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            file_layout.addWidget(lbl, row, 0)
            edit = QLineEdit()
            edit.setStyleSheet("QLineEdit { font-size: 11px; }")
            setattr(self, edit_attr, edit)
            file_layout.addWidget(edit, row, 1)
            btn = QPushButton("浏览")
            btn.setStyleSheet("QPushButton { font-size: 11px; }")
            btn.clicked.connect(handler)
            setattr(self, btn_attr, btn)
            file_layout.addWidget(btn, row, 2)

        self.auto_detect_btn = QPushButton("自动检测文件")
        self.auto_detect_btn.setStyleSheet("QPushButton { font-size: 11px; }")
        self.auto_detect_btn.clicked.connect(self.detect_trajectory_files)
        file_layout.addWidget(self.auto_detect_btn, 3, 0, 1, 3)
        layout.addWidget(file_group)

        # 分析功能选择（放在滚动区域中）
        analysis_group = QGroupBox("分析功能")
        analysis_outer_layout = QVBoxLayout(analysis_group)
        analysis_outer_layout.setContentsMargins(4, 4, 4, 4)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_widget = QWidget()
        analysis_layout = QVBoxLayout(scroll_widget)
        analysis_layout.setSpacing(6)

        # RMSD分析
        self.rmsd_check = QCheckBox("RMSD分析")
        self.rmsd_check.setChecked(True)
        self.rmsd_check.setStyleSheet("QCheckBox { font-size: 12px; font-weight: bold; }")
        analysis_layout.addWidget(self.rmsd_check)

        rmsd_layout = QGridLayout()
        rmsd_layout.setSpacing(3)
        for row, (label, attr, items) in enumerate([
            ("对齐组:", "rmsd_alignment_combo", ["System", "Protein", "Backbone", "C-alpha"]),
            ("分析组:", "rmsd_analysis_combo", ["System", "Protein", "Backbone", "C-alpha", "Ligand"]),
        ]):
            lbl = QLabel(label)
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            rmsd_layout.addWidget(lbl, row, 0)
            combo = QComboBox()
            combo.addItems(items)
            combo.setStyleSheet("QComboBox { font-size: 11px; }")
            setattr(self, attr, combo)
            rmsd_layout.addWidget(combo, row, 1)

        sim_info = self.get_simulation_type_info(self.simulation_type)
        default_align = sim_info.get('rmsd_default_align', 'System')
        idx = self.rmsd_alignment_combo.findText(default_align)
        if idx >= 0:
            self.rmsd_alignment_combo.setCurrentIndex(idx)
        analysis_layout.addLayout(rmsd_layout)

        # 二面角分析
        self.dihedral_check = QCheckBox("二面角分析")
        self.dihedral_check.setChecked(True)
        self.dihedral_check.setStyleSheet("QCheckBox { font-size: 12px; font-weight: bold; }")
        analysis_layout.addWidget(self.dihedral_check)

        dihedral_layout = QGridLayout()
        dihedral_layout.setSpacing(3)
        lbl = QLabel("预设类型:")
        lbl.setStyleSheet("QLabel { font-size: 11px; }")
        dihedral_layout.addWidget(lbl, 0, 0)
        self.dihedral_preset_combo = QComboBox()
        self.dihedral_preset_combo.addItems(["自定义", "蛋白质Phi角", "蛋白质Psi角", "蛋白质Chi1角"])
        self.dihedral_preset_combo.setStyleSheet("QComboBox { font-size: 11px; }")
        dihedral_layout.addWidget(self.dihedral_preset_combo, 0, 1)

        for i in range(1, 5):
            lbl = QLabel(f"原子{i}:")
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            dihedral_layout.addWidget(lbl, i, 0)
            edit = QLineEdit()
            edit.setStyleSheet("QLineEdit { font-size: 11px; }")
            setattr(self, f"dihedral_atom{i}_edit", edit)
            dihedral_layout.addWidget(edit, i, 1)

        preset_btn_layout = QHBoxLayout()
        self.save_dihedral_preset_btn = QPushButton("保存预设")
        self.save_dihedral_preset_btn.setStyleSheet("QPushButton { font-size: 10px; }")
        self.save_dihedral_preset_btn.clicked.connect(self.save_dihedral_preset)
        preset_btn_layout.addWidget(self.save_dihedral_preset_btn)
        self.load_dihedral_preset_btn = QPushButton("加载预设")
        self.load_dihedral_preset_btn.setStyleSheet("QPushButton { font-size: 10px; }")
        self.load_dihedral_preset_btn.clicked.connect(self.load_dihedral_presets)
        preset_btn_layout.addWidget(self.load_dihedral_preset_btn)
        dihedral_layout.addLayout(preset_btn_layout, 5, 0, 1, 2)
        self.dihedral_preset_combo.currentTextChanged.connect(self.on_dihedral_preset_changed)
        analysis_layout.addLayout(dihedral_layout)

        # RDF分析
        self.rdf_check = QCheckBox("径向分布函数(RDF)分析")
        self.rdf_check.setChecked(True)
        self.rdf_check.setStyleSheet("QCheckBox { font-size: 12px; font-weight: bold; }")
        analysis_layout.addWidget(self.rdf_check)

        rdf_layout = QGridLayout()
        rdf_layout.setSpacing(3)
        for row, (label, attr, items) in enumerate([
            ("参考组:", "rdf_ref_combo", ["System", "Protein", "Ligand", "Water", "ION"]),
            ("目标组:", "rdf_target_combo", ["Water", "ION", "Protein", "Ligand", "System"]),
        ]):
            lbl = QLabel(label)
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            rdf_layout.addWidget(lbl, row, 0)
            combo = QComboBox()
            combo.addItems(items)
            combo.setStyleSheet("QComboBox { font-size: 11px; }")
            setattr(self, attr, combo)
            rdf_layout.addWidget(combo, row, 1)

        lbl = QLabel("截断距离(nm):")
        lbl.setStyleSheet("QLabel { font-size: 11px; }")
        rdf_layout.addWidget(lbl, 2, 0)
        self.rdf_cutoff_spin = QDoubleSpinBox()
        self.rdf_cutoff_spin.setRange(0.5, 5.0)
        self.rdf_cutoff_spin.setValue(1.5)
        self.rdf_cutoff_spin.setStyleSheet("QDoubleSpinBox { font-size: 11px; }")
        rdf_layout.addWidget(self.rdf_cutoff_spin, 2, 1)
        analysis_layout.addLayout(rdf_layout)

        if self.simulation_type in ['真空模拟']:
            self.rdf_check.setEnabled(False)
            self.rdf_check.setToolTip("真空模拟不适用RDF分析")

        # MSD分析
        self.msd_check = QCheckBox("均方根位移(MSD)分析")
        self.msd_check.setChecked(True)
        self.msd_check.setStyleSheet("QCheckBox { font-size: 12px; font-weight: bold; }")
        analysis_layout.addWidget(self.msd_check)

        msd_layout = QGridLayout()
        msd_layout.setSpacing(3)
        lbl = QLabel("分析组:")
        lbl.setStyleSheet("QLabel { font-size: 11px; }")
        msd_layout.addWidget(lbl, 0, 0)
        self.msd_group_combo = QComboBox()
        self.msd_group_combo.addItems(["System", "Protein", "Ligand", "Water", "ION"])
        self.msd_group_combo.setStyleSheet("QComboBox { font-size: 11px; }")
        msd_layout.addWidget(self.msd_group_combo, 0, 1)

        sim_info = self.get_simulation_type_info(self.simulation_type)
        for row, (label, attr, lo, hi, val) in enumerate([
            ("拟合起始(%):", "msd_fit_start_spin", 0, 90, int(sim_info['msd_fit_range'][0] * 100)),
            ("拟合结束(%):", "msd_fit_end_spin", 10, 100, int(sim_info['msd_fit_range'][1] * 100)),
        ], start=1):
            lbl = QLabel(label)
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            msd_layout.addWidget(lbl, row, 0)
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(val)
            spin.setStyleSheet("QSpinBox { font-size: 11px; }")
            setattr(self, attr, spin)
            msd_layout.addWidget(spin, row, 1)
        analysis_layout.addLayout(msd_layout)

        # 氢键分析
        self.hbond_check = QCheckBox("氢键分析")
        self.hbond_check.setChecked(True)
        self.hbond_check.setStyleSheet("QCheckBox { font-size: 12px; font-weight: bold; }")
        analysis_layout.addWidget(self.hbond_check)

        hbond_layout = QGridLayout()
        hbond_layout.setSpacing(3)
        for row, (label, attr, items) in enumerate([
            ("供体组:", "hbond_donor_combo", ["Protein", "Ligand", "Water", "System"]),
            ("受体组:", "hbond_acceptor_combo", ["Protein", "Ligand", "Water", "System"]),
            ("分析模式:", "hbond_mode_combo", ["氢键数量", "占据率(Occupancy)", "寿命(Lifetime)"]),
        ]):
            lbl = QLabel(label)
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            hbond_layout.addWidget(lbl, row, 0)
            combo = QComboBox()
            combo.addItems(items)
            combo.setStyleSheet("QComboBox { font-size: 11px; }")
            setattr(self, attr, combo)
            hbond_layout.addWidget(combo, row, 1)

        for row, (label, attr, val) in enumerate([
            ("距离cutoff(nm):", "hbond_dist_cutoff_spin", 0.35),
            ("角度cutoff(°):", "hbond_ang_cutoff_spin", 30),
        ], start=3):
            lbl = QLabel(label)
            lbl.setStyleSheet("QLabel { font-size: 11px; }")
            hbond_layout.addWidget(lbl, row, 0)
            if "dist" in attr:
                spin = QDoubleSpinBox()
                spin.setRange(0.25, 0.50)
                spin.setValue(val)
                spin.setSingleStep(0.01)
                spin.setStyleSheet("QDoubleSpinBox { font-size: 11px; }")
            else:
                spin = QSpinBox()
                spin.setRange(15, 60)
                spin.setValue(int(val))
                spin.setStyleSheet("QSpinBox { font-size: 11px; }")
            setattr(self, attr, spin)
            hbond_layout.addWidget(spin, row, 1)
        analysis_layout.addLayout(hbond_layout)

        if self.simulation_type in ['真空模拟']:
            self.hbond_check.setEnabled(False)
            self.hbond_check.setToolTip("真空模拟不适用氢键分析")

        # 回旋半径分析
        self.gyrate_check = QCheckBox("回旋半径分析")
        self.gyrate_check.setChecked(True)
        self.gyrate_check.setStyleSheet("QCheckBox { font-size: 12px; font-weight: bold; }")
        analysis_layout.addWidget(self.gyrate_check)

        gyrate_layout = QGridLayout()
        gyrate_layout.setSpacing(3)
        lbl = QLabel("分析组:")
        lbl.setStyleSheet("QLabel { font-size: 11px; }")
        gyrate_layout.addWidget(lbl, 0, 0)
        self.gyrate_group_combo = QComboBox()
        self.gyrate_group_combo.addItems(["Protein", "Ligand", "System"])
        self.gyrate_group_combo.setStyleSheet("QComboBox { font-size: 11px; }")
        gyrate_layout.addWidget(self.gyrate_group_combo, 0, 1)
        analysis_layout.addLayout(gyrate_layout)

        analysis_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        analysis_outer_layout.addWidget(scroll_area)
        layout.addWidget(analysis_group, 1)

        # 控制按钮
        self.run_analysis_btn = QPushButton("运行选定分析")
        self.run_analysis_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; font-size: 12px; }")
        self.run_analysis_btn.clicked.connect(self.run_selected_analyses)
        layout.addWidget(self.run_analysis_btn)

        self.run_all_btn = QPushButton("运行所有适用分析")
        self.run_all_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 8px; font-size: 12px; }")
        self.run_all_btn.clicked.connect(self.run_all_applicable_analyses)
        layout.addWidget(self.run_all_btn)

        self.clear_btn = QPushButton("清除结果")
        self.clear_btn.setStyleSheet("QPushButton { font-size: 11px; }")
        self.clear_btn.clicked.connect(self.clear_results)
        layout.addWidget(self.clear_btn)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 状态信息
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(80)
        self.status_text.setPlaceholderText("分析状态信息将显示在这里...")
        self.status_text.setStyleSheet("QTextEdit { font-size: 11px; }")
        layout.addWidget(self.status_text)

        return panel
    
    def create_result_panel(self):
        """创建结果面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 结果标签页
        self.result_tabs = QTabWidget()
        
        # RMSD结果标签页
        self.rmsd_tab = QWidget()
        rmsd_layout = QVBoxLayout(self.rmsd_tab)
        self.rmsd_plot_widget = PlotWidget()
        rmsd_layout.addWidget(self.rmsd_plot_widget)
        self.result_tabs.addTab(self.rmsd_tab, "RMSD")
        
        # 二面角结果标签页
        self.dihedral_tab = QWidget()
        dihedral_layout = QVBoxLayout(self.dihedral_tab)
        self.dihedral_plot_widget = PlotWidget()
        dihedral_layout.addWidget(self.dihedral_plot_widget)
        self.result_tabs.addTab(self.dihedral_tab, "二面角")
        
        # RDF结果标签页
        self.rdf_tab = QWidget()
        rdf_layout = QVBoxLayout(self.rdf_tab)
        self.rdf_plot_widget = PlotWidget()
        rdf_layout.addWidget(self.rdf_plot_widget)
        self.result_tabs.addTab(self.rdf_tab, "RDF")
        
        # MSD结果标签页
        self.msd_tab = QWidget()
        msd_layout = QVBoxLayout(self.msd_tab)
        self.msd_plot_widget = PlotWidget()
        msd_layout.addWidget(self.msd_plot_widget)
        self.result_tabs.addTab(self.msd_tab, "MSD")
        
        # 氢键结果标签页
        self.hbond_tab = QWidget()
        hbond_layout = QVBoxLayout(self.hbond_tab)
        self.hbond_plot_widget = PlotWidget()
        hbond_layout.addWidget(self.hbond_plot_widget)
        self.result_tabs.addTab(self.hbond_tab, "氢键")
        
        # 回旋半径结果标签页
        self.gyrate_tab = QWidget()
        gyrate_layout = QVBoxLayout(self.gyrate_tab)
        self.gyrate_plot_widget = PlotWidget()
        gyrate_layout.addWidget(self.gyrate_plot_widget)
        self.result_tabs.addTab(self.gyrate_tab, "回旋半径")
        
        # 数据统计标签页
        self.stats_tab = QWidget()
        stats_layout = QVBoxLayout(self.stats_tab)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setFont(QFont("Courier", 10))
        stats_layout.addWidget(self.stats_text)
        self.result_tabs.addTab(self.stats_tab, "数据统计")
        
        layout.addWidget(self.result_tabs)
        
        # 保存按钮
        save_layout = QHBoxLayout()
        self.save_results_btn = QPushButton("保存所有结果")
        self.save_results_btn.clicked.connect(self.save_all_results)
        save_layout.addWidget(self.save_results_btn)
        
        self.save_plot_btn = QPushButton("保存当前图表")
        self.save_plot_btn.clicked.connect(self.save_current_plot)
        save_layout.addWidget(self.save_plot_btn)
        
        layout.addLayout(save_layout)
        
        return panel
    
    def get_simulation_type_info(self, sim_type):
        """获取模拟类型的分析信息"""
        sim_info = {
            '真空模拟': {
                'description': '真空模拟（单分子/小分子团，无周期性边界）',
                'applicable_analyses': ['RMSD', '二面角', '回旋半径'],
                'caution_analyses': ['MSD'],
                'inapplicable_analyses': ['RDF', '氢键'],
                'msd_fit_range': (0.2, 0.9),
                'rmsd_default_align': 'System',
                'notes': '真空MSD仅反映布朗运动，扩散系数无凝聚态物理意义；RDF和氢键不适用',
                'msd_warning': '真空单分子MSD仅反映布朗运动，扩散系数无凝聚态物理意义'
            },
            '气相模拟': {
                'description': '气相模拟（多个气体分子，有周期性边界）',
                'applicable_analyses': ['RMSD', '二面角', 'MSD', '氢键', '回旋半径'],
                'caution_analyses': ['RDF'],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.2, 0.8),
                'rmsd_default_align': 'System',
                'notes': 'RDF可选，截断半径不应超过盒子半长的1/2',
                'msd_warning': ''
            },
            '溶液模拟': {
                'description': '溶液模拟（蛋白质/小分子在水中）',
                'applicable_analyses': ['RMSD', '二面角', 'RDF', 'MSD', '氢键', '回旋半径'],
                'caution_analyses': [],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.2, 0.8),
                'rmsd_default_align': 'Backbone',
                'notes': '适用于所有分析功能。RDF需选择溶质-溶剂原子对；氢键需区分分子内/分子间',
                'msd_warning': ''
            },
            '晶体模拟': {
                'description': '晶体模拟（固体材料）',
                'applicable_analyses': ['RMSD', '二面角', '回旋半径'],
                'caution_analyses': ['MSD', 'RDF'],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.3, 0.7),
                'rmsd_default_align': 'System',
                'notes': '晶体MSD主要反映原子振动（~0.01 nm²量级），非扩散；RDF即对分布函数g(r)',
                'msd_warning': '晶体中原子MSD主要反映振动而非扩散，数值通常很小'
            },
            '膜模拟': {
                'description': '膜模拟（生物膜/膜蛋白）',
                'applicable_analyses': ['RMSD', '二面角', 'RDF', 'MSD', '氢键', '回旋半径'],
                'caution_analyses': [],
                'inapplicable_analyses': [],
                'msd_fit_range': (0.2, 0.8),
                'rmsd_default_align': 'Backbone',
                'notes': 'MSD需分别分析膜平面内（xy）和垂直方向（z）的扩散',
                'msd_warning': ''
            }
        }
        return sim_info.get(sim_type, sim_info['溶液模拟'])
    
    def detect_trajectory_files(self):
        """自动检测轨迹文件"""
        # 检测轨迹文件
        xtc_files = [f for f in os.listdir(self.working_dir) if f.endswith('.xtc')]
        trr_files = [f for f in os.listdir(self.working_dir) if f.endswith('.trr')]
        tpr_files = [f for f in os.listdir(self.working_dir) if f.endswith('.tpr')]
        ndx_files = [f for f in os.listdir(self.working_dir) if f.endswith('.ndx')]
        
        # 优先选择md.xtc或md.trr
        if 'md.xtc' in xtc_files:
            self.trajectory_file_edit.setText(os.path.join(self.working_dir, 'md.xtc'))
        elif 'md.trr' in trr_files:
            self.trajectory_file_edit.setText(os.path.join(self.working_dir, 'md.trr'))
        elif xtc_files:
            self.trajectory_file_edit.setText(os.path.join(self.working_dir, xtc_files[0]))
        elif trr_files:
            self.trajectory_file_edit.setText(os.path.join(self.working_dir, trr_files[0]))
        
        # 选择拓扑文件
        if 'md.tpr' in tpr_files:
            self.topology_file_edit.setText(os.path.join(self.working_dir, 'md.tpr'))
        elif tpr_files:
            self.topology_file_edit.setText(os.path.join(self.working_dir, tpr_files[0]))
        
        # 选择索引文件
        if 'index.ndx' in ndx_files:
            self.index_file_edit.setText(os.path.join(self.working_dir, 'index.ndx'))
        elif ndx_files:
            self.index_file_edit.setText(os.path.join(self.working_dir, ndx_files[0]))
        
        self.update_status(f"自动检测完成: 找到 {len(xtc_files)} 个xtc文件, {len(trr_files)} 个trr文件, {len(tpr_files)} 个tpr文件")

        # 从.ndx文件读取组名并填充下拉框
        self.load_ndx_groups()
    
    def load_ndx_groups(self):
        """从.ndx文件读取组名并更新所有下拉框"""
        ndx_file = self.index_file_edit.text().strip()
        if not ndx_file or not os.path.exists(ndx_file):
            return

        groups = []
        try:
            with open(ndx_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        grp_name = line[1:-1].strip()
                        if grp_name:
                            groups.append(grp_name)
        except Exception as e:
            self.update_status(f"读取索引文件失败: {str(e)}")
            return

        if not groups:
            return

        # 更新所有下拉框
        combos = [
            self.rmsd_alignment_combo, self.rmsd_analysis_combo,
            self.rdf_ref_combo, self.rdf_target_combo,
            self.msd_group_combo,
            self.hbond_donor_combo, self.hbond_acceptor_combo,
            self.gyrate_group_combo,
        ]
        for combo in combos:
            current = combo.currentText()
            combo.clear()
            combo.addItems(groups)
            # 恢复之前的选择（如果存在）
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        self.update_status(f"已从索引文件加载 {len(groups)} 个原子组: {', '.join(groups[:5])}{'...' if len(groups) > 5 else ''}")

    def browse_trajectory_file(self):
        """浏览轨迹文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择轨迹文件", self.working_dir,
            "轨迹文件 (*.xtc *.trr);;所有文件 (*)"
        )
        if file_path:
            self.trajectory_file_edit.setText(file_path)
    
    def browse_topology_file(self):
        """浏览拓扑文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择拓扑文件", self.working_dir,
            "拓扑文件 (*.tpr);;所有文件 (*)"
        )
        if file_path:
            self.topology_file_edit.setText(file_path)
    
    def browse_index_file(self):
        """浏览索引文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择索引文件", self.working_dir,
            "索引文件 (*.ndx);;所有文件 (*)"
        )
        if file_path:
            self.index_file_edit.setText(file_path)
    
    def update_status(self, message):
        """更新状态信息"""
        self.status_text.append(f"[{self.get_current_time()}] {message}")
        # 滚动到底部
        cursor = self.status_text.textCursor()
        cursor.movePosition(cursor.End)
        self.status_text.setTextCursor(cursor)
    
    def get_current_time(self):
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")
    
    def validate_files(self):
        """验证文件是否存在"""
        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        
        if not trajectory_file or not os.path.exists(trajectory_file):
            QMessageBox.warning(self, "警告", "轨迹文件不存在！")
            return False
        
        if not topology_file or not os.path.exists(topology_file):
            QMessageBox.warning(self, "警告", "拓扑文件不存在！")
            return False
        
        return True
    
    def run_selected_analyses(self):
        """运行选定的分析"""
        if not self.validate_files():
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        # 获取选定的分析
        analyses_to_run = []
        if self.rmsd_check.isChecked():
            analyses_to_run.append('RMSD')
        if self.dihedral_check.isChecked():
            analyses_to_run.append('二面角')
        if self.rdf_check.isChecked() and self.rdf_check.isEnabled():
            analyses_to_run.append('RDF')
        if self.msd_check.isChecked():
            analyses_to_run.append('MSD')
        if self.hbond_check.isChecked() and self.hbond_check.isEnabled():
            analyses_to_run.append('氢键')
        if self.gyrate_check.isChecked():
            analyses_to_run.append('回旋半径')
        
        if not analyses_to_run:
            QMessageBox.warning(self, "警告", "请至少选择一个分析功能！")
            self.progress_bar.setVisible(False)
            return
        
        self.update_status(f"开始运行分析: {', '.join(analyses_to_run)}")
        
        # 运行分析
        for analysis in analyses_to_run:
            try:
                if analysis == 'RMSD':
                    self.run_rmsd_analysis()
                elif analysis == '二面角':
                    self.run_dihedral_analysis()
                elif analysis == 'RDF':
                    self.run_rdf_analysis()
                elif analysis == 'MSD':
                    self.run_msd_analysis()
                elif analysis == '氢键':
                    self.run_hbond_analysis()
                elif analysis == '回旋半径':
                    self.run_gyrate_analysis()
            except Exception as e:
                self.update_status(f"{analysis}分析失败: {str(e)}")
        
        self.progress_bar.setVisible(False)
        self.update_status("所有选定分析完成")
    
    def run_all_applicable_analyses(self):
        """运行所有适用的分析"""
        if not self.validate_files():
            return
        
        sim_info = self.get_simulation_type_info(self.simulation_type)
        applicable_analyses = sim_info['applicable_analyses']
        
        self.update_status(f"运行所有适用分析: {', '.join(applicable_analyses)}")
        
        # 设置复选框状态
        self.rmsd_check.setChecked('RMSD' in applicable_analyses)
        self.dihedral_check.setChecked('二面角' in applicable_analyses)
        self.rdf_check.setChecked('RDF' in applicable_analyses and self.rdf_check.isEnabled())
        self.msd_check.setChecked('MSD' in applicable_analyses)
        self.hbond_check.setChecked('氢键' in applicable_analyses and self.hbond_check.isEnabled())
        self.gyrate_check.setChecked('回旋半径' in applicable_analyses)
        
        # 运行分析
        self.run_selected_analyses()
    
    def run_rmsd_analysis(self):
        """运行RMSD分析"""
        self.update_status("开始RMSD分析...")
        
        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        alignment_group = self.rmsd_alignment_combo.currentText()
        analysis_group = self.rmsd_analysis_combo.currentText()
        
        # 构建gmx rmsd命令
        # 需要两次选择：第一次选择对齐组，第二次选择分析组
        index_file = self.index_file_edit.text().strip()
        ndx_flag = f' -n "{index_file}"' if index_file and os.path.exists(index_file) else ''
        command = f'printf "{alignment_group}\\n{analysis_group}\\n" | gmx rms -s "{topology_file}" -f "{trajectory_file}"{ndx_flag} -o rmsd.xvg -xvg none'
        
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir, timeout=300)
            
            if result.returncode == 0:
                # 读取RMSD数据
                rmsd_data = self.read_xvg_file(os.path.join(self.working_dir, 'rmsd.xvg'))
                if rmsd_data is not None:
                    self.analysis_results['RMSD'] = rmsd_data
                    self.plot_rmsd(rmsd_data)
                    self.update_status("RMSD分析完成")
                else:
                    self.update_status("RMSD分析失败: 无法读取数据文件")
            else:
                self.update_status(f"RMSD分析失败: {result.stderr}")
        except Exception as e:
            self.update_status(f"RMSD分析失败: {str(e)}")
    
    def run_dihedral_analysis(self):
        """运行二面角分析"""
        self.update_status("开始二面角分析...")
        
        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        
        # 获取原子定义
        atom1 = self.dihedral_atom1_edit.text().strip()
        atom2 = self.dihedral_atom2_edit.text().strip()
        atom3 = self.dihedral_atom3_edit.text().strip()
        atom4 = self.dihedral_atom4_edit.text().strip()
        
        if not all([atom1, atom2, atom3, atom4]):
            QMessageBox.warning(self, "警告", "请定义四个原子！")
            return
        
        # 构建选择索引
        selection = f'{atom1} & {atom2} & {atom3} & {atom4}'
        
        # 构建gmx dihedral命令
        command = f'printf "{selection}\\n" | gmx dihedral -f "{trajectory_file}" -s "{topology_file}" -o dihedral.xvg -xvg none'
        
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir, timeout=300)
            
            if result.returncode == 0:
                # 读取二面角数据
                dihedral_data = self.read_xvg_file(os.path.join(self.working_dir, 'dihedral.xvg'))
                if dihedral_data is not None:
                    self.analysis_results['二面角'] = dihedral_data
                    self.plot_dihedral(dihedral_data)
                    self.update_status("二面角分析完成")
                else:
                    self.update_status("二面角分析失败: 无法读取数据文件")
            else:
                self.update_status(f"二面角分析失败: {result.stderr}")
        except Exception as e:
            self.update_status(f"二面角分析失败: {str(e)}")
    
    def run_rdf_analysis(self):
        """运行RDF分析"""
        self.update_status("开始RDF分析...")

        # 检查截断半径
        rdf_warnings = self.check_rdf_cutoff()
        for w in rdf_warnings:
            self.update_status(f"[警告] {w}")
        if rdf_warnings:
            reply = QMessageBox.question(
                self, "截断半径警告",
                "\n".join(rdf_warnings) + "\n\n是否继续运行RDF分析？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.update_status("RDF分析已取消")
                return

        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        ref_group = self.rdf_ref_combo.currentText()
        target_group = self.rdf_target_combo.currentText()
        cutoff = self.rdf_cutoff_spin.value()
        
        # 构建gmx rdf命令
        index_file = self.index_file_edit.text().strip()
        ndx_flag = f' -n "{index_file}"' if index_file and os.path.exists(index_file) else ''
        command = f'printf "{ref_group}\\n{target_group}\\n" | gmx rdf -s "{topology_file}" -f "{trajectory_file}"{ndx_flag} -o rdf.xvg -ref -xvg none -cn rdf_cn.xvg -cut {cutoff}'
        
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir, timeout=300)
            
            if result.returncode == 0:
                # 读取RDF数据
                rdf_data = self.read_xvg_file(os.path.join(self.working_dir, 'rdf.xvg'))
                if rdf_data is not None:
                    self.analysis_results['RDF'] = rdf_data
                    self.plot_rdf(rdf_data)
                    self.update_status("RDF分析完成")
                else:
                    self.update_status("RDF分析失败: 无法读取数据文件")
            else:
                self.update_status(f"RDF分析失败: {result.stderr}")
        except Exception as e:
            self.update_status(f"RDF分析失败: {str(e)}")
    
    def run_msd_analysis(self):
        """运行MSD分析"""
        self.update_status("开始MSD分析...")

        # 模拟类型警告
        sim_info = self.get_simulation_type_info(self.simulation_type)
        msd_warning = sim_info.get('msd_warning', '')
        if msd_warning:
            self.update_status(f"[注意] {msd_warning}")

        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        analysis_group = self.msd_group_combo.currentText()
        fit_start = self.msd_fit_start_spin.value() / 100.0
        fit_end = self.msd_fit_end_spin.value() / 100.0

        # 构建gmx msd命令
        index_file = self.index_file_edit.text().strip()
        ndx_flag = f' -n "{index_file}"' if index_file and os.path.exists(index_file) else ''
        command = f'printf "{analysis_group}\\n" | gmx msd -s "{topology_file}" -f "{trajectory_file}"{ndx_flag} -o msd.xvg -xvg none -mol'

        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir, timeout=300)

            if result.returncode == 0:
                # 读取MSD数据
                msd_data = self.read_xvg_file(os.path.join(self.working_dir, 'msd.xvg'))
                if msd_data is not None:
                    self.analysis_results['MSD'] = msd_data
                    # 计算扩散系数和block averaging误差
                    time_arr = np.array(msd_data['time'])
                    msd_arr = np.array(msd_data['values'])
                    total_points = len(time_arr)
                    start_idx = int(total_points * fit_start)
                    end_idx = int(total_points * fit_end)
                    diffusion_coeff = 0.0
                    diffusion_error = 0.0
                    if start_idx < end_idx and (end_idx - start_idx) > 2:
                        t_fit = time_arr[start_idx:end_idx]
                        m_fit = msd_arr[start_idx:end_idx]
                        coeffs = np.polyfit(t_fit, m_fit, 1)
                        diffusion_coeff = coeffs[0] / 6.0  # D = slope / 6
                        diffusion_error = self.compute_msd_block_error(m_fit) / 6.0
                    self.plot_msd(msd_data, fit_start, fit_end, diffusion_coeff, diffusion_error)
                    self.update_status(
                        f"MSD分析完成 — D = {diffusion_coeff:.4e} ± {diffusion_error:.4e} m²/s "
                        f"(拟合范围 {fit_start*100:.0f}%-{fit_end*100:.0f}%)"
                    )
                else:
                    self.update_status("MSD分析失败: 无法读取数据文件")
            else:
                self.update_status(f"MSD分析失败: {result.stderr}")
        except Exception as e:
            self.update_status(f"MSD分析失败: {str(e)}")
    
    def run_hbond_analysis(self):
        """运行氢键分析"""
        self.update_status("开始氢键分析...")

        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        donor_group = self.hbond_donor_combo.currentText()
        acceptor_group = self.hbond_acceptor_combo.currentText()
        dist_cutoff = self.hbond_dist_cutoff_spin.value()
        ang_cutoff = self.hbond_ang_cutoff_spin.value()
        mode = self.hbond_mode_combo.currentText()

        # 构建gmx hbond命令（使用自定义判据）
        command = (
            f'printf "{donor_group}\\n{acceptor_group}\\n" | gmx hbond '
            f'-s "{topology_file}" -f "{trajectory_file}" '
            f'-num hbond_num.xvg -life hbond_life.xvg '
            f'-dist hbond_dist.xvg -ang hbond_ang.xvg '
            f'-xvg none -noff -r2 {dist_cutoff} -a2 {ang_cutoff}'
        )

        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir, timeout=300)

            if result.returncode == 0:
                if "数量" in mode or "Number" in mode:
                    # 默认：氢键数量
                    hbond_data = self.read_xvg_file(os.path.join(self.working_dir, 'hbond_num.xvg'))
                    if hbond_data is not None:
                        self.analysis_results['氢键'] = hbond_data
                        self.plot_hbond(hbond_data)
                        self.update_status(f"氢键分析完成（距离cutoff={dist_cutoff} nm, 角度cutoff={ang_cutoff}°）")
                    else:
                        self.update_status("氢键分析失败: 无法读取数据文件")
                elif "占据率" in mode or "Occupancy" in mode:
                    # 占据率模式：读取life文件并计算
                    life_file = os.path.join(self.working_dir, 'hbond_life.xvg')
                    if os.path.exists(life_file):
                        life_data = self.read_xvg_file(life_file)
                        if life_data is not None:
                            self.analysis_results['氢键_占据率'] = life_data
                            self.plot_hbond_occupancy(life_data)
                            self.update_status("氢键占据率分析完成")
                        else:
                            self.update_status("氢键占据率分析失败: 无法读取数据")
                    else:
                        self.update_status("氢键占据率分析失败: 未生成life文件")
                elif "寿命" in mode or "Lifetime" in mode:
                    # 寿命模式：读取life文件
                    life_file = os.path.join(self.working_dir, 'hbond_life.xvg')
                    if os.path.exists(life_file):
                        life_data = self.read_xvg_file(life_file)
                        if life_data is not None:
                            self.analysis_results['氢键_寿命'] = life_data
                            self.plot_hbond_lifetime(life_data)
                            self.update_status("氢键寿命分析完成")
                        else:
                            self.update_status("氢键寿命分析失败: 无法读取数据")
                    else:
                        self.update_status("氢键寿命分析失败: 未生成life文件")
            else:
                self.update_status(f"氢键分析失败: {result.stderr}")
        except Exception as e:
            self.update_status(f"氢键分析失败: {str(e)}")
    
    def run_gyrate_analysis(self):
        """运行回旋半径分析"""
        self.update_status("开始回旋半径分析...")
        
        trajectory_file = self.trajectory_file_edit.text().strip()
        topology_file = self.topology_file_edit.text().strip()
        analysis_group = self.gyrate_group_combo.currentText()
        
        # 构建gmx gyrate命令
        index_file = self.index_file_edit.text().strip()
        ndx_flag = f' -n "{index_file}"' if index_file and os.path.exists(index_file) else ''
        command = f'printf "{analysis_group}\\n" | gmx gyrate -s "{topology_file}" -f "{trajectory_file}"{ndx_flag} -o gyrate.xvg -xvg none'
        
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir, timeout=300)
            
            if result.returncode == 0:
                # 读取回旋半径数据
                gyrate_data = self.read_xvg_file(os.path.join(self.working_dir, 'gyrate.xvg'))
                if gyrate_data is not None:
                    self.analysis_results['回旋半径'] = gyrate_data
                    self.plot_gyrate(gyrate_data)
                    self.update_status("回旋半径分析完成")
                else:
                    self.update_status("回旋半径分析失败: 无法读取数据文件")
            else:
                self.update_status(f"回旋半径分析失败: {result.stderr}")
        except Exception as e:
            self.update_status(f"回旋半径分析失败: {str(e)}")
    
    def read_xvg_file(self, file_path):
        """读取XVG文件"""
        try:
            time_data = []
            value_data = []
            
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or line.startswith('@'):
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            time_val = float(parts[0])
                            val = float(parts[1])
                            time_data.append(time_val)
                            value_data.append(val)
                        except ValueError:
                            continue
            
            if time_data and value_data:
                return {'time': time_data, 'values': value_data}
            return None
        except Exception as e:
            self.update_status(f"读取XVG文件失败: {str(e)}")
            return None
    
    def plot_rmsd(self, data):
        """绘制RMSD图"""
        self.rmsd_plot_widget.ax.clear()
        self.rmsd_plot_widget.ax.plot(data['time'], data['values'], 'b-', linewidth=1.5)
        self.rmsd_plot_widget.ax.set_xlabel('Time (ps)')
        self.rmsd_plot_widget.ax.set_ylabel('RMSD (nm)')
        self.rmsd_plot_widget.ax.set_title('RMSD Analysis')
        self.rmsd_plot_widget.ax.grid(True)
        self.rmsd_plot_widget.canvas.draw()
        
        # 切换到RMSD标签页
        self.result_tabs.setCurrentWidget(self.rmsd_tab)
    
    def plot_dihedral(self, data):
        """绘制二面角图"""
        self.dihedral_plot_widget.ax.clear()
        self.dihedral_plot_widget.ax.plot(data['time'], data['values'], 'r-', linewidth=1.5)
        self.dihedral_plot_widget.ax.set_xlabel('Time (ps)')
        self.dihedral_plot_widget.ax.set_ylabel('Dihedral Angle (deg)')
        self.dihedral_plot_widget.ax.set_title('Dihedral Angle Analysis')
        self.dihedral_plot_widget.ax.grid(True)
        self.dihedral_plot_widget.canvas.draw()
        
        # 切换到二面角标签页
        self.result_tabs.setCurrentWidget(self.dihedral_tab)
    
    def plot_rdf(self, data):
        """绘制RDF图"""
        self.rdf_plot_widget.ax.clear()
        self.rdf_plot_widget.ax.plot(data['time'], data['values'], 'g-', linewidth=1.5)
        self.rdf_plot_widget.ax.set_xlabel('Distance (nm)')
        self.rdf_plot_widget.ax.set_ylabel('g(r)')
        self.rdf_plot_widget.ax.set_title('Radial Distribution Function')
        self.rdf_plot_widget.ax.grid(True)
        self.rdf_plot_widget.canvas.draw()
        
        # 切换到RDF标签页
        self.result_tabs.setCurrentWidget(self.rdf_tab)
    
    def plot_msd(self, data, fit_start, fit_end, diffusion_coeff=0.0, diffusion_error=0.0):
        """绘制MSD图"""
        self.msd_plot_widget.ax.clear()
        self.msd_plot_widget.ax.plot(data['time'], data['values'], 'm-', linewidth=1.5, label='MSD')

        # 计算拟合范围
        total_points = len(data['time'])
        start_idx = int(total_points * fit_start)
        end_idx = int(total_points * fit_end)

        if start_idx < end_idx:
            # 进行线性拟合
            time_fit = np.array(data['time'][start_idx:end_idx])
            msd_fit = np.array(data['values'][start_idx:end_idx])

            # 线性拟合
            coeffs = np.polyfit(time_fit, msd_fit, 1)
            fit_line = np.polyval(coeffs, data['time'])

            if diffusion_error > 0:
                fit_label = f'Fit: D = ({diffusion_coeff:.4e} ± {diffusion_error:.4e}) m²/s'
            else:
                fit_label = f'Fit: D = {diffusion_coeff:.4e} m²/s'
            self.msd_plot_widget.ax.plot(data['time'], fit_line, 'r--', linewidth=1, label=fit_label)
            self.msd_plot_widget.ax.axvspan(data['time'][start_idx], data['time'][min(end_idx-1, total_points-1)],
                                            alpha=0.2, color='red', label='Fitting range')

        self.msd_plot_widget.ax.set_xlabel('Time (ps)')
        self.msd_plot_widget.ax.set_ylabel('MSD (nm²)')
        self.msd_plot_widget.ax.set_title('Mean Square Displacement')
        self.msd_plot_widget.ax.legend()
        self.msd_plot_widget.ax.grid(True)
        self.msd_plot_widget.canvas.draw()

        # 切换到MSD标签页
        self.result_tabs.setCurrentWidget(self.msd_tab)
    
    def plot_hbond(self, data):
        """绘制氢键图"""
        self.hbond_plot_widget.ax.clear()
        self.hbond_plot_widget.ax.plot(data['time'], data['values'], 'c-', linewidth=1.5)
        self.hbond_plot_widget.ax.set_xlabel('Time (ps)')
        self.hbond_plot_widget.ax.set_ylabel('Number of H-bonds')
        self.hbond_plot_widget.ax.set_title('Hydrogen Bond Analysis')
        self.hbond_plot_widget.ax.grid(True)
        self.hbond_plot_widget.canvas.draw()

        # 切换到氢键标签页
        self.result_tabs.setCurrentWidget(self.hbond_tab)

    def plot_hbond_occupancy(self, data):
        """绘制氢键占据率图"""
        self.hbond_plot_widget.ax.clear()
        self.hbond_plot_widget.ax.plot(data['time'], data['values'], 'c-', linewidth=1.5)
        self.hbond_plot_widget.ax.set_xlabel('Time (ps)')
        self.hbond_plot_widget.ax.set_ylabel('H-bond Occupancy')
        self.hbond_plot_widget.ax.set_title('Hydrogen Bond Occupancy')
        self.hbond_plot_widget.ax.set_ylim(-0.05, 1.05)
        self.hbond_plot_widget.ax.grid(True)
        self.hbond_plot_widget.canvas.draw()
        self.result_tabs.setCurrentWidget(self.hbond_tab)

    def plot_hbond_lifetime(self, data):
        """绘制氢键寿命图"""
        self.hbond_plot_widget.ax.clear()
        self.hbond_plot_widget.ax.plot(data['time'], data['values'], 'c-', linewidth=1.5)
        self.hbond_plot_widget.ax.set_xlabel('Time (ps)')
        self.hbond_plot_widget.ax.set_ylabel('C(t)')
        self.hbond_plot_widget.ax.set_title('Hydrogen Bond Lifetime Autocorrelation')
        self.hbond_plot_widget.ax.set_ylim(-0.05, 1.05)
        self.hbond_plot_widget.ax.grid(True)
        self.hbond_plot_widget.canvas.draw()
        self.result_tabs.setCurrentWidget(self.hbond_tab)
    
    def plot_gyrate(self, data):
        """绘制回旋半径图"""
        self.gyrate_plot_widget.ax.clear()
        self.gyrate_plot_widget.ax.plot(data['time'], data['values'], 'y-', linewidth=1.5)
        self.gyrate_plot_widget.ax.set_xlabel('Time (ps)')
        self.gyrate_plot_widget.ax.set_ylabel('Rg (nm)')
        self.gyrate_plot_widget.ax.set_title('Radius of Gyration')
        self.gyrate_plot_widget.ax.grid(True)
        self.gyrate_plot_widget.canvas.draw()
        
        # 切换到回旋半径标签页
        self.result_tabs.setCurrentWidget(self.gyrate_tab)
    
    def clear_results(self):
        """清除所有结果"""
        self.analysis_results.clear()
        
        # 清除所有图表
        self.rmsd_plot_widget.ax.clear()
        self.rmsd_plot_widget.canvas.draw()
        
        self.dihedral_plot_widget.ax.clear()
        self.dihedral_plot_widget.canvas.draw()
        
        self.rdf_plot_widget.ax.clear()
        self.rdf_plot_widget.canvas.draw()
        
        self.msd_plot_widget.ax.clear()
        self.msd_plot_widget.canvas.draw()
        
        self.hbond_plot_widget.ax.clear()
        self.hbond_plot_widget.canvas.draw()
        
        self.gyrate_plot_widget.ax.clear()
        self.gyrate_plot_widget.canvas.draw()
        
        self.stats_text.clear()
        
        self.update_status("已清除所有分析结果")
    
    def save_all_results(self):
        """保存所有结果"""
        if not self.analysis_results:
            QMessageBox.warning(self, "警告", "没有可保存的结果！")
            return
        
        # 选择保存目录
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", self.working_dir)
        if not save_dir:
            return
        
        try:
            # 保存每个分析的结果
            for analysis_name, data in self.analysis_results.items():
                filename = os.path.join(save_dir, f'{analysis_name}_analysis.xvg')
                with open(filename, 'w') as f:
                    f.write(f'# {analysis_name} Analysis\n')
                    f.write('# Time\tValue\n')
                    for t, v in zip(data['time'], data['values']):
                        f.write(f'{t:.4f}\t{v:.6f}\n')
            
            # 保存统计信息
            stats_file = os.path.join(save_dir, 'analysis_statistics.txt')
            with open(stats_file, 'w') as f:
                f.write("轨迹分析统计信息\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"模拟类型: {self.simulation_type}\n")
                f.write(f"轨迹文件: {self.trajectory_file_edit.text()}\n")
                f.write(f"拓扑文件: {self.topology_file_edit.text()}\n\n")
                
                for analysis_name, data in self.analysis_results.items():
                    values = data['values']
                    f.write(f"{analysis_name}分析:\n")
                    f.write(f"  数据点数: {len(values)}\n")
                    f.write(f"  平均值: {np.mean(values):.6f}\n")
                    f.write(f"  标准差: {np.std(values):.6f}\n")
                    f.write(f"  最小值: {np.min(values):.6f}\n")
                    f.write(f"  最大值: {np.max(values):.6f}\n\n")
            
            self.update_status(f"所有结果已保存到: {save_dir}")
            QMessageBox.information(self, "成功", f"所有结果已保存到:\n{save_dir}")
            
        except Exception as e:
            self.update_status(f"保存结果失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"保存结果失败:\n{str(e)}")
    
    def save_current_plot(self):
        """保存当前图表"""
        # 获取当前活动的标签页
        current_tab = self.result_tabs.currentWidget()
        
        # 根据当前标签页获取对应的plot_widget
        if current_tab == self.rmsd_tab:
            plot_widget = self.rmsd_plot_widget
            filename_suffix = "RMSD"
        elif current_tab == self.dihedral_tab:
            plot_widget = self.dihedral_plot_widget
            filename_suffix = "dihedral"
        elif current_tab == self.rdf_tab:
            plot_widget = self.rdf_plot_widget
            filename_suffix = "RDF"
        elif current_tab == self.msd_tab:
            plot_widget = self.msd_plot_widget
            filename_suffix = "MSD"
        elif current_tab == self.hbond_tab:
            plot_widget = self.hbond_plot_widget
            filename_suffix = "hbond"
        elif current_tab == self.gyrate_tab:
            plot_widget = self.gyrate_plot_widget
            filename_suffix = "gyrate"
        else:
            QMessageBox.warning(self, "警告", "当前没有可保存的图表！")
            return
        
        # 选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存图表", "",
            "PNG文件 (*.png);;PDF文件 (*.pdf);;SVG文件 (*.svg);;所有文件 (*)"
        )
        
        if file_path:
            try:
                plot_widget.figure.savefig(file_path, dpi=300, bbox_inches='tight')
                self.update_status(f"图表已保存到: {file_path}")
                QMessageBox.information(self, "成功", f"图表已保存到:\n{file_path}")
            except Exception as e:
                self.update_status(f"保存图表失败: {str(e)}")
                QMessageBox.critical(self, "错误", f"保存图表失败:\n{str(e)}")

    # ========== 二面角预设管理 ==========

    def save_dihedral_preset(self):
        """保存当前二面角原子定义为自定义预设"""
        atom1 = self.dihedral_atom1_edit.text().strip()
        atom2 = self.dihedral_atom2_edit.text().strip()
        atom3 = self.dihedral_atom3_edit.text().strip()
        atom4 = self.dihedral_atom4_edit.text().strip()

        if not all([atom1, atom2, atom3, atom4]):
            QMessageBox.warning(self, "警告", "请先填写四个原子的名称！")
            return

        name, ok = QInputDialog.getText(self, "保存预设", "输入预设名称:")
        if not ok or not name.strip():
            return

        preset_file = os.path.join(self.working_dir, 'dihedral_presets.json')
        presets = {}
        if os.path.exists(preset_file):
            try:
                with open(preset_file, 'r') as f:
                    presets = json.load(f)
            except Exception:
                presets = {}

        presets[name.strip()] = [atom1, atom2, atom3, atom4]
        try:
            with open(preset_file, 'w') as f:
                json.dump(presets, f, indent=2, ensure_ascii=False)
            self.update_status(f"预设 '{name.strip()}' 已保存到 {preset_file}")
            self.load_dihedral_presets()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存预设失败:\n{str(e)}")

    def load_dihedral_presets(self):
        """加载自定义二面角预设并更新下拉框"""
        preset_file = os.path.join(self.working_dir, 'dihedral_presets.json')
        if not os.path.exists(preset_file):
            return

        try:
            with open(preset_file, 'r') as f:
                presets = json.load(f)
        except Exception:
            return

        # 移除旧的自定义预设项
        for i in range(self.dihedral_preset_combo.count() - 1, -1, -1):
            text = self.dihedral_preset_combo.itemText(i)
            if text.startswith("[自定义]"):
                self.dihedral_preset_combo.removeItem(i)

        # 添加新预设
        for name in presets:
            self.dihedral_preset_combo.addItem(f"[自定义] {name}")

    def on_dihedral_preset_changed(self, text):
        """二面角预设选择变化时填充原子"""
        if not text or text == "自定义":
            return

        # 蛋白质预设的原子映射（需根据具体残基调整，这里给出模板）
        protein_presets = {
            "蛋白质Phi角": ("C_N-1", "N", "CA", "C"),
            "蛋白质Psi角": ("N", "CA", "C", "N_N+1"),
            "蛋白质Chi1角": ("N", "CA", "CB", "CG"),
        }

        if text in protein_presets:
            atoms = protein_presets[text]
            self.dihedral_atom1_edit.setText(atoms[0])
            self.dihedral_atom2_edit.setText(atoms[1])
            self.dihedral_atom3_edit.setText(atoms[2])
            self.dihedral_atom4_edit.setText(atoms[3])
            self.update_status(f"已加载预设 '{text}'（请根据实际残基调整原子名）")
        elif text.startswith("[自定义] "):
            # 加载自定义预设
            preset_name = text.replace("[自定义] ", "")
            preset_file = os.path.join(self.working_dir, 'dihedral_presets.json')
            if os.path.exists(preset_file):
                try:
                    with open(preset_file, 'r') as f:
                        presets = json.load(f)
                    if preset_name in presets:
                        atoms = presets[preset_name]
                        self.dihedral_atom1_edit.setText(atoms[0])
                        self.dihedral_atom2_edit.setText(atoms[1])
                        self.dihedral_atom3_edit.setText(atoms[2])
                        self.dihedral_atom4_edit.setText(atoms[3])
                except Exception:
                    pass

    # ========== MSD block averaging 误差 ==========

    def compute_msd_block_error(self, msd_values, n_blocks=5):
        """用 block averaging 计算MSD扩散系数的误差估计"""
        if len(msd_values) < n_blocks * 2:
            return 0.0
        block_size = len(msd_values) // n_blocks
        block_diffusions = []
        for i in range(n_blocks):
            start = i * block_size
            end = start + block_size
            block = msd_values[start:end]
            if len(block) < 2:
                continue
            x = np.arange(len(block))
            coeffs = np.polyfit(x, block, 1)
            block_diffusions.append(coeffs[0])
        if len(block_diffusions) < 2:
            return 0.0
        return np.std(block_diffusions) / np.sqrt(len(block_diffusions))

    # ========== RDF 截断半径警告 ==========

    def check_rdf_cutoff(self):
        """检查RDF截断半径是否合理，返回警告信息"""
        cutoff = self.rdf_cutoff_spin.value()
        topology_file = self.topology_file_edit.text().strip()
        warnings = []
        if cutoff > 1.5:
            warnings.append(f"截断距离 {cutoff} nm 较大，可能增加计算时间")
        # 尝试从轨迹文件推断盒子大小
        trajectory_file = self.trajectory_file_edit.text().strip()
        if trajectory_file and os.path.exists(trajectory_file):
            try:
                result = subprocess.run(
                    f'gmx dump -f "{trajectory_file}" -om box.xvg 2>/dev/null | head -20',
                    shell=True, capture_output=True, text=True, cwd=self.working_dir
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'box' in line.lower() or len(line.split()) >= 3:
                            parts = line.split()
                            if len(parts) >= 3:
                                try:
                                    box_x = float(parts[0])
                                    half_box = box_x / 2.0
                                    if cutoff > half_box:
                                        warnings.append(
                                            f"截断距离 {cutoff} nm 超过盒子半长 {half_box:.2f} nm，"
                                            f"RDF结果可能不可靠！建议截断距离 ≤ {half_box:.2f} nm"
                                        )
                                    break
                                except ValueError:
                                    continue
            except Exception:
                pass
        return warnings

class CommandExecutor(QThread):
    """后台命令执行线程类，用于异步执行GROMACS命令"""
    output_ready = pyqtSignal(str)        # 实时输出信号
    error_ready = pyqtSignal(str)         # 错误输出信号
    finished_signal = pyqtSignal(int, str) # 完成信号(返回码, 消息)
    progress_update = pyqtSignal(str)     # 进度更新信号
    
    def __init__(self, commands, working_dir=None):
        super().__init__()
        self.commands = commands
        self.working_dir = working_dir
        self._is_running = False
        self.process = None
        
    def run(self):
        """执行命令"""
        self._is_running = True
        try:
            for i, command in enumerate(self.commands):
                if not self._is_running:
                    self.finished_signal.emit(-1, "命令执行被用户中断")
                    return
                    
                # 添加详细输出参数
                if "gmx mdrun" in command and "-v" not in command:
                    command += " -v"
                
                self.progress_update.emit(f"正在执行 ({i+1}/{len(self.commands)}): {command}")
                self.output_ready.emit(f"=== 开始执行: {command} ===")
                
                # 使用Popen而不是run，以便实时获取输出
                self.process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # 合并stderr到stdout
                    stdin=subprocess.PIPE,
                    text=True,
                    cwd=self.working_dir,
                    bufsize=0,  # 无缓冲
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='replace'
                )
                
                # 实时读取输出
                while True:
                    output = self.process.stdout.readline() if self.process and self.process.stdout else ''
                    if output == '' and self.process.poll() is not None:
                        break
                    if output:
                        # 检查输出内容类型并发送适当的信号
                        line = output.strip()
                        if line.startswith("==="):  # 系统提示信息
                            self.output_ready.emit(line)
                        elif "GROMACS" in line and ("gmx" in line or ":-)" in line):  # GROMACS标题行
                            self.output_ready.emit(line)
                        elif line.startswith("Setting the LD random seed"):  # 特殊信息行
                            self.output_ready.emit(line)
                        elif line.startswith("Generated") or "parameter combinations" in line:  # 参数生成信息
                            self.output_ready.emit(line)
                        elif line.startswith("Executable:"):  # 可执行文件信息
                            self.output_ready.emit(line)
                        elif line.startswith("work"):  # 工作目录信息
                            self.error_ready.emit(line)
                        else:
                            self.output_ready.emit(line)
                    if not self._is_running:
                        break
                
                # 等待进程结束
                return_code = self.process.wait()
                
                # 检查是否被中断
                if not self._is_running:
                    self.process.terminate()
                    self.process.wait()
                    self.finished_signal.emit(-1, "命令执行被用户中断")
                    return
                
                # 获取最终结果
                self.output_ready.emit(f"=== 命令执行完成: {command} ===")
                if return_code != 0:
                    self.finished_signal.emit(return_code, f"命令执行失败，返回码: {return_code}")
                    return
            self.finished_signal.emit(0, "所有命令执行成功")
            
        except Exception as e: # 捕获所有未预期的异常
            self.error_ready.emit(f"执行错误: {str(e)}")
            self.finished_signal.emit(-1, f"执行异常: {str(e)}")
        finally:
            self._is_running = False
            # 确保管道被关闭
            if self.process:
                if self.process.stdout:
                    try:
                        self.process.stdout.close()
                    except:
                        pass
                if self.process.stderr:
                    try:
                        self.process.stderr.close()
                    except:
                        pass
            self.process = None
# ... existing code ...



    def stop(self):
        """停止命令执行"""
        self._is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

class GromacsEditconfCommandGenerator:
    """gmx editconf命令生成器类"""
    
    def __init__(self):
        # 盒子类型映射表
        self.box_type_mapping = {
            "cubic": "cubic",           # 立方体
            "triclinic": "triclinic",   # 三斜晶系  
            "dodecahedron": "dodecahedron", # 十二面体
            "octahedron": "octahedron"      # 八面体
        }
    
    def generate_command(self, params):
        """根据参数字典生成完整的gmx editconf命令"""
        try:
            # 参数验证
            validation_error = self._validate_parameters(params)
            if validation_error:
                return None, validation_error
            
            # 构建命令组件
            cmd_parts = ["gmx", "editconf"]
            
            # 添加文件参数
            input_file = params.get("input_file", "").strip()
            if input_file:
                cmd_parts.extend(["-f", f'"{input_file}"'])
            
            output_file = params.get("output_file", "").strip()
            if output_file:
                cmd_parts.extend(["-o", f'"{output_file}"'])
            else:
                # 如果没有指定输出文件，使用默认命名
                base_name = os.path.splitext(input_file)[0]
                default_output = f"{base_name}_centered.gro"
                cmd_parts.extend(["-o", f'"{default_output}"'])
            
            # 添加盒子参数
            box_type = params.get("box_type", "cubic")
            if box_type in self.box_type_mapping:
                cmd_parts.extend(["-bt", self.box_type_mapping[box_type]])
            
            box_size = params.get("box_size", 10.0)
            cmd_parts.extend(["-box", f"{box_size:.3f}", f"{box_size:.3f}", f"{box_size:.3f}"])
            
            # 添加密度参数
            density = params.get("density", 1000.0)
            if abs(density - 1000.0) > 0.001:  # 与默认值不同时才添加
                cmd_parts.extend(["-density", f"{density:.3f}"])
            
            # 添加居中参数
            if params.get("center", True):
                cmd_parts.append("-c")
            
            # 添加平移参数
            translate = params.get("translate", [0.0, 0.0, 0.0])
            if any(abs(t) > 0.001 for t in translate):
                cmd_parts.extend([
                    "-translate",
                    f"{translate[0]:.3f}",
                    f"{translate[1]:.3f}",
                    f"{translate[2]:.3f}"
                ])
            
            # 添加旋转参数
            if params.get("rotate", False):
                rotation = params.get("rotation", [0.0, 0.0, 0.0])
                cmd_parts.extend([
                    "-rotate",
                    f"{rotation[0]:.1f}",
                    f"{rotation[1]:.1f}",
                    f"{rotation[2]:.1f}"
                ])
            
            # 添加缩放参数
            scale = params.get("scale", 1.0)
            if abs(scale - 1.0) > 0.001:  # 与默认值不同时才添加
                cmd_parts.extend(["-scale", f"{scale:.3f}"])
            
            # 添加保持链标识符参数
            if params.get("keep_chain", False):
                cmd_parts.append("-pbc")
            
            # 添加保持残基编号参数
            if params.get("keep_resnr", False):
                cmd_parts.append("-resnr")
            
            # 组装最终命令
            final_command = " ".join(cmd_parts)
            
            return final_command, None
            
        except Exception as e:
            return None, f"生成命令时发生错误: {str(e)}"
    
    def _validate_parameters(self, params):
        """验证参数有效性"""
        # 检查输入文件
        input_file = params.get("input_file", "").strip()
        if not input_file:
            return "请选择输入文件"
        
        if not os.path.exists(input_file):
            return f"输入文件不存在: {input_file}"
        
        # 检查文件扩展名
        if not any(input_file.lower().endswith(ext) for ext in [".gro", ".pdb"]):
            return "输入文件必须是.gro或.pdb格式"
        
        return None

class GMXCommandGenerator:
    """GROMACS命令生成器类"""
    def __init__(self, ui_reference):
        self.ui = ui_reference

    def get_user_files(self):
        """获取用户在UI中选择的实际文件路径"""
        return {
            'pdb': self.ui.pdb_file_edit.text().strip(),
            'gro': self.ui.gro_file_edit.text().strip(),
            'top': self.ui.top_file_edit.text().strip(),
            'itp': self.ui.itp_file_edit.text().strip(), # ITP 文件路径，可能为空字符串
            'working_dir': self.ui.working_dir_edit.text().strip()
        }

    def validate_files(self, step_type):
        """验证文件存在性，根据模拟类型调整验证逻辑"""
        user_files = self.get_user_files()
        sim_type = self.ui.sim_type_combo.currentText()
        missing_files = []
        
        if step_type == 'minimization':
            # 检查结构文件
            if not (user_files['gro'] or user_files['pdb']):
                missing_files.append("结构文件(.gro或.pdb)")
            else:
                gro_exists = user_files['gro'] and os.path.exists(user_files['gro'])
                pdb_exists = user_files['pdb'] and os.path.exists(user_files['pdb'])
                if not (gro_exists or pdb_exists):
                    missing_files.append("结构文件(所选文件不存在)")
            
            # 检查拓扑文件
            if not user_files['top']:
                missing_files.append("拓扑文件(.top)")
            elif not os.path.exists(user_files['top']):
                missing_files.append("拓扑文件(所选文件不存在)")
            
            # 根据模拟类型进行特殊检查
            if sim_type == '溶液模拟':
                # 溶液模拟需要检查溶剂化步骤是否完成
                working_dir = user_files['working_dir'] or os.getcwd()
                solvated_file = os.path.join(working_dir, "solvated.gro")
                ionized_file = os.path.join(working_dir, "ionized.gro")
                if not (os.path.exists(solvated_file) or os.path.exists(ionized_file)):
                    missing_files.append("溶剂化文件(需要先完成editconf/solvate/genion步骤)")
            
            elif sim_type == '膜模拟':
                # 膜模拟需要检查膜体系文件
                if user_files['gro']:
                    # 检查文件名是否包含膜相关关键词
                    filename = os.path.basename(user_files['gro']).lower()
                    membrane_keywords = ['membrane', 'lipid', 'bilayer', 'popc', 'dppc', 'dopc']
                    if not any(keyword in filename for keyword in membrane_keywords):
                        missing_files.append("膜体系结构文件(建议使用预构建的膜结构)")
            
            elif sim_type == '自由能计算':
                # 自由能计算需要检查λ参数或umbrella配置
                if user_files['top']:
                    try:
                        with open(user_files['top'], 'r', encoding='utf-8') as f:
                            top_content = f.read()
                        if 'lambda' not in top_content.lower() and 'free' not in top_content.lower():
                            missing_files.append("自由能拓扑文件(需包含λ参数或自由能定义)")
                    except:
                        pass  # 文件读取失败，不强制检查
            
            elif sim_type == '晶体模拟':
                # 晶体模拟检查结构文件是否为晶体结构
                if user_files['gro']:
                    filename = os.path.basename(user_files['gro']).lower()
                    crystal_keywords = ['crystal', 'unit', 'cell', 'lattice', 'solid']
                    if not any(keyword in filename for keyword in crystal_keywords):
                        # 这只是一个提示，不算作错误
                        pass
            
            elif sim_type == '气相模拟':
                # 气相模拟检查盒子尺寸等
                if user_files['gro']:
                    try:
                        # 简单检查：气相模拟通常需要较大的盒子
                        pass  # 具体检查可以根据需要实现
                    except:
                        pass
        
        else:
            # 检查上一步的输出文件
            prev_step_map = self._get_prev_step_mapping(sim_type)
            prev_step = prev_step_map.get(step_type)
            
            if prev_step:
                prev_gro = f"{prev_step}.gro"
                working_dir = user_files['working_dir'] or os.getcwd()
                if not os.path.exists(os.path.join(working_dir, prev_gro)):
                    missing_files.append(f"{prev_gro} (需要先完成{prev_step}步骤)")
            
            # 拓扑文件在后续步骤中也应存在
            if not user_files['top']:
                missing_files.append("拓扑文件(.top)")
            elif not os.path.exists(user_files['top']):
                missing_files.append("拓扑文件(所选文件不存在)")
        
        return missing_files
    
    def _get_prev_step_mapping(self, sim_type):
        """获取模拟类型对应的步骤映射关系"""
        if sim_type == '真空模拟':
            # 真空模拟直接从em跳到md
            return {
                'production': 'em'
            }
        elif sim_type == '气相模拟':
            # 气相模拟运行全流程但生产运行从nvt跳过
            return {
                'nvt': 'em',
                'npt': 'nvt',
                'production': 'nvt'  # 气相模拟生产运行直接从nvt跳过到md
            }
        else:
            # 其他模拟类型的标准流程
            return {
                'nvt': 'em',
                'npt': 'nvt',
                'production': 'npt'
            }

    # ... existing code ...
    def generate_grompp_command(self, step_type):
        """根据步骤类型和用户文件生成grompp命令，支持不同模拟类型"""
        user_files = self.get_user_files()
        sim_type = self.ui.sim_type_combo.currentText()
        
        # 检查真空模拟是否跳过npt步骤
        if sim_type == '真空模拟' and step_type == 'npt':
            raise ValueError("真空模拟不需要NPT步骤")
        
        # 确定输入结构文件
        if step_type == 'minimization':
            if user_files['gro'] and os.path.exists(user_files['gro']):
                input_structure = os.path.basename(user_files['gro'])
            elif user_files['pdb'] and os.path.exists(user_files['pdb']):
                input_structure = os.path.basename(user_files['pdb'])
            else:
                raise FileNotFoundError("未找到有效的结构文件")
        else:
            # 后续步骤使用前一步的输出，根据模拟类型调整
            input_structure = self._get_prev_step_output(step_type, sim_type)

        # 确定拓扑文件
        topology_file = os.path.basename(user_files['top']) if user_files['top'] else 'topol.top'

        # 构建基础命令
        step_names = {'minimization': 'em', 'nvt': 'nvt', 'npt': 'npt', 'production': 'md'}
        step_name = step_names[step_type]
        command = f"gmx grompp -f {step_name}.mdp -c {input_structure} -p {topology_file} -o {step_name}.tpr"

        # 添加特定步骤的参数
        if step_type == 'nvt':
            command += f" -r {input_structure}"  # 位置约束参考
        elif step_type in ['npt', 'production']:
            prev_cpt = self._get_prev_checkpoint_file(step_type, sim_type)
            if prev_cpt:
                command += f" -t {prev_cpt}"
        return command
    
    def _get_prev_step_output(self, step_type, sim_type):
        """根据模拟类型获取前一步骤的输出文件"""
        if step_type == 'nvt':
            return 'em.gro'
        elif step_type == 'npt':
            return 'nvt.gro'
        elif step_type == 'production':
            # 真空模拟跳过NVT和NPT，直接从EM继续
            if sim_type == '真空模拟':
                return 'em.gro'
            # 气相模拟跳过NPT，从NVT继续
            elif sim_type == '气相模拟':
                return 'nvt.gro'
            else:
                return 'npt.gro'
        else:
            return 'em.gro'
    
    def _get_prev_checkpoint_file(self, step_type, sim_type):
        """根据模拟类型获取前一步骤的检查点文件"""
        if step_type == 'npt':
            return 'nvt.cpt'
        elif step_type == 'production':
            # 真空模拟跳过NVT和NPT，无检查点
            if sim_type == '真空模拟':
                return None
            # 气相模拟跳过NPT，使用NVT检查点
            elif sim_type == '气相模拟':
                return 'nvt.cpt'
            else:
                return 'npt.cpt'
        else:
            return None
    ##############################
    def _check_tpr_file_exists(self, step_type):
        """检查指定步骤的 tpr 文件是否存在"""
        step_names = {'minimization': 'em', 'nvt': 'nvt', 'npt': 'npt', 'production': 'md'}
        step_name = step_names.get(step_type, step_type)  # Fixed the bug here
        working_dir = self.ui.working_dir_edit.text() or os.getcwd()
        tpr_file = os.path.join(working_dir, f"{step_name}.tpr")
        return os.path.exists(tpr_file)



# ... existing code ...
    def generate_mdrun_command(self, step_type):
        """生成mdrun命令，根据模拟类型添加特殊参数"""
        step_names = {'minimization': 'em', 'nvt': 'nvt', 'npt': 'npt', 'production': 'md'}
        step_name = step_names[step_type]
        sim_type = self.ui.sim_type_combo.currentText()
        
        # 检查真空模拟是否跳过npt步骤
        if sim_type == '真空模拟' and step_type == 'npt':
            # 真空模拟直接跳过npt步骤
            return None
        
        # 检查是否存在检查点文件或日志文件
        working_dir = self.ui.working_dir_edit.text() or os.getcwd()
        cpt_file = os.path.join(working_dir, f"{step_name}.cpt")
        log_file = os.path.join(working_dir, f"{step_name}.log")
        tpr_file = os.path.join(working_dir, f"{step_name}.tpr")
        
        # 如果存在检查点或日志文件，先询问用户操作方式
        if os.path.exists(cpt_file) or os.path.exists(log_file):
            # 弹出选择对话框让用户选择操作方式
            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("检测到已存在的模拟文件")
            msg_box.setText(f"检测到 {step_name} 阶段已存在模拟文件:\n"
                           f"{'检查点文件: ' + os.path.basename(cpt_file) if os.path.exists(cpt_file) else ''}\n"
                           f"{'日志文件: ' + os.path.basename(log_file) if os.path.exists(log_file) else ''}\n\n"
                           "请选择操作方式:")
            msg_box.setIcon(QMessageBox.Question)
            
            restart_btn = msg_box.addButton("重新开始", QMessageBox.AcceptRole)
            resume_btn = msg_box.addButton("继续运行", QMessageBox.AcceptRole)
            cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
            
            msg_box.exec_()
            
            if msg_box.clickedButton() == cancel_btn:
                return None  # 用户取消操作
                
            elif msg_box.clickedButton() == resume_btn:
                # 续跑模式 - 直接使用现有检查点文件
                mdrun_cmd = f"gmx mdrun -deffnm {step_name}"

                # 如果存在检查点文件，添加检查点参数
                if os.path.exists(cpt_file):
                    mdrun_cmd += f" -cpi {step_name}.cpt"

                # 追加输出
                if hasattr(self.ui, 'append_checkbox'):
                    if self.ui.append_checkbox.isChecked():
                        mdrun_cmd += " -append"
                    else:
                        mdrun_cmd += " -noappend"

                # 追加通用运行参数
                mdrun_cmd = self._append_mdrun_params(mdrun_cmd, step_type, sim_type)

                # 返回元组标识这是续跑模式
                return ("RESUME_MODE", mdrun_cmd)
                
            # 如果用户选择重新开始，继续执行下面的代码
        
        # 基础mdrun命令 (重新开始模式) - 只有在没有检查点文件或用户选择重新开始时才需要生成.tpr文件
        # 如果当前步骤不是能量最小化且存在.tpr文件，则不需要重新生成grompp命令
        if step_type != 'minimization' and os.path.exists(tpr_file):
            command = f"gmx mdrun -s {step_name}.tpr -deffnm {step_name}"
        else:
            # 需要先生成grompp命令
            try:
                grompp_cmd = self.generate_grompp_command(step_type)
                command = f"{grompp_cmd}\ngmx mdrun -s {step_name}.tpr -deffnm {step_name}"
            except Exception as e:
                QMessageBox.warning(self.ui, "错误", f"生成grompp命令失败: {str(e)}")
                return None

        # 追加通用运行参数（GPU、线程、输出等）
        command = self._append_mdrun_params(command, step_type, sim_type)

        return command

    def _append_mdrun_params(self, mdrun_cmd, step_type, sim_type):
        """为mdrun命令追加通用运行参数（MPI、GPU、线程、输出等）。
        支持单行命令和多行命令（grompp+mdrun），多行时只追加到mdrun行。"""
        # 构建参数字符串
        params_parts = []

        # 获取计算模式
        compute_mode_idx = 0
        if hasattr(self.ui, 'compute_mode_combo'):
            compute_mode_idx = self.ui.compute_mode_combo.currentIndex()
        is_cpu_mode = (compute_mode_idx == 2)

        # GPU选项
        if not is_cpu_mode and hasattr(self.ui, 'gpu_edit') and self.ui.gpu_edit.text().strip():
            gpu_id = self.ui.gpu_edit.text().strip()
            params_parts.append(f"-gpu_id {gpu_id}")
            if hasattr(self.ui, 'nb_combo') and self.ui.nb_combo.currentIndex() == 0:
                params_parts.append("-nb gpu")

        # 最大运行时间
        if hasattr(self.ui, 'maxh_spinbox') and self.ui.maxh_spinbox.value() > 0:
            params_parts.append(f"-maxh {self.ui.maxh_spinbox.value()}")

        # 总线程数
        if hasattr(self.ui, 'nt_spinbox') and self.ui.nt_spinbox.value() > 0:
            params_parts.append(f"-nt {self.ui.nt_spinbox.value()}")

        # 线程绑定
        if hasattr(self.ui, 'pin_combo'):
            pin_val = self.ui.pin_combo.currentText()
            if pin_val != "自动":
                params_parts.append(f"-pin {pin_val}")

        # 绑定偏移
        if hasattr(self.ui, 'pinoffset_spinbox') and self.ui.pinoffset_spinbox.value() > 0:
            params_parts.append(f"-pinoffset {self.ui.pinoffset_spinbox.value()}")

        # 动态负载均衡
        if hasattr(self.ui, 'dlb_combo'):
            dlb_val = self.ui.dlb_combo.currentText()
            if dlb_val != "自动":
                params_parts.append(f"-dlb {dlb_val}")

        # 非键计算
        if hasattr(self.ui, 'nb_combo'):
            nb_val = self.ui.nb_combo.currentText()
            if nb_val != "自动":
                params_parts.append(f"-nb {nb_val}")

        # PME计算
        if hasattr(self.ui, 'pme_combo'):
            pme_val = self.ui.pme_combo.currentText()
            if pme_val != "自动":
                params_parts.append(f"-pme {pme_val}")

        # 输出间隔
        if hasattr(self.ui, 'stepout_spinbox') and self.ui.stepout_spinbox.value() != 1000:
            params_parts.append(f"-stepout {self.ui.stepout_spinbox.value()}")

        # 检查点间隔
        if hasattr(self.ui, 'cpt_spinbox') and self.ui.cpt_spinbox.value() > 0:
            params_parts.append(f"-cpt {self.ui.cpt_spinbox.value()}")

        # OpenMP线程数（智能避免OMP_NUM_THREADS冲突）
        if hasattr(self.ui, 'ntomp_spinbox') and self.ui.ntomp_spinbox.value() > 0:
            ntomp_val = self.ui.ntomp_spinbox.value()
            omp_env = os.environ.get('OMP_NUM_THREADS')
            should_add_ntomp = True
            if omp_env:
                try:
                    if int(omp_env) != ntomp_val:
                        should_add_ntomp = False
                except ValueError:
                    pass
            if should_add_ntomp:
                params_parts.append(f"-ntomp {ntomp_val}")

        # 模拟类型特殊参数
        specific_params = self._get_mdrun_specific_params(step_type, sim_type)
        if specific_params:
            params_parts.append(specific_params.strip())

        params_str = " " + " ".join(params_parts) if params_parts else ""

        # 多行命令：只追加到 gmx mdrun 那一行
        if "\n" in mdrun_cmd:
            lines = mdrun_cmd.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('gmx mdrun'):
                    lines[i] = line + params_str
            mdrun_cmd = '\n'.join(lines)
        else:
            mdrun_cmd += params_str

        # MPI前缀（最后添加，包裹整个命令）
        if hasattr(self.ui, 'mpi_checkbox') and self.ui.mpi_checkbox.isChecked():
            if hasattr(self.ui, 'mpi_np_spinbox'):
                mpi_nprocs = self.ui.mpi_np_spinbox.value()
                mdrun_cmd = f"mpirun -np {mpi_nprocs} {mdrun_cmd}"

        return mdrun_cmd

    def _get_mdrun_specific_params(self, step_type, sim_type):
        """根据模拟类型和步骤类型返回特殊的mdrun参数"""
        specific_params = ""
        
        # 膜模拟的特殊参数
        if sim_type == '膜模拟':
            if step_type in ['npt', 'production']:
                # 膜模拟使用半各向同性压力耦合，可能需要特殊的输出参数
                # 注意：半各向同性参数主要在MDP文件中设置，但这里可以添加相关输出
                pass
        
        # 自由能计算的特殊参数
        elif sim_type == '自由能计算':
            if step_type == 'production':
                # 自由能计算可能需要特殊的输出或多窗口支持
                # 注意：具体参数将在MDP文件中设置
                pass
        
        # 真空模拟的特殊参数
        elif sim_type == '真空模拟':
            # 真空模拟可能需要特殊的输出设置
            pass
        
        return specific_params

    def generate_single_step_commands(self, step_type):
        """生成单步命令（统一入口）"""
        # 1. 调用 generate_mdrun_command(step_type)
        result = self.generate_mdrun_command(step_type)
        
        # 2. 判断返回值类型
        if result is None:
            return None  # 用户取消
        
        # 3. 如果是续跑模式（返回元组且第一个元素是"RESUME_MODE"）
        if isinstance(result, tuple) and result[0] == "RESUME_MODE":
            return [result[1]]  # 只返回mdrun命令，不调用generate_grompp_command
        
        # 4. 如果是重新开始模式
        # 4.1 如果mdrun命令已经包含grompp（多行字符串）
        if isinstance(result, str) and "\n" in result and "gmx grompp" in result:
            return result.split('\n')  # 拆分成命令列表
        
        # 4.2 如果只有mdrun命令，需要单独生成grompp
        elif isinstance(result, str):
            grompp_cmd = self.generate_grompp_command(step_type)
            return [grompp_cmd, result]
        
        return None
    ##############################
    def generate_complete_workflow(self):
        """生成完整工作流程（支持续跑只生成 mdrun）"""
        sim_type = self.ui.sim_type_combo.currentText()
        commands = []

        def _process_step(step_type):
            mdrun_cmd = self.generate_mdrun_command(step_type)
            if mdrun_cmd is None:
                return None, None

            # 检查是否是续跑模式（返回元组）
            if isinstance(mdrun_cmd, tuple) and len(mdrun_cmd) == 2 and mdrun_cmd[0] == "RESUME_MODE":
                return 'resume', [mdrun_cmd[1]]

            # 转换为字符串处理
            cmd_str = str(mdrun_cmd) if mdrun_cmd else ""
            
            # 续跑：直接返回
            if cmd_str.strip().startswith(("gmx mdrun", "mpirun", "mpiexec")) and "\n" not in cmd_str:
                return 'resume', [cmd_str]

            # 重新开始
            if "\n" in cmd_str and "gmx grompp" in cmd_str:
                return 'ok', [cmd_str]

            grompp_cmd = self.generate_grompp_command(step_type)
            return 'ok', [grompp_cmd, cmd_str]

        # 顺序执行流程，根据模拟类型调整步骤
        workflow_steps = self._get_workflow_steps(sim_type)
        
        for step in workflow_steps:
            status, cmds = _process_step(step)
            if status is None:
                return None
            if status == 'resume':
                return cmds  # 直接返回续跑命令
            if cmds:  # 确保cmds不为None
                commands.extend(cmds)

        return commands
    
    def _get_workflow_steps(self, sim_type):
        """根据模拟类型获取工作流程步骤"""
        if sim_type == '真空模拟':
            return ['minimization', 'production']
        elif sim_type == '气相模拟':
            return ['minimization', 'nvt', 'production']  # 气相模拟跳过NPT
        else:
            return ['minimization', 'nvt', 'npt', 'production']
    
    def generate_editconf_command(self, input_file, output_file, a, b, c):
        """生成editconf命令用于设置盒子尺寸"""
        if not input_file or not output_file:
            raise ValueError("输入文件和输出文件路径不能为空")
        
        if a <= 0 or b <= 0 or c <= 0:
            raise ValueError("盒子尺寸必须大于0")
        
        # 构建editconf命令
        command = f"gmx editconf -f \"{input_file}\" -o \"{output_file}\" -box {a:.3f} {b:.3f} {c:.3f}"
        return command
    
    def generate_editconf_center_command(self, input_file, output_file):
        """生成editconf命令用于PDB文件的居中操作
        
        PDB文件使用editconf进行居中是推荐方法，避免trjconv的"Cannot read from input"错误
        """
        if not input_file or not output_file:
            raise ValueError("输入文件和输出文件路径不能为空")
        
        # 检查输入文件是否为PDB格式
        input_ext = os.path.splitext(input_file)[1].lower()
        if input_ext != '.pdb':
            raise ValueError(f"此方法专用于PDB文件，当前文件类型: {input_ext}")
        
        # 对PDB文件使用editconf进行居中操作
        # -c 参数表示将分子居中到盒子中心
        command = f'gmx editconf -f "{input_file}" -o "{output_file}" -c'
        
        return command
    
    def generate_trjconv_center_command(self, input_file, output_file, center_group="Protein", output_group="System", pbc="mol", tpr_file=None):
        """生成trjconv命令用于结构居中操作
        
        严格遵循GROMACS规则：
        - .gro 文件：使用 -s input.gro -f input.gro -center
        - 轨迹文件(.xtc/.trr)：使用 -s system.tpr -f traj.xtc -center -pbc mol
        - 所有情况都必须显式指定 -s 参数
        - trjconv -center 需要两次分组选择：居中组和输出组
        
        Args:
            input_file: 输入文件路径
            output_file: 输出文件路径
            center_group: 第一次选择 - 要居中的分组
            output_group: 第二次选择 - 要输出的分组
            pbc: PBC参数
            tpr_file: TPR文件路径（可选）
        """
        if not input_file or not output_file:
            raise ValueError("输入文件和输出文件路径不能为空")
        
        # 判断文件类型
        input_ext = os.path.splitext(input_file)[1].lower()
        is_coordinate_file = input_ext == '.gro'
        is_trajectory_file = input_ext in ['.xtc', '.trr']
        
        # 构建命令 - 使用两次分组选择
        if is_coordinate_file:
            # 情况A：输入文件是 .gro（单帧结构）
            # 命令格式：printf "%s\n%s\n" "center_group" "output_group" | gmx trjconv -s input.gro -f input.gro -o centered.gro -center
            if pbc != "none":
                # 返回警告信息，但仍然生成命令
                warning_msg = (
                    "\n警告：对于 .gro 文件，不建议使用 PBC 参数。\n"
                    "如需使用 PBC 功能，请提供 .tpr 文件。\n"
                    "当前将使用简化的居中命令。\n"
                )
            else:
                warning_msg = ""
            
            # 对 .gro 文件：务必使用 -s input.gro，使用printf提供两次输入
            command = f'printf "%s\\n%s\\n" "{center_group}" "{output_group}" | gmx trjconv -s "{input_file}" -f "{input_file}" -o "{output_file}" -center'
            return command + warning_msg
            
        elif is_trajectory_file:
            # 情况B：输入文件是 .xtc 或 .trr（轨迹文件）
            # 命令格式：printf "%s\n%s\n" "center_group" "output_group" | gmx trjconv -s system.tpr -f traj.xtc -o centered.xtc -center -pbc mol
            if pbc != "none" and not tpr_file:
                raise ValueError(
                    f"对于轨迹文件 {input_ext}，使用 PBC 参数时必须提供 .tpr 文件"
                )
            
            command = f'printf "%s\\n%s\\n" "{center_group}" "{output_group}" | gmx trjconv'
            
            # 对 .xtc/.trr 文件：务必使用 -s system.tpr
            if tpr_file:
                command += f' -s "{tpr_file}"'
            else:
                # 如果没有TPR文件但PBC是none，则不需要TPR
                # 但这种情况下仍然需要一个结构参考文件
                if pbc == "none":
                    # 对于轨迹文件，即使不使用PBC，也建议提供TPR
                    warning_msg = "\n注意：对于轨迹文件，建议提供 .tpr 文件以获得更好的结果。\n"
                    # 在这种情况下，我们可以尝试使用轨迹文件本身作为参考
                    command += f' -s "{input_file}"'
                else:
                    raise ValueError("轨迹文件使用PBC时必须提供 .tpr 文件")
            
            command += f' -f "{input_file}" -o "{output_file}" -center'
            
            if pbc != "none":
                if pbc not in ['mol', 'atom', 'res']:
                    raise ValueError("PBC参数必须是 mol、atom 或 res 之一")
                command += f' -pbc {pbc}'
            
            # 如果有警告信息，添加到命令后
            if 'warning_msg' in locals():
                command += warning_msg
                
            return command
            
        else:
            # 其他文件类型，默认使用简化命令
            warning_msg = f"\n注意：未识别的文件类型 {input_ext}，使用默认参数。\n"
            command = f'printf "%s\\n%s\\n" "{center_group}" "{output_group}" | gmx trjconv -s "{input_file}" -f "{input_file}" -o "{output_file}" -center'
            
            if pbc != "none":
                if pbc not in ['mol', 'atom', 'res']:
                    raise ValueError("PBC参数必须是 mol、atom、res 或 none 之一")
                command += f' -pbc {pbc}'
                
            return command + warning_msg
    #############################
class FileManager:
    """文件命名管理器"""
    def __init__(self, ui_reference):
        self.ui = ui_reference  # 引用UI界面获取用户选择的文件
        self.step_names = {
            'minimization': 'em',
            'nvt': 'nvt',
            'npt': 'npt',
            'production': 'md'
        }

    def get_user_selected_files(self):
        """获取用户选择的文件"""
        return {
            'gro': self.ui.gro_file_edit.text().strip(),
            'top': self.ui.top_file_edit.text().strip(),
            'itp': self.ui.itp_file_edit.text().strip(), # 可能为空
            'pdb': self.ui.pdb_file_edit.text().strip()
        }

    def get_input_structure(self, step_type, completed_steps):
        """获取输入结构文件 - 根据实际情况"""
        user_files = self.get_user_selected_files()
        if step_type == 'minimization':
            # 优先使用用户选择的GRO文件，如果没有则使用PDB
            if user_files['gro'] and os.path.exists(user_files['gro']):
                return user_files['gro']
            elif user_files['pdb'] and os.path.exists(user_files['pdb']):
                return user_files['pdb']  # GROMACS可以直接读取PDB
            else:
                return None
        elif step_type == 'nvt':
            return 'em.gro'
        elif step_type == 'npt':
            return 'nvt.gro'
        elif step_type == 'production':
            # 气相模拟跳过npt步骤
            if self.ui.sim_type_combo.currentText() == '气相模拟':
                return 'nvt.gro'
            else:
                return 'npt.gro'

    def get_topology_file(self):
        """获取拓扑文件"""
        user_files = self.get_user_selected_files()
        if user_files['top'] and os.path.exists(user_files['top']):
            return user_files['top']
        else:
            return 'topol.top'  # 默认名称

    def get_mdp_filename(self, step_type):
        """获取MDP文件名"""
        return f"{self.step_names[step_type]}.mdp"

class WorkflowManager:
    """工作流程管理器"""
    def __init__(self):
        self.completed_steps = []
        self.current_step = None
        self.available_files = {}

    def mark_step_completed(self, step_name):
        """标记步骤完成"""
        if step_name not in self.completed_steps:
            self.completed_steps.append(step_name)

    def get_next_available_step(self):
        """获取下一个可执行步骤"""
        if not self.completed_steps:
            return 'minimization'
        elif 'minimization' in self.completed_steps and 'nvt' not in self.completed_steps:
            return 'nvt'
        elif 'nvt' in self.completed_steps and 'npt' not in self.completed_steps:
            return 'npt'
        elif 'npt' in self.completed_steps and 'production' not in self.completed_steps:
            return 'production'
        return None

    def get_completed_steps(self):
        """获取已完成步骤"""
        return self.completed_steps

class MDPGenerator:
    """MDP文件生成器类，包含静态方法生成不同类型的MDP文件"""
    
    @staticmethod
    def generate_mdp_content(mdp_type, parameters):
        """统一生成MDP内容的函数
        
        Args:
            mdp_type (str): MDP类型 ('minimization', 'nvt', 'npt', 'production')
            parameters (dict): 参数字典
            
        Returns:
            str: 生成的MDP文件内容
        """
        if mdp_type == 'minimization':
            return MDPGenerator.generate_minimization_mdp(parameters)
        elif mdp_type == 'nvt':
            return MDPGenerator.generate_nvt_mdp(parameters)
        elif mdp_type == 'npt':
            return MDPGenerator.generate_npt_mdp(parameters)
        elif mdp_type == 'production':
            return MDPGenerator.generate_production_mdp(parameters)
        else:
            raise ValueError(f"不支持的MDP类型: {mdp_type}")
    @staticmethod
    def generate_minimization_mdp(params):
        """生成能量最小化MDP文件"""
        # 检查语言设置
        is_english = hasattr(lang_manager, 'current_language') and lang_manager.current_language == 'en'
        
        if is_english:
            mdp_content = f"""; ========================================================================
; 🔧 GROMACS Energy Minimization MDP Parameter File
; ========================================================================
; Function: Remove bad contacts and high-energy conformations from the system
; Application: Preprocessing step for all simulation types
; ========================================================================

; 🚀 Integrator Settings
; ========================================================================
integrator      = {params['integrator']}        ; Steepest descent optimizer
nsteps          = {params['nsteps']}            ; Maximum optimization steps
emtol           = {params['emtol']}             ; Convergence criterion: max force < {params['emtol']} kJ/mol/nm
emstep          = {params['emstep']}            ; Optimization step size (nm)

; 🔗 Bond Constraint Settings
; ========================================================================
constraints     = all-bonds     ; Constrain all covalent bonds, prevent bond breaking
constraint_algorithm = lincs    ; LINCS algorithm, supports parallel computation

; 👥 Neighbor Search Settings
; ========================================================================
cutoff-scheme   = {params['cutoff-scheme']}    ; Cutoff scheme (recommended: Verlet)
nstlist         = {params['nstlist']}           ; Neighbor list update frequency
rlist           = {params['rlist']}             ; Short-range neighbor list cutoff radius (nm)

; ⚡ Electrostatic Interaction Settings
; ========================================================================
coulombtype     = {params['coulombtype']}       ; Electrostatic interaction method (recommended: PME)
rcoulomb        = {params.get('rcoulomb', '1.0')} ; Electrostatic cutoff radius (nm)

; 🌐 Van der Waals Interaction Settings
; ========================================================================
vdwtype         = {params.get('vdwtype', 'Cut-off')} ; VdW interaction method
rvdw            = {params.get('rvdw', '1.0')}   ; VdW cutoff radius (nm)

; 📊 PME Parameter Settings
; ========================================================================
pme_order       = {params.get('pme_order', '4')} ; PME interpolation order
fourierspacing  = {params.get('fourierspacing', '0.16')} ; FFT grid spacing (nm)

; 📦 Periodic Boundary Conditions
; ========================================================================
pbc             = {params['pbc']}               ; PBC type (xyz/xy/no)

; ========================================================================
; 📝 Notes: After energy minimization, check convergence and structural reasonableness
; ========================================================================
"""
        else:
            mdp_content = f""";
; ========================================================================
; 🔧 GROMACS 能量最小化 (Energy Minimization) MDP 参数文件
; ========================================================================
; 功能: 去除体系中的不良接触和高能构象
; 适用: 所有模拟类型的预处理步骤
; ========================================================================

; 🚀 积分器设置 (Integrator Settings)
; ========================================================================
integrator      = {params['integrator']}        ; 最陡下降法优化器
nsteps          = {params['nsteps']}            ; 最大优化步数
emtol           = {params['emtol']}             ; 收敛标准: 最大力 < {params['emtol']} kJ/mol/nm
emstep          = {params['emstep']}            ; 优化步长 (nm)

; 🔗 键约束设置 (Bond Constraints)
; ========================================================================
constraints     = all-bonds     ; 约束所有共价键，防止键断裂
constraint_algorithm = lincs    ; LINCS算法，支持并行计算
lincs_iter      = {params.get('lincs_iter', 1)}          ; LINCS精度参数
lincs_order     = {params.get('lincs_order', 4)}         ; LINCS阶数参数

; 👥 邻居搜索设置 (Neighbor Searching)
; ========================================================================
cutoff-scheme   = {params['cutoff-scheme']}    ; 截断方案 (推荐: Verlet)
nstlist         = {params['nstlist']}           ; 邻居列表更新频率
rlist           = {params['rlist']}             ; 短程邻居列表截断半径 (nm)

; 📊 输出控制 (Output Control)
; ========================================================================
nstxout         = {params.get('nstxout', 1000)}           ; 坐标输出频率 (生成.trr文件)
nstvout         = 1000          ; 速度输出频率 (每 1000 步)
nstxout-compressed = 1000   ; 压缩轨迹输出频率 (生成.xtc文件)
compressed-x-precision = 1000 ; xtc精度(默认1000，保留三位小数nm)
nstenergy       = {params.get('nstenergy', 1000)}       ; 能量输出频率 (每 {params.get('nstenergy', 1000)} 步)
nstlog          = {params.get('nstlog', 1000)}          ; 日志更新频率 (每 {params.get('nstlog', 1000)} 步)

; ⚡ 静电相互作用设置 (Electrostatics)
; ========================================================================
coulombtype     = {params['coulombtype']}       ; 静电相互作用方法 (推荐: PME)
rcoulomb        = {params.get('rcoulomb', '1.0')} ; 静电截断半径 (nm)

; 🌐 范德华相互作用设置 (Van der Waals)
; ========================================================================
vdwtype         = {params.get('vdwtype', 'Cut-off')} ; VdW相互作用方法
rvdw            = {params.get('rvdw', '1.0')}   ; VdW截断半径 (nm)

; 📊 PME参数设置 (PME Parameters)
; ========================================================================
pme_order       = {params.get('pme_order', '4')} ; PME插值阶数
fourierspacing  = {params.get('fourierspacing', '0.16')} ; FFT网格间距 (nm)

; 📦 周期性边界条件 (Periodic Boundary Conditions)
; ========================================================================
pbc             = {params['pbc']}               ; PBC类型 (xyz/xy/no)

; ========================================================================
; 📝 说明: 能量最小化完成后，应检查收敛性和最终结构的合理性
; ========================================================================
"""
        return mdp_content

    @staticmethod
    def generate_nvt_mdp(params):
        """生成NVT平衡MDP文件，支持模拟类型特定参数"""
        # 根据模拟类型调整参数
        sim_type = params.get('sim_type', '溶液模拟')
        
        # 气相模拟特殊处理
        if sim_type == '气相模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            tc_grps = params.get('tc-grps', 'System')
        # 真空模拟特殊处理
        elif sim_type == '真空模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            tc_grps = params.get('tc-grps', 'System')
        # 晶体模拟特殊处理
        elif sim_type == '晶体模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')
            tc_grps = params.get('tc-grps', 'System')
        # 膜模拟特殊处理
        elif sim_type == '膜模拟':
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'Berendsen')  # 预平衡使用Berendsen
            tc_grps = params.get('tc-grps', 'Protein Lipid Water_and_ions')
        # 自由能计算特殊处理
        elif sim_type == '自由能计算':
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')
            tc_grps = params.get('tc-grps', 'Protein Water_and_ions')
        # 溶液模拟和其他默认情况
        else:
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            tc_grps = params.get('tc-grps', 'Protein Water_and_ions')
        
        # 根据模拟类型生成特定说明
        sim_type_info = {
            '气相模拟': {
                'description': '气体分子模拟 - 使用1fs步长，适合高速运动的气相体系',
                'notes': '• 不使用压力耦合（后续直接跳转到生产运行）• 推荐使用大盒子（>5nm）避免周期性相互作用'
            },
            '溶液模拟': {
                'description': '蛋白质/小分子在水中的模拟 - 标准生物分子模拟',
                'notes': '• 使用双组温度耦合（蛋白质 + 水和离子） • 2fs步长适合受约束的共价键体系'
            },
            '晶体模拟': {
                'description': '固体材料晶体结构模拟 - 高密度系统',
                'notes': '• Nose-Hoover温度耦合提供更好的温度控制  • 1fs步长确保数值精度'
            },
            '膜模拟': {
                'description': '生物膜/膜蛋白体系模拟 - 非各向同性体系',
                'notes': '• 三组温度耦合（蛋白质 + 脂质 + 水和离子）\n• Berendsen预平衡阶段提供稳定性'
            },
            '真空模拟': {
                'description': '单分子/小分子群模拟 - 无周期性边界',
                'notes': '• 无压力耦合，适合高温模拟\n• 可选择性使用温度耦合器'
            },
            '自由能计算': {
                'description': '热力学积分/伞状采样模拟 - 高精度计算',
                'notes': '• Nose-Hoover提供更好的统计力学性质\n• 需要特殊的自由能参数设置'
            }
        }
        
        type_info = sim_type_info.get(sim_type, sim_type_info['溶液模拟'])
        
        mdp_content = f""";
; ========================================================================
; 🌡️ GROMACS NVT平衡 (Canonical Ensemble) MDP 参数文件
; ========================================================================
; 模拟类型: {sim_type}
; 功能描述: {type_info['description']}
;
; 📝 特殊说明:
; {type_info['notes']}
; ========================================================================

; 🚀 积分器设置 (Integrator Settings)
; ========================================================================
integrator      = {params['integrator']}            ; 跃蹄式积分器 (Leap-frog)
nsteps          = {params['nsteps']}            ; 模拟步数 ({params['nsteps']} × {dt} = {params['nsteps'] * dt:.1f} ps)
dt              = {dt}                ; 积分步长 ({dt*1000:.0f} fs)

; 📊 输出控制 (Output Control)
; ========================================================================
nstxout         = {params.get('nstxout', 500)}           ; 坐标输出频率 (生成.trr文件)
nstvout         = 500           ; 速度输出频率 (每 1.0 ps)
nstxout-compressed = {params.get('nstxout-compressed', 500)}   ; 压缩轨迹输出频率 (生成.xtc文件)
compressed-x-precision = {params.get('compressed-x-precision', 1000)} ; xtc精度(默认1000，保留三位小数nm)
nstenergy       = {params.get('nstenergy', 500)}       ; 能量输出频率 (每 {params.get('nstenergy', 500)} ps)
nstlog          = {params.get('nstlog', 500)}          ; 日志更新频率 (每 {params.get('nstlog', 500)} ps)

; 🔗 键约束设置 (Bond Constraints)
; ========================================================================
continuation    = {params.get('continuation', 'no')}     ; {'继续动力学运行' if params.get('continuation', 'no') == 'yes' else '首次动力学运行'}
constraint_algorithm = {params['constraint_algorithm']}    ; 约束算法
constraints     = {params['constraints']}       ; 约束类型 (包括重原子-氢键)
lincs_iter      = {params.get('lincs_iter', 1)}          ; LINCS精度参数
lincs_order     = {params.get('lincs_order', 4)}         ; LINCS阶数参数

; 👥 邻居搜索设置 (Neighbor Searching)
; ========================================================================
cutoff-scheme   = {params['cutoff-scheme']}    ; 截断方案 (推荐: Verlet)
nstlist         = {params['nstlist']}           ; 邻居列表更新频率
rlist           = {params['rlist']}             ; 短程邻居列表截断半径 (nm)

; ⚡ 静电相互作用设置 (Electrostatics)
; ========================================================================
coulombtype     = {params['coulombtype']}       ; 静电相互作用方法
rcoulomb        = {params.get('rcoulomb', '1.0')} ; 静电截断半径 (nm)

; 🌐 范德华相互作用设置 (Van der Waals)
; ========================================================================
vdwtype         = {params.get('vdwtype', 'Cut-off')} ; VdW相互作用方法
rvdw            = {params.get('rvdw', '1.0')}   ; VdW截断半径 (nm)

; 📊 PME参数设置 (PME Parameters)
; ========================================================================
pme_order       = {params.get('pme_order', '4')} ; PME插值阶数
fourierspacing  = {params.get('fourierspacing', '0.16')} ; FFT网格间距 (nm)

; 🌡️ 温度耦合设置 (Temperature Coupling) - 核心参数
; ========================================================================
tcoupl          = {tcoupl}            ; 温度耦合方法
tc-grps         = {tc_grps}           ; 温度耦合组
tau_t           = {params['tau_t']}             ; 温度耦合时间常数 (ps)
ref_t           = {params['ref_t']}             ; 参考温度 (K)

; 📎 压力耦合设置 (Pressure Coupling)
; ========================================================================
pcoupl          = no            ; NVT中不使用压力耦合

; 📦 周期性边界条件 (Periodic Boundary Conditions)
; ========================================================================
pbc             = {params['pbc']}               ; PBC类型 (xyz/xy/no)

; 🔄 色散校正 (Dispersion Correction)
; ========================================================================
DispCorr        = EnerPres      ; 考虑截断的VdW能量和压力校正

; 🎯 速度生成 (Velocity Generation)
; ========================================================================
gen_vel         = {'yes' if params['gen_vel'] else 'no'}        ; 是否生成初始速度
gen_temp        = {params['gen_temp']}          ; Maxwell分布温度 (K)
gen_seed        = -1            ; 随机数种子 (-1 = 随机)
"""
        if params.get('posres', False):
            mdp_content += "\n; 🔒 位置约束 (Position Restraints)\n; ========================================================================\n; define          = -DPOSRES      ; C-alpha原子位置约束\n"
        
        mdp_content += "\n; ========================================================================\n; 📝 说明: NVT平衡完成后，系统温度应稳定在设定值附近\n; • 检查温度收敛情况\n; • 观察动能和势能变化\n; • 确认系统结构稳定性\n; ========================================================================\n"
        return mdp_content

    @staticmethod
    def generate_npt_mdp(params):
        """生成NPT平衡MDP文件，支持模拟类型特定参数"""
        # 根据模拟类型调整参数
        sim_type = params.get('sim_type', '溶液模拟')
        
        # 气相模拟特殊处理
        if sim_type == '气相模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            pcoupl = 'no'  # 气相不使用压力耦合
            pcoupltype = 'isotropic'
            ref_p = '1.0'
            compressibility = '4.5e-05'
        # 真空模拟特殊处理
        elif sim_type == '真空模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = 'no'  # 真空模拟可以不使用温度耦合
            pcoupl = 'no'  # 真空不使用压力耦合
            pcoupltype = 'isotropic'
            ref_p = '1.0'
            compressibility = '4.5e-05'
        # 晶体模拟特殊处理
        elif sim_type == '晶体模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')
            pcoupl = params.get('pcoupl', 'Berendsen')  # 预平衡使用Berendsen
            pcoupltype = params.get('pcoupltype', 'isotropic')
            ref_p = params.get('ref_p', 1.0)
            compressibility = params.get('compressibility', '0')  # 固定晶格
        # 膜模拟特殊处理
        elif sim_type == '膜模拟':
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'Berendsen')  # 预平衡使用Berendsen
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')
            pcoupltype = 'semiisotropic'  # 半各向同性压力耦合
            ref_p = '1.0 1.0'  # XY和Z方向的参考压力
            compressibility = params.get('compressibility', '4.5e-05 4.5e-05')
        # 自由能计算特殊处理
        elif sim_type == '自由能计算':
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')
            pcoupltype = params.get('pcoupltype', 'isotropic')
            ref_p = params.get('ref_p', 1.0)
            compressibility = params.get('compressibility', '4.5e-05')
        # 溶液模拟和其他默认情况
        else:
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')
            pcoupltype = params.get('pcoupltype', 'isotropic')
            ref_p = params.get('ref_p', 1.0)
            compressibility = params.get('compressibility', '4.5e-05')
            
        # 根据模拟类型生成特定说明
        pressure_coupling_info = {
            '气相模拟': {
                'description': '气体分子模拟 - 禁用压力耦合',
                'pressure_notes': '• pcoupl = no : 气相不需要压力耦合\n;• 后续直接跳转到生产运行阶段'
            },
            '溶液模拟': {
                'description': '蛋白质/小分子在水中的模拟 - 各向同性压力耦合',
                'pressure_notes': '• pcoupltype = isotropic : 各向同性压力耦合 • ref_p = 1.0 bar : 标准大气压力 • Parrinello-Rahman : 适合生产运行的压力耦合器'
            },
            '晶体模拟': {
                'description': '固体材料晶体结构模拟 - 各向同性压力耦合',
                'pressure_notes': '• 预平衡阶段使用 Berendsen • compressibility = 0 : 固定晶格选项 • 生产运行将切换到 Parrinello-Rahman'
            },
            '膜模拟': {
                'description': '生物膜/膜蛋白体系模拟 - 半各向同性压力耦合',
                'pressure_notes': '• pcoupltype = semiisotropic : 半各向同性耦合\n• ref_p = 1.0 1.0 : XY和Z方向分别设置\n• compressibility = 4.5e-05 4.5e-05 : 对应的压缩系数\n• 适合膜蛋白和脂质双分子层体系'
            },
            '真空模拟': {
                'description': '单分子/小分子群模拟 - 禁用所有耦合',
                'pressure_notes': '• pcoupl = no : 真空中无压力概念\n• tcoupl = no : 可选禁用温度耦合\n• 此步骤实际上不会执行'
            },
            '自由能计算': {
                'description': '热力学积分/伞状采样模拟 - 高精度压力耦合',
                'pressure_notes': '• Nose-Hoover + Parrinello-Rahman : 高精度组合\n• 适合自由能计算的严格统计力学条件'
            }
        }
        
        type_info = pressure_coupling_info.get(sim_type, pressure_coupling_info['溶液模拟'])
        
        mdp_content = f""";
; ========================================================================
; 📎 GROMACS NPT平衡 (Isothermal-Isobaric Ensemble) MDP 参数文件
; ========================================================================
; 模拟类型: {sim_type}
; 功能描述: {type_info['description']}
;
; 📝 压力耦合特殊说明:
; {type_info['pressure_notes']}
; ========================================================================

; 🚀 积分器设置 (Integrator Settings)
; ========================================================================
integrator      = {params['integrator']}            ; 跃蹄式积分器 (Leap-frog)
nsteps          = {params['nsteps']}            ; 模拟步数 ({params['nsteps']} × {dt} = {params['nsteps'] * dt:.1f} ps)
dt              = {dt}                ; 积分步长 ({dt*1000:.0f} fs)

; 📊 输出控制 (Output Control)
; ========================================================================
nstxout         = {params.get('nstxout', 500)}           ; 坐标输出频率 (生成.trr文件)
nstvout         = 500           ; 速度输出频率 (每 1.0 ps)
nstxout-compressed = {params.get('nstxout-compressed', 500)}   ; 压缩轨迹输出频率 (生成.xtc文件)
compressed-x-precision = {params.get('compressed-x-precision', 1000)} ; xtc精度(默认1000，保留三位小数nm)
nstenergy       = {params.get('nstenergy', 500)}       ; 能量输出频率 (每 {params.get('nstenergy', 500)} ps)
nstlog          = {params.get('nstlog', 500)}          ; 日志更新频率 (每 {params.get('nstlog', 500)} ps)


; 🔗 键约束设置 (Bond Constraints)
; ========================================================================
continuation    = {'yes' if params.get('continuation', True) else 'no'}   ; 从 NVT 继续运行
constraint_algorithm = lincs    ; LINCS约束算法
constraints     = all-bonds     ; 约束所有共价键
lincs_iter      = {params.get('lincs_iter', 1)}          ; LINCS精度参数
lincs_order     = {params.get('lincs_order', 4)}         ; LINCS阶数参数

; 👥 邻居搜索设置 (Neighbor Searching)
; ========================================================================
cutoff-scheme   = {params['cutoff-scheme']}    ; 截断方案 (推荐: Verlet)
nstlist         = {params['nstlist']}           ; 邻居列表更新频率
rlist           = {params['rlist']}             ; 短程邻居列表截断半径 (nm)

; ⚡ 静电相互作用设置 (Electrostatics)
; ========================================================================
coulombtype     = {params['coulombtype']}       ; 静电相互作用方法
rcoulomb        = {params.get('rcoulomb', '1.0')} ; 静电截断半径 (nm)

; 🌐 范德华相互作用设置 (Van der Waals)
; ========================================================================
vdwtype         = {params.get('vdwtype', 'Cut-off')} ; VdW相互作用方法
rvdw            = {params.get('rvdw', '1.0')}   ; VdW截断半径 (nm)

; 📊 PME参数设置 (PME Parameters)
; ========================================================================
pme_order       = {params.get('pme_order', '4')} ; PME插值阶数
fourierspacing  = {params.get('fourierspacing', '0.16')} ; FFT网格间距 (nm)

; 🌡️ 温度耦合设置 (Temperature Coupling)
; ========================================================================
tcoupl          = {tcoupl}            ; 温度耦合方法
tc-grps         = {params['tc-grps']}           ; 温度耦合组
tau_t           = {params['tau_t']}             ; 温度耦合时间常数 (ps)
ref_t           = {params['ref_t']}             ; 参考温度 (K)

; 📎 压力耦合设置 (Pressure Coupling) - 核心参数
; ========================================================================
pcoupl          = {pcoupl}            ; 压力耦合类型
pcoupltype      = {pcoupltype}        ; 压力耦合几何形状
tau_p           = {params['tau_p']}             ; 压力耦合时间常数 (ps)
ref_p           = {ref_p}             ; 参考压力 (bar)
compressibility = {compressibility}   ; 压缩系数 (bar^-1)

; 📦 周期性边界条件 (Periodic Boundary Conditions)
; ========================================================================
pbc             = {params['pbc']}               ; PBC类型 (xyz/xy/no)

; 🔄 色散校正 (Dispersion Correction)
; ========================================================================
DispCorr        = {params['DispCorr']}          ; VdW截断校正方法

; 🎯 速度生成 (Velocity Generation)
; ========================================================================
gen_vel         = no            ; 不重新生成速度 (继续 NVT)
"""
        if params.get('posres', False):
            mdp_content += "\n; 🔒 位置约束 (Position Restraints)\n; ========================================================================\n; define          = -DPOSRES      ; NPT阶段位置约束\n"
        
        mdp_content += "\n; ========================================================================\n; 📝 说明: NPT平衡完成后，系统压力和密度应稳定在设定值附近\n; • 检查压力和密度收敛情况\n; • 观察盒子尺寸变化\n; • 确认系统体积稳定性\n; ========================================================================\n"
        return mdp_content

    @staticmethod
    def generate_production_mdp(params):
        """生成生产运行MDP文件，支持模拟类型特定参数"""
        # 根据模拟类型调整参数
        sim_type = params.get('sim_type', '溶液模拟')
        
        # 气相模拟特殊处理
        if sim_type == '气相模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            pcoupl = 'no'  # 气相不使用压力耦合
            pcoupltype = 'isotropic'
            ref_p = '1.0'
            compressibility = '4.5e-05'
            nstxout_compressed = params.get('nstxout-compressed', 1000)
            continuation_comment = '; Restarting after NVT (gas phase skips NPT)'
        # 真空模拟特殊处理
        elif sim_type == '真空模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'V-rescale')  # 或'no'
            pcoupl = 'no'  # 真空不使用压力耦合
            pcoupltype = 'isotropic'
            ref_p = '1.0'
            compressibility = '4.5e-05'
            nstxout_compressed = params.get('nstxout-compressed', 1000)
            continuation_comment = '; Restarting after EM (vacuum skips NVT/NPT)'
        # 晶体模拟特殊处理
        elif sim_type == '晶体模拟':
            dt = params.get('dt', 0.001)  # 1 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')  # 生产运行使用Parrinello-Rahman
            pcoupltype = params.get('pcoupltype', 'isotropic')
            ref_p = params.get('ref_p', 1.0)
            compressibility = params.get('compressibility', '4.5e-05')
            nstxout_compressed = params.get('nstxout-compressed', 5000)
            continuation_comment = '; Restarting after NPT'
        # 膜模拟特殊处理
        elif sim_type == '膜模拟':
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')  # 生产运行使用Nose-Hoover
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')
            pcoupltype = 'semiisotropic'  # 半各向同性压力耦合
            ref_p = '1.0 1.0'  # XY和Z方向的参考压力
            compressibility = params.get('compressibility', '4.5e-05 4.5e-05')
            nstxout_compressed = params.get('nstxout-compressed', 5000)
            continuation_comment = '; Restarting after NPT (semiisotropic)'
        # 自由能计算特殊处理
        elif sim_type == '自由能计算':
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'Nose-Hoover')
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')
            pcoupltype = params.get('pcoupltype', 'isotropic')
            ref_p = params.get('ref_p', 1.0)
            compressibility = params.get('compressibility', '4.5e-05')
            nstxout_compressed = params.get('nstxout-compressed', 1000)  # 自由能需要更频繁输出
            continuation_comment = '; Restarting after NPT (free energy calculation)'
        # 溶液模拟和其他默认情况
        else:
            dt = params.get('dt', 0.002)  # 2 fs
            tcoupl = params.get('tcoupl', 'V-rescale')
            pcoupl = params.get('pcoupl', 'Parrinello-Rahman')
            pcoupltype = params.get('pcoupltype', 'isotropic')
            ref_p = params.get('ref_p', 1.0)
            compressibility = params.get('compressibility', '4.5e-05')
            nstxout_compressed = params.get('nstxout-compressed', 5000)
            continuation_comment = '; Restarting after NPT'
            
        # 根据模拟类型生成特定说明
        production_info = {
            '气相模拟': {
                'description': '气体分子生产运行 - 高频率输出，无压力耦合',
                'continuation_comment': '; 从 NVT 直接继续 (气相跳过 NPT)',
                'notes': '• 高频率输出适合快速运动的气相分子  • 无压力耦合，适合大盒子系统  • 建议使用GPU加速'
            },
            '溶液模拟': {
                'description': '蛋白质/小分子溶液生产运行 - 标准生物分子模拟',
                'continuation_comment': '; 从 NPT 继续运行',
                'notes': '• 标准输出频率适合长时间模拟 • Parrinello-Rahman 提供稳定的压力控制 • 可考虑去除位置约束'
            },
            '晶体模拟': {
                'description': '固体材料晶体生产运行 - 高精度结构性质研究',
                'continuation_comment': '; 从 NPT 继续运行',
                'notes': '• Nose-Hoover + Parrinello-Rahman 高精度组合 • 可研究弹性、热导率等性质 • 建议较长模拟时间'
            },
            '膜模拟': {
                'description': '生物膜/膜蛋白生产运行 - 半各向同性系统',
                'continuation_comment': '; 从 NPT 继续运行 (半各向同性)',
                'notes': '• 保持半各向同性压力耦合 • 三组温度耦合保证各组分温度稳定 • 适合研究膜蛋白功能和脂质相互作用'
            },
            '真空模拟': {
                'description': '单分子/小分子群真空生产运行 - 无周期性边界',
                'continuation_comment': '; 从 EM 直接继续 (真空跳过 NVT/NPT)',
                'notes': '• 无周期性边界条件 • 可选温度耦合，适合高温模拟 • 高频率输出捕捉快速变化'
            },
            '自由能计算': {
                'description': '热力学积分/伞状采样生产运行 - 高精度自由能计算',
                'continuation_comment': '; 从 NPT 继续运行 (自由能计算)',
                'notes': '• 高频率输出用于精确的自由能分析 • Nose-Hoover 保证正确的统计力学集合 • 需要额外的 λ 参数设置'
            }
        }
        
        type_info = production_info.get(sim_type, production_info['溶液模拟'])
        
        # 计算模拟时间
        simulation_time_ns = params['nsteps'] * dt / 1000.0
        
        mdp_content = f""";
; ========================================================================
; 🏃 GROMACS 生产运行 (Production Run) MDP 参数文件
; ========================================================================
; 模拟类型: {sim_type}
; 功能描述: {type_info['description']}
; 模拟时间: {simulation_time_ns:.2f} ns ({params['nsteps']:,} 步 × {dt} ps)
;
; 📝 特殊说明:
; {type_info['notes']}
; ========================================================================

; 🚀 积分器设置 (Integrator Settings)
; ========================================================================
integrator      = {params['integrator']}            ; 跃蹄式积分器 (Leap-frog)
nsteps          = {params['nsteps']}            ; 模拟步数 (总时间: {simulation_time_ns:.2f} ns)
dt              = {dt}                ; 积分步长 ({dt*1000:.0f} fs)

; 📊 输出控制 (Output Control) - 性能优化
; ========================================================================
nstxout         = {params.get('nstxout', 0)}             ; 坐标输出频率 (生成.trr文件)
nstvout         = 0             ; 不频繁保存速度 (节省磁盘空间)
nstxout-compressed = {nstxout_compressed} ; 压缩轨迹保存频率 (每 {nstxout_compressed*dt:.1f} ps)
compressed-x-precision = {params.get('compressed-x-precision', 1000)} ; xtc精度(默认1000，保留三位小数nm)
nstenergy       = {params['nstenergy']}         ; 能量输出频率 (每 {params['nstenergy']*dt:.1f} ps)
nstlog          = {params['nstlog']}            ; 日志更新频率 (每 {params['nstlog']*dt:.1f} ps)

; 🔗 键约束设置 (Bond Constraints)
; ========================================================================
continuation    = yes           {continuation_comment}
constraint_algorithm = {params.get('constraint_algorithm', 'lincs').lower()}    ; LINCS约束算法
constraints     = {params.get('constraints', 'all-bonds')}     ; 约束所有共价键
lincs_iter      = {params.get('lincs_iter', 1)}          ; LINCS精度参数
lincs_order     = {params.get('lincs_order', 4)}         ; LINCS阶数参数

; 👥 邻居搜索设置 (Neighbor Searching)
; ========================================================================
cutoff-scheme   = {params['cutoff-scheme']}    ; 截断方案 (推荐: Verlet)
nstlist         = {params['nstlist']}           ; 邻居列表更新频率
rlist           = {params['rlist']}             ; 短程邻居列表截断半径 (nm)

; ⚡ 静电相互作用设置 (Electrostatics)
; ========================================================================
coulombtype     = {params['coulombtype']}       ; 静电相互作用方法
rcoulomb        = {params.get('rcoulomb', '1.0')} ; 静电截断半径 (nm)

; 🌐 范德华相互作用设置 (Van der Waals)
; ========================================================================
vdwtype         = {params.get('vdwtype', 'Cut-off')} ; VdW相互作用方法
rvdw            = {params.get('rvdw', '1.0')}   ; VdW截断半径 (nm)

; 📊 PME参数设置 (PME Parameters)
; ========================================================================
pme_order       = {params.get('pme_order', '4')} ; PME插值阶数
fourierspacing  = {params.get('fourierspacing', '0.16')} ; FFT网格间距 (nm)

; 🌡️ 温度耦合设置 (Temperature Coupling)
; ========================================================================
tcoupl          = {tcoupl}            ; 温度耦合方法
tc-grps         = {params['tc-grps']}           ; 温度耦合组
tau_t           = {params['tau_t']}             ; 温度耦合时间常数 (ps)
ref_t           = {params['ref_t']}             ; 参考温度 (K)

; 📎 压力耦合设置 (Pressure Coupling)
; ========================================================================
pcoupl          = {pcoupl}            ; 压力耦合类型
pcoupltype      = {pcoupltype}        ; 压力耦合几何形状
tau_p           = {params['tau_p']}             ; 压力耦合时间常数 (ps)
ref_p           = {ref_p}             ; 参考压力 (bar)
compressibility = {compressibility}   ; 压缩系数 (bar^-1)

; 📦 周期性边界条件 (Periodic Boundary Conditions)
; ========================================================================
pbc             = {params['pbc']}               ; PBC类型 (xyz/xy/no)

; 🔄 色散校正 (Dispersion Correction)
; ========================================================================
DispCorr        = {params['DispCorr']}          ; VdW截断校正方法

; 🎯 速度生成 (Velocity Generation)
; ========================================================================
gen_vel         = no            ; 不重新生成速度 (继续上一步)
"""
        if params.get('posres', False):
            mdp_content += "\n; 🔒 位置约束 (Position Restraints)\n; ========================================================================\n; 注意: 生产运行中已移除位置约束\n"
        
        # 添加性能提示
        performance_tips = ""
        if sim_type == '气相模拟':
            performance_tips = "; • 考虑使用 GPU 加速\n; • 可适当增大 nstlist 值"
        elif sim_type == '溶液模拟':
            performance_tips = "; • 长时间模拟可考虑去除位置约束\n; • 可使用 MPI + GPU 混合并行"
        elif sim_type == '膜模拟':
            performance_tips = "; • 适合使用多 GPU并行\n; • 注意监控膜厢的稳定性"
        elif sim_type == '自由能计算':
            performance_tips = "; • 需要额外设置 TI 或 Umbrella 参数\n; • 建议使用多窗口并行计算"
        
        mdp_content += f"\n; ========================================================================\n; 📝 生产运行说明：\n; • 检查能量守恒性和系统稳定性\n; • 定期备份 .cpt 检查点文件\n; • 监控温度、压力、密度等关键参数\n; ========================================================================\n; 🚀 性能优化建议：\n{performance_tips}\n; ========================================================================\n"
        return mdp_content

class GromacsUI(QMainWindow):
    """GROMACS分子动力学模拟PyQt5用户界面主类"""
    def __init__(self):
        super().__init__()
        
        # 初始化语言管理器
        self.lang_manager = LanguageManager()
        
        self.setWindowTitle("GROMACS Molecular Dynamics Interface")
        self.setGeometry(50, 50, 1200, 700)
        self.setMinimumSize(1000, 600)

        # 全局样式表
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; }
            QTabWidget::pane { border: 1px solid #ddd; background: white; border-radius: 4px; }
            QTabBar::tab {
                padding: 6px 16px; margin-right: 2px;
                background: #e8e8e8; border: 1px solid #ccc; border-bottom: none;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: white; font-weight: bold;
                border-bottom: 2px solid #4CAF50;
            }
            QTabBar::tab:hover { background: #f0f0f0; }
            QGroupBox {
                font-weight: bold; border: 1px solid #ddd; border-radius: 6px;
                margin-top: 12px; padding: 12px 8px 8px 8px; background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 6px;
                color: #333; font-size: 12px;
            }
            QPushButton {
                padding: 5px 12px; border: 1px solid #ccc; border-radius: 4px;
                background: #f8f8f8; font-size: 11px; min-height: 20px;
            }
            QPushButton:hover { background: #e8f5e9; border-color: #4CAF50; }
            QPushButton:pressed { background: #c8e6c9; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                padding: 4px 6px; border: 1px solid #ccc; border-radius: 3px;
                background: white; font-size: 11px; min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #4CAF50;
            }
            QLabel { font-size: 11px; }
            QScrollArea { border: none; }
            QMessageBox {
                background-color: #f5f5f5;
            }
            QMessageBox QLabel {
                color: #333; font-size: 12px; min-width: 280px;
            }
            QMessageBox QPushButton {
                min-width: 80px; padding: 6px 16px; font-size: 12px;
                border: 1px solid #bbb; border-radius: 4px; background: #fafafa;
            }
            QMessageBox QPushButton:hover {
                background: #e8f5e9; border-color: #4CAF50;
            }
            QMessageBox QPushButton:pressed {
                background: #c8e6c9;
            }
        """)
        # 统一按钮配色样式表
        self._btn_primary = "QPushButton { background-color: #4CAF50; color: white; border: none; font-weight: bold; padding: 6px 16px; border-radius: 4px; } QPushButton:hover { background-color: #45a049; } QPushButton:pressed { background-color: #3d8b40; }"
        self._btn_secondary = "QPushButton { background-color: #2196F3; color: white; border: none; font-weight: bold; padding: 6px 16px; border-radius: 4px; } QPushButton:hover { background-color: #1e88e5; } QPushButton:pressed { background-color: #1976D2; }"
        self._btn_danger = "QPushButton { background-color: #f44336; color: white; border: none; font-weight: bold; padding: 6px 16px; border-radius: 4px; } QPushButton:hover { background-color: #e53935; } QPushButton:pressed { background-color: #d32f2f; }"
        self._btn_tool = "QPushButton { background-color: #607D8B; color: white; border: none; font-weight: bold; padding: 6px 16px; border-radius: 4px; } QPushButton:hover { background-color: #546E7A; } QPushButton:pressed { background-color: #455A64; }"
        # 初始化组件
        self.file_manager = FileManager(self)
        self.workflow_manager = WorkflowManager()
        self.command_generator = GMXCommandGenerator(self)
        self.command_executor = None # 初始化为 None
        # 初始化命令历史
        self.command_history_text = ""
        # 初始化MDP参数字典
        self.selected_mdp_parameters = {}
        # 初始化线程执行器列表
        self.executors = []
        # 创建主分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        # 创建左侧控制面板和右侧输出面板
        self.create_control_panel()
        self.create_output_panel()
        # 连接信号和槽
        self.connect_signals()
        # 更新工作流程状态
        self.update_workflow_status()
        # 启动时自动检测文件
        self.auto_detect_files()

    def update_forcefield_info(self, forcefield):
        """更新力场适用说明"""
        # 力场适用说明映射
        forcefield_info = {
            "amber99sb-ildn": "适用于蛋白质、核酸等生物大分子",
            "amber99sb": "适用于蛋白质、核酸等生物大分子",
            "amber03": "适用于蛋白质、核酸等生物大分子",
            "amber94": "适用于蛋白质、核酸等生物大分子",
            "amber96": "适用于蛋白质、核酸等生物大分子",
            "amber99": "适用于蛋白质、核酸等生物大分子",
            "charmm27": "适用于蛋白质、核酸等生物大分子",
            "gromos43a1": "适用于蛋白质、核酸等生物大分子",
            "gromos43a2": "适用于蛋白质、核酸等生物大分子",
            "gromos45a3": "适用于蛋白质、核酸等生物大分子",
            "gromos53a5": "适用于蛋白质、核酸等生物大分子",
            "gromos53a6": "适用于蛋白质、核酸等生物大分子",
            "gromos54a7": "适用于蛋白质、核酸等生物大分子",
            "oplsaa": "适用于蛋白质、核酸等生物大分子",
            "gaff": "适用于小分子、配体（需额外工具）",
            "CGenFF": "适用于小分子、配体（需额外工具）"
        }
        
        # 获取当前力场的适用说明
        info = forcefield_info.get(forcefield, "适用于蛋白质、核酸等生物大分子")
        self.pdb2gmx_forcefield_info.setText(f"💡 {info}")

    def create_output_panel(self):
        """创建右侧输出面板"""
        # 创建滚动区域容器
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建输出面板widget
        self.output_panel = QWidget()
        output_layout = QVBoxLayout(self.output_panel)
        
        # 设置适合的边距和间距
        output_layout.setContentsMargins(10, 10, 10, 10)
        output_layout.setSpacing(8)
        
        # 创建输出选项卡控件
        self.output_tab_widget = QTabWidget()
        
        # 创建各个输出选项卡
        # self.create_structure_centering_info_tab()  # 结构居中信息选项卡（已移除）
        self.create_mdp_preview_tab()  # MDP预览选项卡
        self.create_cmd_preview_tab()  # 命令预览选项卡
        self.create_realtime_output_tab()  # 实时输出选项卡
        self.create_execution_log_tab()  # 执行日志选项卡
        self.create_file_status_tab()  # 文件状态选项卡
        self.create_language_settings_tab()  # 语言设置选项卡
        
        output_layout.addWidget(self.output_tab_widget)
        
        # 将输出面板设置为滚动区域的子widget
        scroll_area.setWidget(self.output_panel)
        
        # 将滚动区域添加到分割器
        self.splitter.addWidget(scroll_area)

    def create_mdp_preview_tab(self):
        """创建MDP预览选项卡"""
        self.mdp_preview_tab = QWidget()
        layout = QVBoxLayout(self.mdp_preview_tab)
        
        # 添加说明文本
        info_label = QLabel("MDP参数预览：显示当前步骤的MDP参数设置")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        layout.addWidget(info_label)
        
        # MDP预览区域
        self.mdp_preview_text = QTextEdit()
        self.mdp_preview_text.setReadOnly(False)  # 设置为可编辑模式
        # 应用MDP语法高亮器
        self.mdp_highlighter = MDPHighlighter(self.mdp_preview_text.document())
        # 设置字体
        font = QFont("Courier New", 10)
        self.mdp_preview_text.setFont(font)
        layout.addWidget(self.mdp_preview_text)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        self.select_mdp_btn = QPushButton("选择MDP文件")
        self.save_mdp_btn = QPushButton("保存MDP文件")
        self.save_mdp_btn.setStyleSheet(self._btn_secondary)
        # 连接信号
        # 移除这里过早的信号连接，让connect_signals方法统一处理
        # self.mdp_search_btn.clicked.connect(self.search_mdp_parameters)
        # self.mdp_search_edit.returnPressed.connect(self.search_mdp_parameters)
        button_layout.addWidget(self.select_mdp_btn)
        button_layout.addWidget(self.save_mdp_btn)
        layout.addLayout(button_layout)
        
        # 只添加一次MDP预览选项卡，使用语言管理器，提供默认值
        tab_text = self.lang_manager.get_text('mdp_preview')
        if tab_text is None:
            tab_text = "MDP预览"
        self.output_tab_widget.addTab(self.mdp_preview_tab, tab_text)

    def generate_nvt_mdp_content(self):
        """生成NVT平衡MDP内容"""
        lines = [
            "; NVT平衡参数",
            self._format_mdp_line("integrator", "md"),
            self._format_mdp_line("dt", "0.002"),
            self._format_mdp_line("nsteps", "50000"),
            self._format_mdp_line("nstcomm", "100"),
            self._format_mdp_line("nstxout", "1000"),
            self._format_mdp_line("nstvout", "1000"),
            self._format_mdp_line("nstfout", "1000"),
            self._format_mdp_line("nstlog", "1000"),
            self._format_mdp_line("nstenergy", "1000"),
            self._format_mdp_line("nstlist", "10"),
            self._format_mdp_line("cutoff-scheme", "Verlet"),
            self._format_mdp_line("ns_type", "grid"),
            self._format_mdp_line("coulombtype", "PME"),
            self._format_mdp_line("rcoulomb", "1.0"),
            self._format_mdp_line("rvdw", "1.0"),
            self._format_mdp_line("pbc", "xyz"),
            self._format_mdp_line("tcoupl", "V-rescale"),
            self._format_mdp_line("tc-grps", "Protein Water_and_ions"),
            self._format_mdp_line("tau_t", "0.1 0.1"),
            self._format_mdp_line("ref_t", "300 300"),
            ""
        ]
        return "\n".join(lines)

    def generate_npt_mdp_content(self):
        """生成NPT平衡MDP内容"""
        lines = [
            "; NPT平衡参数",
            self._format_mdp_line("integrator", "md"),
            self._format_mdp_line("dt", "0.002"),
            self._format_mdp_line("nsteps", "50000"),
            self._format_mdp_line("nstcomm", "100"),
            self._format_mdp_line("nstxout", "1000"),
            self._format_mdp_line("nstvout", "1000"),
            self._format_mdp_line("nstfout", "1000"),
            self._format_mdp_line("nstlog", "1000"),
            self._format_mdp_line("nstenergy", "1000"),
            self._format_mdp_line("nstlist", "10"),
            self._format_mdp_line("cutoff-scheme", "Verlet"),
            self._format_mdp_line("ns_type", "grid"),
            self._format_mdp_line("coulombtype", "PME"),
            self._format_mdp_line("rcoulomb", "1.0"),
            self._format_mdp_line("rvdw", "1.0"),
            self._format_mdp_line("pbc", "xyz"),
            self._format_mdp_line("tcoupl", "V-rescale"),
            self._format_mdp_line("tc-grps", "Protein Water_and_ions"),
            self._format_mdp_line("tau_t", "0.1 0.1"),
            self._format_mdp_line("ref_t", "300 300"),
            self._format_mdp_line("pcoupl", "Parrinello-Rahman"),
            self._format_mdp_line("pcoupltype", "isotropic"),
            self._format_mdp_line("tau_p", "2.0"),
            self._format_mdp_line("ref_p", "1.0"),
            self._format_mdp_line("compressibility", "4.5e-5"),
            ""
        ]
        return "\n".join(lines)

    def generate_production_mdp_content(self):
        """生成生产运行MDP内容"""
        lines = [
            "; 生产运行参数",
            self._format_mdp_line("integrator", "md"),
            self._format_mdp_line("dt", "0.002"),
            self._format_mdp_line("nsteps", "1000000"),
            self._format_mdp_line("nstcomm", "100"),
            self._format_mdp_line("nstxout", "5000"),
            self._format_mdp_line("nstvout", "5000"),
            self._format_mdp_line("nstfout", "5000"),
            self._format_mdp_line("nstlog", "5000"),
            self._format_mdp_line("nstenergy", "5000"),
            self._format_mdp_line("nstlist", "10"),
            self._format_mdp_line("cutoff-scheme", "Verlet"),
            self._format_mdp_line("ns_type", "grid"),
            self._format_mdp_line("coulombtype", "PME"),
            self._format_mdp_line("rcoulomb", "1.0"),
            self._format_mdp_line("rvdw", "1.0"),
            self._format_mdp_line("pbc", "xyz"),
            self._format_mdp_line("tcoupl", "V-rescale"),
            self._format_mdp_line("tc-grps", "Protein Water_and_ions"),
            self._format_mdp_line("tau_t", "0.1 0.1"),
            self._format_mdp_line("ref_t", "300 300"),
            self._format_mdp_line("pcoupl", "Parrinello-Rahman"),
            self._format_mdp_line("pcoupltype", "isotropic"),
            self._format_mdp_line("tau_p", "2.0"),
            self._format_mdp_line("ref_p", "1.0"),
            self._format_mdp_line("compressibility", "4.5e-5"),
            ""
        ]
        return "\n".join(lines)

    def create_control_panel(self):
        """创建左侧控制面板"""
        # 创建滚动区域容器
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建控制面板widget
        self.control_panel = QWidget()
        self.control_panel_layout = QVBoxLayout(self.control_panel)
        
        # 设置适合的边距和间距
        self.control_panel_layout.setContentsMargins(10, 10, 10, 10)
        self.control_panel_layout.setSpacing(8)
        
        # 创建文件选择区域
        self.create_file_selection_area()
        # 创建模拟类型选择区域
        self.create_simulation_type_group()
        # 创建工作流程状态显示（放在Tab上方）
        self.create_workflow_status_area()
        # 创建选项卡控件
        self.create_tab_widget()
        
        # 将控制面板设置为滚动区域的子widget
        scroll_area.setWidget(self.control_panel)
        
        # 将滚动区域添加到分割器
        self.splitter.addWidget(scroll_area)

    def create_simulation_type_group(self):
        """创建模拟类型选择组"""
        self.sim_type_group = QGroupBox("模拟类型")
        sim_type_layout = QVBoxLayout(self.sim_type_group)
        
        # 模拟类型选择
        self.sim_type_combo = QComboBox()
        sim_types = [
            '溶液模拟',      # 默认选项
            '气相模拟',
            '晶体模拟',
            '膜模拟',
            '真空模拟',
            '自由能计算'
        ]
        self.sim_type_combo.addItems(sim_types)
        self.sim_type_combo.setCurrentText('溶液模拟')  # 设置默认选项
        self.sim_type_combo.currentTextChanged.connect(self.on_simulation_type_changed)
        
        sim_type_layout.addWidget(QLabel("选择模拟类型:"))
        sim_type_layout.addWidget(self.sim_type_combo)
        
        # 工作流程提示
        self.workflow_hint = QLabel()
        self.workflow_hint.setWordWrap(True)
        self.workflow_hint.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        self.update_workflow_hint()
        sim_type_layout.addWidget(self.workflow_hint)
        
        # 模拟类型说明
        self.sim_type_description = QLabel()
        self.sim_type_description.setWordWrap(True)
        self.sim_type_description.setStyleSheet("QLabel { color: #666; font-size: 10px; padding: 5px; background-color: #f9f9f9; border: 1px solid #ddd; border-radius: 3px; }")
        self.update_sim_type_description()
        sim_type_layout.addWidget(self.sim_type_description)
        
        # 推荐参数说明
        self.parameter_recommendations_label = QLabel()
        self.parameter_recommendations_label.setWordWrap(True)
        self.parameter_recommendations_label.setStyleSheet("QLabel { color: #444; font-size: 10px; padding: 8px; background-color: #fff8dc; border: 1px solid #daa520; border-radius: 3px; }")
        self.update_parameter_recommendations(self.sim_type_combo.currentText())
        sim_type_layout.addWidget(self.parameter_recommendations_label)
        
        self.control_panel_layout.addWidget(self.sim_type_group)

    def on_simulation_type_changed(self, sim_type):
        """模拟类型改变时的处理"""
        self.update_workflow_hint()
        self.update_sim_type_description()
        self.update_available_steps()
        # 模拟类型改变时重新计算工作流程进度
        self.update_workflow_status()
        # 自动应用推荐参数
        self.apply_simulation_type_defaults(sim_type)
        # 更新推荐参数说明
        self.update_parameter_recommendations(sim_type)

    def update_workflow_hint(self):
        """更新工作流程提示"""
        sim_type_internal = self.get_simulation_type_internal_name()
        current_lang = self.lang_manager.get_current_language()
        
        if current_lang == 'zh':
            workflow_hints = {
                '气相模拟': '工作流程: 结构文件 → 能量最小化 → NVT平衡 → 生产运行',
                '溶液模拟': '工作流程: PDB → 结构处理 → 加盒子 → 溶剂化 → 加离子 → 能量最小化 → NVT → NPT → 生产运行',
                '晶体模拟': '工作流程: 晶胞结构 → 能量最小化 → NVT平衡 → NPT平衡 → 生产运行',
                '膜模拟': '工作流程: 膜体系结构 → 能量最小化 → NVT平衡 → NPT平衡(半各向同性) → 生产运行',
                '真空模拟': '工作流程: 单分子结构 → 能量最小化 → 生产运行',
                '自由能计算': '工作流程: 系统准备 → 能量最小化 → NVT平衡 → NPT平衡 → 多窗口生产运行'
            }
        else:
            workflow_hints = {
                '气相模拟': 'Workflow: Structure File → Energy Minimization → NVT Equilibration → Production Run',
                '溶液模拟': 'Workflow: PDB → Structure Processing → Add Box → Solvation → Add Ions → Energy Minimization → NVT → NPT → Production Run',
                '晶体模拟': 'Workflow: Crystal Structure → Energy Minimization → NVT Equilibration → NPT Equilibration → Production Run',
                '膜模拟': 'Workflow: Membrane System → Energy Minimization → NVT Equilibration → NPT Equilibration(Semi-isotropic) → Production Run',
                '真空模拟': 'Workflow: Single Molecule → Energy Minimization → Production Run',
                '自由能计算': 'Workflow: System Preparation → Energy Minimization → NVT Equilibration → NPT Equilibration → Multi-window Production Run'
            }
        
        hint = workflow_hints.get(sim_type_internal, workflow_hints['溶液模拟'])
        if hasattr(self, 'workflow_hint'):
            self.workflow_hint.setText(hint)
    
    def update_sim_type_description(self):
        """更新模拟类型说明"""
        sim_type_internal = self.get_simulation_type_internal_name()
        current_lang = self.lang_manager.get_current_language()
        
        if current_lang == 'zh':
            descriptions = {
                '气相模拟': '【适用于】气体分子、小分子群等\n【文件需求】结构文件(.gro/.pdb) + 拓扑文件(.top)\n【特点】周期性边界条件，大盒子系统',
                '溶液模拟': '【适用于】蛋白质、小分子在水中的模拟\n【文件需求】PDB结构 + 力场参数 + 溶剂化配置\n【特点】包含溶剂化、加离子等预处理步骤',
                '晶体模拟': '【适用于】固态材料、晶体结构模拟\n【文件需求】晶胞结构文件 + 晶体力场拓扑\n【特点】高密度系统，可考察弹性、相变',
                '膜模拟': '【适用于】生物膜、膜蛋白体系\n【文件需求】预构建膜结构 + 膜力场参数\n【特点】半各向同性压力耦合，表面张力计算',
                '真空模拟': '【适用于】单分子、小分子群高温模拟\n【文件需求】分子结构 + 力场参数\n【特点】无周期性边界，跨过NPT步骤',
                '自由能计算': '【适用于】热力学积分、伞状采样等\n【文件需求】含λ参数的拓扑 + 多窗口配置\n【特点】多窗口并行计算，需要后处理分析'
            }
        else:
            descriptions = {
                '气相模拟': '【Applications】Gas molecules, small molecule clusters\n【File Requirements】Structure file (.gro/.pdb) + topology file (.top)\n【Features】Periodic boundary conditions, large box systems',
                '溶液模拟': '【Applications】Proteins, small molecules in aqueous solution\n【File Requirements】PDB structure + force field parameters + solvation configuration\n【Features】Includes solvation, ion addition preprocessing steps',
                '晶体模拟': '【Applications】Solid materials, crystal structure simulation\n【File Requirements】Unit cell structure + crystal force field topology\n【Features】High-density systems, elastic properties, phase transitions',
                '膜模拟': '【Applications】Biological membranes, membrane protein systems\n【File Requirements】Pre-built membrane structure + membrane force field parameters\n【Features】Semi-isotropic pressure coupling, surface tension calculations',
                '真空模拟': '【Applications】Single molecules, small clusters high-temperature simulation\n【File Requirements】Molecular structure + force field parameters\n【Features】No periodic boundaries, skip NPT step',
                '自由能计算': '【Applications】Thermodynamic integration, umbrella sampling\n【File Requirements】λ-parameter topology + multi-window configuration\n【Features】Multi-window parallel computation, requires post-processing analysis'
            }
        
        description = descriptions.get(sim_type_internal, descriptions['溶液模拟'])
        if hasattr(self, 'sim_type_description'):
            self.sim_type_description.setText(description)

    def update_available_steps(self):
        """更新可用步骤"""
        pass  # 可以根据需要实现

    def apply_simulation_type_defaults(self, sim_type):
        """根据模拟类型自动应用推荐参数"""
        defaults = self.get_simulation_type_defaults(sim_type)
        
        # 应用默认参数到UI控件
        try:
            # NVT参数
            if hasattr(self, 'nvt_dt_spin'):
                self.nvt_dt_spin.setValue(defaults['nvt']['dt'])
            if hasattr(self, 'nvt_tcoupl_combo'):
                self.nvt_tcoupl_combo.setCurrentText(defaults['nvt']['tcoupl'])
            if hasattr(self, 'nvt_ref_t_edit'):
                self.nvt_ref_t_edit.setText(str(defaults['nvt']['ref_t']))
            if hasattr(self, 'nvt_tc_grps_combo'):
                self.nvt_tc_grps_combo.setCurrentText(defaults['nvt']['tc_grps'])
            if hasattr(self, 'nvt_nstxout_spin'):
                self.nvt_nstxout_spin.setValue(defaults['nvt']['nstxout'])
            if hasattr(self, 'nvt_nstxtcout_spin'):
                self.nvt_nstxtcout_spin.setValue(defaults['nvt']['nstxout-compressed'])
            
            # NPT参数
            if hasattr(self, 'npt_dt_spin'):
                self.npt_dt_spin.setValue(defaults['npt']['dt'])
            if hasattr(self, 'npt_tcoupl_combo'):
                self.npt_tcoupl_combo.setCurrentText(defaults['npt']['tcoupl'])
            if hasattr(self, 'npt_pcoupl_combo'):
                self.npt_pcoupl_combo.setCurrentText(defaults['npt']['pcoupl'])
            if hasattr(self, 'npt_pcoupltype_combo'):
                self.npt_pcoupltype_combo.setCurrentText(defaults['npt']['pcoupltype'])
            if hasattr(self, 'npt_ref_p_spin'):
                self.npt_ref_p_spin.setValue(defaults['npt']['ref_p'])
            if hasattr(self, 'npt_tau_p_spin'):
                self.npt_tau_p_spin.setValue(defaults['npt']['tau_p'])
            if hasattr(self, 'npt_compressibility_edit'):
                self.npt_compressibility_edit.setText(defaults['npt']['compressibility'])
            if hasattr(self, 'npt_nstxout_spin'):
                self.npt_nstxout_spin.setValue(defaults['npt']['nstxout'])
            if hasattr(self, 'npt_nstxtcout_spin'):
                self.npt_nstxtcout_spin.setValue(defaults['npt']['nstxout-compressed'])
            
            # 生产运行参数
            if hasattr(self, 'prod_dt_spin'):
                self.prod_dt_spin.setValue(defaults['production']['dt'])
            if hasattr(self, 'prod_tcoupl_combo'):
                self.prod_tcoupl_combo.setCurrentText(defaults['production']['tcoupl'])
            if hasattr(self, 'prod_pcoupl_combo'):
                self.prod_pcoupl_combo.setCurrentText(defaults['production']['pcoupl'])
            if hasattr(self, 'prod_pcoupltype_combo'):
                self.prod_pcoupltype_combo.setCurrentText(defaults['production']['pcoupltype'])
            if hasattr(self, 'prod_ref_p_spin'):
                self.prod_ref_p_spin.setValue(defaults['production']['ref_p'])
            if hasattr(self, 'prod_tau_p_spin'):
                self.prod_tau_p_spin.setValue(defaults['production']['tau_p'])
            if hasattr(self, 'prod_compressibility_edit'):
                self.prod_compressibility_edit.setText(defaults['production']['compressibility'])
            if hasattr(self, 'prod_nstxout_compressed_spin'):
                self.prod_nstxout_compressed_spin.setValue(defaults['production']['nstxout_compressed'])
            if hasattr(self, 'prod_nstxout_spin'):
                self.prod_nstxout_spin.setValue(defaults['production']['nstxout'])
            if hasattr(self, 'prod_nstxtcout_spin'):
                self.prod_nstxtcout_spin.setValue(defaults['production']['nstxout-compressed'])
                
        except Exception as e:
            print(f"应用默认参数时出错: {e}")

    def get_simulation_type_defaults(self, sim_type):
        """获取模拟类型的默认参数配置"""
        defaults = {
            '气相模拟': {
                'nvt': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'V-rescale',
                    'ref_t': '300',
                    'tc_grps': 'System',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'npt': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'V-rescale',
                    'pcoupl': 'no',  # 气相不使用压力耦合
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'production': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'V-rescale',
                    'pcoupl': 'no',  # 气相不使用压力耦合
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout_compressed': 1000,
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                }
            },
            '溶液模拟': {
                'nvt': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'V-rescale',
                    'ref_t': '300',
                    'tc_grps': 'Protein Water_and_ions',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'npt': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'V-rescale',
                    'pcoupl': 'Parrinello-Rahman',
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'production': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'V-rescale',
                    'pcoupl': 'Parrinello-Rahman',
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout_compressed': 5000,
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                }
            },
            '晶体模拟': {
                'nvt': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'Nose-Hoover',
                    'ref_t': '300',
                    'tc_grps': 'System',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'npt': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'Nose-Hoover',
                    'pcoupl': 'Berendsen',  # 预平衡使用Berendsen
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '0',  # 固定晶格
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'production': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'Nose-Hoover',
                    'pcoupl': 'Parrinello-Rahman',  # 生产运行使用Parrinello-Rahman
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout_compressed': 5000,
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                }
            },
            '膜模拟': {
                'nvt': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'Berendsen',  # 预平衡使用Berendsen
                    'ref_t': '300',
                    'tc_grps': 'Protein Lipid Water_and_ions',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'npt': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'Berendsen',
                    'pcoupl': 'Parrinello-Rahman',
                    'pcoupltype': 'semiisotropic',  # 半各向同性
                    'ref_p': 1.0,  # 将在MDP生成时转换为"1.0 1.0"
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05 4.5e-05',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'production': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'Nose-Hoover',  # 生产运行使用Nose-Hoover
                    'pcoupl': 'Parrinello-Rahman',
                    'pcoupltype': 'semiisotropic',  # 半各向同性
                    'ref_p': 1.0,  # 将在MDP生成时转换为"1.0 1.0"
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05 4.5e-05',
                    'nstxout_compressed': 5000,
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                }
            },
            '真空模拟': {
                'nvt': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'V-rescale',  # 可选或no
                    'ref_t': '300',
                    'tc_grps': 'System',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'npt': {
                    'dt': 0.001,  # 1 fs (但真空模拟不用NPT)
                    'tcoupl': 'no',
                    'pcoupl': 'no',
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'production': {
                    'dt': 0.001,  # 1 fs
                    'tcoupl': 'V-rescale',  # 或no
                    'pcoupl': 'no',
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout_compressed': 1000,
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                }
            },
            '自由能计算': {
                'nvt': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'Nose-Hoover',
                    'ref_t': '300',
                    'tc_grps': 'Protein Water_and_ions',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'npt': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'Nose-Hoover',
                    'pcoupl': 'Parrinello-Rahman',
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                },
                'production': {
                    'dt': 0.002,  # 2 fs
                    'tcoupl': 'Nose-Hoover',
                    'pcoupl': 'Parrinello-Rahman',
                    'pcoupltype': 'isotropic',
                    'ref_p': 1.0,
                    'tau_p': 2.0,
                    'compressibility': '4.5e-05',
                    'nstxout_compressed': 1000,  # 自由能计算需要更频繁的输出
                    'nstxout': 1000,
                    'nstxout-compressed': 1000
                }
            }
        }
        
        return defaults.get(sim_type, defaults['溶液模拟'])  # 默认使用溶液模拟参数

    def update_parameter_recommendations(self, sim_type):
        """更新参数推荐说明"""
        if not hasattr(self, 'parameter_recommendations_label'):
            return
            
        recommendations = {
            '气相模拟': '🔧 推荐参数：\n• 积分步长: 1 fs\n• 温度耦合: V-rescale (300K)\n• 压力耦合: 无 (跳过NPT)\n• 盒子: 立方体，5-10 nm 边长\n• 输出: nstxout-compressed=1000',
            '溶液模拟': '🔧 推荐参数：\n• 积分步长: 2 fs\n• 温度耦合: V-rescale\n• 压力耦合: Parrinello-Rahman (1 bar)\n• 盒子: 十二面体，分子外 1.0 nm\n• 温度组: Protein Water_and_ions',
            '晶体模拟': '🔧 推荐参数：\n• 积分步长: 1 fs\n• 温度耦合: Nose-Hoover\n• 压力耦合: Berendsen→Parrinello-Rahman\n• 盒子: 三斜晶体（保持晶格）\n• 压缩系数: 0 (固定晶格)',
            '膜模拟': '🔧 推荐参数：\n• 积分步长: 2 fs\n• 温度耦合: Berendsen→Nose-Hoover\n• 压力耦合: 半各向同性 Parrinello-Rahman\n• 盒子: 矩形，Z方向多留空间\n• 温度组: Protein Lipid Water_and_ions',
            '真空模拟': '🔧 推荐参数：\n• 积分步长: 1 fs\n• 温度耦合: V-rescale 或 无\n• 压力耦合: 无\n• 盒子: 立方体，3-5 nm\n• 流程: em → md (跳过NPT)',
            '自由能计算': '🔧 推荐参数：\n• 积分步长: 2 fs\n• 温度耦合: Nose-Hoover\n• 压力耦合: Parrinello-Rahman\n• 盒子: 十二面体，1.0 nm\n• 自由能: TI/Umbrella 参数'
        }
        
        recommendation = recommendations.get(sim_type, '请选择模拟类型查看推荐参数')
        self.parameter_recommendations_label.setText(recommendation)

    def create_file_selection_area(self):
        """创建文件选择区域"""
        self.file_group = QGroupBox("文件选择")
        file_layout = QGridLayout()
        # 工作目录选择
        file_layout.addWidget(QLabel("工作目录:"), 0, 0)
        self.working_dir_edit = QLineEdit(os.getcwd())
        self.working_dir_button = QPushButton("浏览")
        file_layout.addWidget(self.working_dir_edit, 0, 1)
        file_layout.addWidget(self.working_dir_button, 0, 2)
        # PDB文件选择
        file_layout.addWidget(QLabel("PDB文件:"), 1, 0)
        self.pdb_file_edit = QLineEdit()
        self.pdb_file_button = QPushButton("浏览")
        file_layout.addWidget(self.pdb_file_edit, 1, 1)
        file_layout.addWidget(self.pdb_file_button, 1, 2)
        # GRO文件选择
        file_layout.addWidget(QLabel("GRO文件:"), 2, 0)
        self.gro_file_edit = QLineEdit()
        self.gro_file_button = QPushButton("浏览")
        file_layout.addWidget(self.gro_file_edit, 2, 1)
        file_layout.addWidget(self.gro_file_button, 2, 2)
        # TOP文件选择
        file_layout.addWidget(QLabel("TOP文件:"), 3, 0)
        self.top_file_edit = QLineEdit()
        self.top_file_button = QPushButton("浏览")
        file_layout.addWidget(self.top_file_edit, 3, 1)
        file_layout.addWidget(self.top_file_button, 3, 2)
        # ITP文件选择 (可选)
        file_layout.addWidget(QLabel("ITP文件 (可选):"), 4, 0)
        self.itp_file_edit = QLineEdit()
        self.itp_file_button = QPushButton("浏览")
        file_layout.addWidget(self.itp_file_edit, 4, 1)
        file_layout.addWidget(self.itp_file_button, 4, 2)

        # 自动填充按钮
        self.auto_fill_button = QPushButton("自动填充文件")
        self.auto_fill_button.setStyleSheet(self._btn_tool)
        file_layout.addWidget(self.auto_fill_button, 5, 1)

        self.file_group.setLayout(file_layout)
        self.control_panel_layout.addWidget(self.file_group)

    def create_workflow_status_area(self):
        """创建工作流程状态显示区域"""
        self.workflow_group = QGroupBox("工作流程状态")
        workflow_layout = QVBoxLayout()

        # 步骤指示器（用 QLabel 模拟步骤条）
        self.workflow_steps_widget = QWidget()
        steps_layout = QHBoxLayout(self.workflow_steps_widget)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(2)
        self.workflow_step_labels = []
        step_names = ['EM', 'NVT', 'NPT', 'MD']
        for i, name in enumerate(step_names):
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumHeight(28)
            lbl.setStyleSheet(
                "QLabel { background-color: #e0e0e0; color: #888; border-radius: 4px; "
                "font-size: 10px; font-weight: bold; padding: 2px; }"
            )
            self.workflow_step_labels.append(lbl)
            steps_layout.addWidget(lbl)
        workflow_layout.addWidget(self.workflow_steps_widget)

        # 进度条
        self.workflow_progress_bar = QProgressBar()
        self.workflow_progress_bar.setRange(0, 4)
        self.workflow_progress_bar.setValue(0)
        self.workflow_progress_bar.setTextVisible(True)
        self.workflow_progress_bar.setFormat("%v/4 步骤完成")
        self.workflow_progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #ccc; border-radius: 4px; text-align: center; height: 18px; }"
            "QProgressBar::chunk { background-color: #4CAF50; border-radius: 3px; }"
        )
        workflow_layout.addWidget(self.workflow_progress_bar)

        # 状态文字
        self.workflow_status_label = QLabel("请先运行能量最小化")
        self.workflow_status_label.setStyleSheet("QLabel { color: #666; font-size: 11px; }")
        workflow_layout.addWidget(self.workflow_status_label)

        self.workflow_group.setLayout(workflow_layout)
        self.control_panel_layout.addWidget(self.workflow_group)

    def on_tab_changed(self, index):
        """标签页切换时的处理"""
        self.update_current_mdp_preview()

    def select_mdp_file(self):
        """选择MDP文件并在预览区域显示其内容"""
        working_dir = self.working_dir_edit.text() if hasattr(self, 'working_dir_edit') else "."
        mdp_file, _ = QFileDialog.getOpenFileName(
            self, "选择MDP文件", working_dir, "MDP Files (*.mdp);;All Files (*)"
        )
        if mdp_file:
            try:
                with open(mdp_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.mdp_preview_text.setPlainText(content)
                QMessageBox.information(self, "成功", f"已加载MDP文件: {os.path.basename(mdp_file)}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法读取MDP文件:\n{str(e)}")

    def save_current_mdp(self):
        """保存当前MDP文件"""
        current_tab_text = ""
        if hasattr(self, 'sim_run_tabs'):
            idx = self.sim_run_tabs.currentIndex()
            if idx >= 0:
                current_tab_text = self.sim_run_tabs.tabText(idx)

        if "能量最小化" in current_tab_text:
            filename = "em.mdp"
            self.current_step_type = "minimization"
        elif "NVT" in current_tab_text:
            filename = "nvt.mdp"
            self.current_step_type = "nvt"
        elif "NPT" in current_tab_text:
            filename = "npt.mdp"
            self.current_step_type = "npt"
        elif "生产运行" in current_tab_text:
            filename = "md.mdp"
            self.current_step_type = "production"
        else:
            filename, _ = QFileDialog.getSaveFileName(self, "保存MDP文件", "", "MDP Files (*.mdp)")
            if not filename:
                return

        mdp_content = self.mdp_preview_text.toPlainText()
        if not mdp_content.strip():
            if "能量最小化" in current_tab_text:
                mdp_content = self.generate_minimization_mdp_content()
            elif "NVT" in current_tab_text:
                mdp_content = self.generate_nvt_mdp_content()
            elif "NPT" in current_tab_text:
                mdp_content = self.generate_npt_mdp_content()
            elif "生产运行" in current_tab_text:
                self.generate_production_mdp()
                mdp_content = self.mdp_preview_text.toPlainText()
            else:
                mdp_content = "; 请先选择一个步骤标签页"

        try:
            if os.path.exists(filename):
                reply = QMessageBox.question(
                    self, "文件已存在", f"文件 {filename} 已存在，是否覆盖？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(mdp_content)
            self.mdp_preview_text.setPlainText(mdp_content)
            self.output_tab_widget.setCurrentWidget(self.mdp_preview_tab)
            QMessageBox.information(self, "成功", f"MDP文件已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存MDP文件失败: {str(e)}")

    def copy_current_command(self):
        """复制当前命令到剪贴板"""
        command = self.cmd_preview_text.toPlainText()
        clipboard = QApplication.clipboard()
        clipboard.setText(command)
        QMessageBox.information(self, "成功", "命令已复制到剪贴板")

    def save_current_command(self):
        """保存当前命令为脚本文件"""
        command = self.cmd_preview_text.toPlainText()
        if not command.strip():
            QMessageBox.warning(self, "警告", "没有可保存的命令")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "保存脚本文件", "", "Shell Scripts (*.sh);;All Files (*)")
        if not filename:
            return
        try:
            script_content = f"#!/bin/bash\n# GROMACS命令脚本\n# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n{command}\n"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(script_content)
            QMessageBox.information(self, "成功", f"脚本文件已保存到: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存脚本文件失败: {str(e)}")

    def _format_mdp_line(self, param, value):
        """格式化MDP参数行, 添加注释"""
        lang = self.lang_manager.get_current_language()
        comment = PARAM_COMMENTS.get(param, {}).get(lang, "")
        return f"{param:<15} = {value:<10} ; {comment}" if comment else f"{param:<15} = {value}"

    def generate_current_command(self):
        """生成当前命令"""
        self.on_generate_command_clicked()

    def execute_current_command(self):
        """执行当前命令"""
        self.on_execute_command_clicked()

    def update_current_mdp_preview(self):
        """更新当前MDP预览"""
        current_tab_text = ""
        if hasattr(self, 'sim_run_tabs'):
            idx = self.sim_run_tabs.currentIndex()
            if idx >= 0:
                current_tab_text = self.sim_run_tabs.tabText(idx)

        mdp_content = ""
        if "能量最小化" in current_tab_text:
            mdp_content = self.generate_minimization_mdp_content()
        elif "NVT" in current_tab_text:
            mdp_content = self.generate_nvt_mdp_content()
        elif "NPT" in current_tab_text:
            mdp_content = self.generate_npt_mdp_content()
        elif "生产运行" in current_tab_text:
            self.generate_production_mdp()
            return
        else:
            mdp_content = "; 请先选择一个步骤标签页"

        if hasattr(self, 'mdp_preview_text'):
            self.mdp_preview_text.setPlainText(mdp_content)

    def create_tab_widget(self):
        """创建选项卡控件（分组布局）"""
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # === 第一组：结构准备 ===
        self.structure_prep_widget = QWidget()
        prep_layout = QVBoxLayout(self.structure_prep_widget)
        prep_layout.setContentsMargins(4, 4, 4, 4)
        self.structure_prep_tabs = QTabWidget()
        self.structure_prep_tabs.setDocumentMode(True)
        self.create_center_alignment_tab()
        self.create_pdb2gmx_tab()
        self.create_solvation_tab()
        prep_layout.addWidget(self.structure_prep_tabs)
        self.tab_widget.addTab(self.structure_prep_widget, "结构准备")

        # === 第二组：模拟运行 ===
        self.sim_run_widget = QWidget()
        run_layout = QVBoxLayout(self.sim_run_widget)
        run_layout.setContentsMargins(4, 4, 4, 4)
        self.sim_run_tabs = QTabWidget()
        self.sim_run_tabs.setDocumentMode(True)
        self.create_energy_minimization_tab()
        self.create_nvt_equilibration_tab()
        self.create_npt_equilibration_tab()
        self.create_production_md_tab()
        run_layout.addWidget(self.sim_run_tabs)
        self.tab_widget.addTab(self.sim_run_widget, "模拟运行")

        # === 第三组：高级工具 ===
        self.tools_widget = QWidget()
        tools_layout = QVBoxLayout(self.tools_widget)
        tools_layout.setContentsMargins(4, 4, 4, 4)
        self.tools_tabs = QTabWidget()
        self.tools_tabs.setDocumentMode(True)
        self.create_mdp_search_tab()
        tools_layout.addWidget(self.tools_tabs)
        self.tab_widget.addTab(self.tools_widget, "高级工具")

        self.control_panel_layout.addWidget(self.tab_widget)

    def create_pbc_group(self, prefix):
        """创建PBC设置组 - 通用方法"""
        pbc_group = QGroupBox("周期性边界条件(PBC)设置")
        pbc_layout = QGridLayout(pbc_group)
        # PBC类型选择
        pbc_layout.addWidget(QLabel("PBC类型 (pbc):"), 0, 0)
        pbc_combo = QComboBox()

        pbc_combo.setObjectName(f"{prefix}_pbc_combo")
        pbc_combo.addItems(['xyz', 'xy', 'no'])
        pbc_combo.setCurrentText('xyz')  # 默认值
        pbc_combo.currentTextChanged.connect(lambda text: self.on_pbc_changed(prefix, text))
        pbc_layout.addWidget(pbc_combo, 0, 1)
        # 截断方案
        pbc_layout.addWidget(QLabel("截断方案 (cutoff-scheme):"), 1, 0)
        cutoff_scheme_combo = QComboBox()
        cutoff_scheme_combo.setObjectName(f"{prefix}_cutoff_scheme_combo")
        cutoff_scheme_combo.addItems(['Verlet', 'group'])
        cutoff_scheme_combo.setCurrentText('Verlet')
        cutoff_scheme_combo.currentTextChanged.connect(lambda text: self.on_cutoff_scheme_changed(prefix, text))
        pbc_layout.addWidget(cutoff_scheme_combo, 1, 1)
        # 邻居列表更新频率
        pbc_layout.addWidget(QLabel("邻居列表更新 (nstlist):"), 2, 0)
        nstlist_spinbox = QSpinBox()
        nstlist_spinbox.setObjectName(f"{prefix}_nstlist_spinbox")
        nstlist_spinbox.setRange(0, 50)
        nstlist_spinbox.setValue(10)
        pbc_layout.addWidget(nstlist_spinbox, 2, 1)
        # 邻居搜索半径
        pbc_layout.addWidget(QLabel("邻居搜索半径 (rlist, nm):"), 3, 0)
        rlist_spinbox = QDoubleSpinBox()
        rlist_spinbox.setObjectName(f"{prefix}_rlist_spinbox")
        rlist_spinbox.setRange(0.0, 3.0)
        rlist_spinbox.setValue(1.0)
        rlist_spinbox.setDecimals(2)
        rlist_spinbox.setSingleStep(0.1)
        pbc_layout.addWidget(rlist_spinbox, 3, 1)
        # 添加工具提示
        pbc_combo.setToolTip("xyz:三维周期性边界(常规模拟)\nxy:二维周期性边界(膜蛋白)\nno:无周期性边界(气相模拟)")
        cutoff_scheme_combo.setToolTip("Verlet:推荐方案,支持GPU加速\ngroup:传统方案,CPU计算")
        nstlist_spinbox.setToolTip("邻居列表更新频率,pbc=no时应设为0")
        rlist_spinbox.setToolTip("邻居搜索半径,pbc=no时应设为0")
        # 保存控件引用到实例
        setattr(self, f"{prefix}_pbc_combo", pbc_combo)
        setattr(self, f"{prefix}_cutoff_scheme_combo", cutoff_scheme_combo)
        setattr(self, f"{prefix}_nstlist_spinbox", nstlist_spinbox)
        setattr(self, f"{prefix}_rlist_spinbox", rlist_spinbox)
        return pbc_group

    def on_pbc_changed(self, prefix, pbc_type):
        """PBC类型改变时的参数自动调整"""
        nstlist_spinbox = getattr(self, f"{prefix}_nstlist_spinbox")
        rlist_spinbox = getattr(self, f"{prefix}_rlist_spinbox")
        cutoff_scheme_combo = getattr(self, f"{prefix}_cutoff_scheme_combo")
        if pbc_type == 'no':
            # 气相模拟参数
            nstlist_spinbox.setValue(0)
            rlist_spinbox.setValue(0.0)
            # cutoff_scheme_combo.setCurrentText('Verlet')  # 气相也推荐Verlet，但不强制改变
            # 禁用不相关参数
            nstlist_spinbox.setEnabled(False)
            rlist_spinbox.setEnabled(False)
            # 提示用户
            self.show_pbc_info("已切换到气相模拟模式：nstlist=0, rlist=0")
        else:
            # 恢复周期性边界参数
            nstlist_spinbox.setValue(10)
            rlist_spinbox.setValue(1.0)
            # 启用参数
            nstlist_spinbox.setEnabled(True)
            rlist_spinbox.setEnabled(True)
            # 提示用户
            pbc_info = {
                'xyz': '三维周期性边界：适用于体相溶液模拟',
                'xy': '二维周期性边界：适用于膜蛋白/表面模拟'
            }
            self.show_pbc_info(pbc_info.get(pbc_type, ''))

    def on_cutoff_scheme_changed(self, prefix, scheme):
        """截断方案改变时的建议"""
        nstlist_spinbox = getattr(self, f"{prefix}_nstlist_spinbox")
        if scheme == 'Verlet':
            nstlist_spinbox.setValue(10)
            self.show_pbc_info("Verlet方案：支持GPU加速，建议nstlist=10-20")
        elif scheme == 'group':
            nstlist_spinbox.setValue(5)
            self.show_pbc_info("Group方案：传统CPU方案，建议nstlist=5-10")

    def show_pbc_info(self, message):
        """显示PBC相关信息"""
        # 在状态栏或信息标签中显示
        if hasattr(self, 'pbc_info_label'):
            self.pbc_info_label.setText(message)
        else:
            # 如果没有专门的信息标签，可以打印到日志或使用状态栏
            # self.statusBar().showMessage(message, 5000) # 需要启用状态栏
            print(f"PBC Info: {message}") # 或者简单打印

    def create_parameter_assistant_tab(self):
        """创建参数助手选项卡"""
        self.param_assistant_tab = QWidget()
        layout = QVBoxLayout(self.param_assistant_tab)
        
        # 添加说明
        info_label = QLabel("参数助手：可调整时间步长、nsteps、温度/压力耦合等参数，并实时生成MDP片段")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        layout.addWidget(info_label)
        
        # 参数调整区域
        param_group = QGroupBox("MDP参数调整")
        param_layout = QGridLayout(param_group)
        
        # 时间步长
        param_layout.addWidget(QLabel("时间步长 (dt):"), 0, 0)
        self.param_dt_spin = QDoubleSpinBox()
        self.param_dt_spin.setRange(0.001, 0.01)
        self.param_dt_spin.setValue(0.002)
        self.param_dt_spin.setSuffix(" ps")
        param_layout.addWidget(self.param_dt_spin, 0, 1)
        
        # 步数
        param_layout.addWidget(QLabel("步数 (nsteps):"), 1, 0)
        self.param_nsteps_spin = QSpinBox()
        self.param_nsteps_spin.setRange(1000, 10000000)
        self.param_nsteps_spin.setValue(50000)
        param_layout.addWidget(self.param_nsteps_spin, 1, 1)
        
        # 温度耦合
        param_layout.addWidget(QLabel("温度耦合方法 (tcoupl):"), 2, 0)
        self.param_tcoupl_combo = QComboBox()
        self.param_tcoupl_combo.addItems(['V-rescale', 'Berendsen', 'nose-hoover'])
        self.param_tcoupl_combo.setCurrentText('V-rescale')
        param_layout.addWidget(self.param_tcoupl_combo, 2, 1)
        
        # 压力耦合
        param_layout.addWidget(QLabel("压力耦合方法 (pcoupl):"), 3, 0)
        self.param_pcoupl_combo = QComboBox()
        self.param_pcoupl_combo.addItems(['no', 'Berendsen', 'Parrinello-Rahman', 'c-rescale'])
        self.param_pcoupl_combo.setCurrentText('Berendsen')
        param_layout.addWidget(self.param_pcoupl_combo, 3, 1)
        
        # 温度值
        param_layout.addWidget(QLabel("参考温度 (ref_t):"), 4, 0)
        self.param_ref_t_edit = QLineEdit("300")
        param_layout.addWidget(self.param_ref_t_edit, 4, 1)
        
        # 压力值
        param_layout.addWidget(QLabel("参考压力 (ref_p):"), 5, 0)
        self.param_ref_p_spin = QDoubleSpinBox()
        self.param_ref_p_spin.setRange(0, 1000)
        self.param_ref_p_spin.setValue(1.0)
        self.param_ref_p_spin.setSuffix(" bar")
        param_layout.addWidget(self.param_ref_p_spin, 5, 1)
        
        layout.addWidget(param_group)
        
        # 实时预览区域
        preview_group = QGroupBox("MDP片段预览")
        preview_layout = QVBoxLayout(preview_group)
        self.param_mdp_preview = QPlainTextEdit()
        self.param_mdp_preview.setReadOnly(True)
        self.param_mdp_preview.setMaximumHeight(200)
        preview_layout.addWidget(self.param_mdp_preview)
        layout.addWidget(preview_group)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        self.update_mdp_btn = QPushButton("更新MDP片段")
        self.apply_to_current_btn = QPushButton("应用到当前步骤")
        button_layout.addWidget(self.update_mdp_btn)
        button_layout.addWidget(self.apply_to_current_btn)
        layout.addLayout(button_layout)
        
        # 连接信号
        self.param_dt_spin.valueChanged.connect(self.update_param_mdp_preview)
        self.param_nsteps_spin.valueChanged.connect(self.update_param_mdp_preview)
        self.param_tcoupl_combo.currentTextChanged.connect(self.update_param_mdp_preview)
        self.param_pcoupl_combo.currentTextChanged.connect(self.update_param_mdp_preview)
        self.param_ref_t_edit.textChanged.connect(self.update_param_mdp_preview)
        self.param_ref_p_spin.valueChanged.connect(self.update_param_mdp_preview)
        self.update_mdp_btn.clicked.connect(self.update_param_mdp_preview)
        self.apply_to_current_btn.clicked.connect(self.apply_param_to_current)
        
        # 初始化预览
        self.update_param_mdp_preview()
        
        self.tools_tabs.addTab(self.param_assistant_tab, "参数助手")
        
    def update_param_mdp_preview(self):
        """更新参数助手的MDP片段预览"""
        # 计算模拟时长
        dt = self.param_dt_spin.value()
        nsteps = self.param_nsteps_spin.value()
        simulation_time_ps = dt * nsteps
        if simulation_time_ps >= 1000:
            simulation_time_ns = simulation_time_ps / 1000.0
            time_display = f"{simulation_time_ns:.2f} ns"
        else:
            time_display = f"{simulation_time_ps:.1f} ps"
        
        # 生成MDP片段
        mdp_fragment = f"""; 参数助手生成的MDP片段
; 时间步长: {dt} ps
; 步数: {nsteps}
; 模拟时长: {time_display}
; 温度耦合: {self.param_tcoupl_combo.currentText()}
; 压力耦合: {self.param_pcoupl_combo.currentText()}

dt                  = {self.param_dt_spin.value()}
nsteps              = {self.param_nsteps_spin.value()}
tcoupl              = {self.param_tcoupl_combo.currentText()}
tc-grps             = System
tau_t               = 1.0
ref_t               = {self.param_ref_t_edit.text()}
pcoupl              = {self.param_pcoupl_combo.currentText()}
pcoupltype          = isotropic
tau_p               = 1.0
ref_p               = {self.param_ref_p_spin.value()}
compressibility     = 4.5e-5
"""
        
        self.param_mdp_preview.setPlainText(mdp_fragment)
        
    def apply_param_to_current(self):
        """将参数应用到当前步骤"""
        # 获取当前活跃的子标签页文本（适配嵌套Tab结构）
        current_tab_text = ""
        if hasattr(self, 'sim_run_tabs'):
            idx = self.sim_run_tabs.currentIndex()
            if idx >= 0:
                current_tab_text = self.sim_run_tabs.tabText(idx)
        
        # 根据当前标签页设置对应的参数
        if "能量最小化" in current_tab_text:
            # 应用到能量最小化步骤
            pass
        elif "NVT" in current_tab_text:
            # 应用到NVT步骤
            self.nvt_dt_spin.setValue(self.param_dt_spin.value())
            self.nvt_nsteps_spin.setValue(self.param_nsteps_spin.value())
            self.nvt_tcoupl_combo.setCurrentText(self.param_tcoupl_combo.currentText())
            self.nvt_ref_t_edit.setText(self.param_ref_t_edit.text())
        elif "NPT" in current_tab_text:
            # 应用到NPT步骤
            self.npt_dt_spin.setValue(self.param_dt_spin.value())
            self.npt_nsteps_spin.setValue(self.param_nsteps_spin.value())
            self.npt_tcoupl_combo.setCurrentText(self.param_tcoupl_combo.currentText())
            self.npt_pcoupl_combo.setCurrentText(self.param_pcoupl_combo.currentText())
            self.npt_ref_t_edit.setText(self.param_ref_t_edit.text())
            self.npt_ref_p_spin.setValue(self.param_ref_p_spin.value())
        elif "生产运行" in current_tab_text:
            # 应用到生产运行步骤
            self.prod_dt_spin.setValue(self.param_dt_spin.value())
            self.prod_nsteps_spin.setValue(self.param_nsteps_spin.value())
            self.prod_tcoupl_combo.setCurrentText(self.param_tcoupl_combo.currentText())
            self.prod_pcoupl_combo.setCurrentText(self.param_pcoupl_combo.currentText())
            self.prod_ref_t_edit.setText(self.param_ref_t_edit.text())
            self.prod_ref_p_spin.setValue(self.param_ref_p_spin.value())
        else:
            QMessageBox.information(self, "提示", "请先选择一个步骤标签页（能量最小化/NVT/NPT/生产运行）")
            return
            
        QMessageBox.information(self, "成功", "参数已应用到当前步骤")

    def create_simulation_presets(self, layout):
        """创建模拟预设按钮组"""
        presets_group = QGroupBox("常用预设")
        presets_layout = QHBoxLayout(presets_group)
        # 预设按钮
        gas_preset_btn = QPushButton("气相模拟")
        solution_preset_btn = QPushButton("溶液模拟")
        membrane_preset_btn = QPushButton("膜蛋白模拟")
        # 连接事件
        gas_preset_btn.clicked.connect(self.apply_gas_phase_preset)
        solution_preset_btn.clicked.connect(self.apply_solution_preset)
        membrane_preset_btn.clicked.connect(self.apply_membrane_preset)
        presets_layout.addWidget(gas_preset_btn)
        presets_layout.addWidget(solution_preset_btn)
        presets_layout.addWidget(membrane_preset_btn)
        layout.addWidget(presets_group)

    def apply_gas_phase_preset(self):
        """应用气相模拟预设"""
        # 所有选项卡的PBC设置
        for prefix in ['em', 'nvt', 'npt', 'md']:
            if hasattr(self, f'{prefix}_pbc_combo'):
                getattr(self, f'{prefix}_pbc_combo').setCurrentText('no')
                # 不强制改变 cutoff-scheme
                getattr(self, f'{prefix}_nstlist_spinbox').setValue(0)
                getattr(self, f'{prefix}_rlist_spinbox').setValue(0.0)
        QMessageBox.information(self, "预设应用", "已应用气相模拟预设参数")

    def apply_solution_preset(self):
        """应用溶液模拟预设"""
        for prefix in ['em', 'nvt', 'npt', 'md']:
            if hasattr(self, f'{prefix}_pbc_combo'):
                getattr(self, f'{prefix}_pbc_combo').setCurrentText('xyz')
                getattr(self, f'{prefix}_cutoff_scheme_combo').setCurrentText('Verlet')
                getattr(self, f'{prefix}_nstlist_spinbox').setValue(10)
                getattr(self, f'{prefix}_rlist_spinbox').setValue(1.0)
        QMessageBox.information(self, "预设应用", "已应用溶液模拟预设参数")

    def apply_membrane_preset(self):
        """应用膜蛋白模拟预设"""
        for prefix in ['em', 'nvt', 'npt', 'md']:
            if hasattr(self, f'{prefix}_pbc_combo'):
                getattr(self, f'{prefix}_pbc_combo').setCurrentText('xy')
                getattr(self, f'{prefix}_cutoff_scheme_combo').setCurrentText('Verlet')
                getattr(self, f'{prefix}_nstlist_spinbox').setValue(10)
                getattr(self, f'{prefix}_rlist_spinbox').setValue(1.2)
        QMessageBox.information(self, "预设应用", "已应用膜蛋白模拟预设参数")

    def create_center_alignment_tab(self):
        """创建结构操作选项卡（加强版）"""
        self.structure_tabs = QTabWidget()

        # 创建加强版标签页
        self.create_enhanced_structure_tabs()

        self.structure_prep_tabs.addTab(self.structure_tabs, "结构操作")
        # self.tab_widget.addTab(self.solvation_tab, "溶剂化")

    def create_enhanced_structure_tabs(self):
        """创建加强版结构操作标签页"""
        self.structure_tabs.addTab(self.create_structure_center_tab(), "结构居中对齐")
        self.structure_tabs.addTab(self.create_structure_group_tab(), "结构分组")
        self.structure_tabs.addTab(self.create_structure_clean_tab(), "结构清理修复")
        self.structure_tabs.addTab(self.create_format_convert_tab(), "格式转换")
        self.structure_tabs.addTab(self.create_structure_analysis_tab(), "结构分析")
        self.structure_tabs.addTab(self.create_structure_modify_tab(), "结构修改")

    def create_solvation_tab(self):
        """创建溶剂化选项卡 - 溶液模拟专用"""
        self.solvation_tab = QWidget()
        layout = QVBoxLayout(self.solvation_tab)
        
        # 1. 顶部说明区域
        info_group = self.create_solvation_info_group()
        layout.addWidget(info_group)
        
        # 2. 流程步骤区域（标签页形式）
        self.solvation_steps_tabs = QTabWidget()
        
        # 步骤1: 定义模拟盒子
        self.solvation_steps_tabs.addTab(self.create_box_definition_tab(), "步骤1: 定义盒子")
        # 步骤2: 添加溶剂
        self.solvation_steps_tabs.addTab(self.create_solvation_tab_content(), "步骤2: 添加溶剂") 
        # 步骤3: 添加离子
        self.solvation_steps_tabs.addTab(self.create_ion_addition_tab(), "步骤3: 添加离子")
        # 步骤4: 检查体系
        self.solvation_steps_tabs.addTab(self.create_system_check_tab(), "步骤4: 体系检查")
        
        layout.addWidget(self.solvation_steps_tabs)
        
        # 3. 底部控制区域
        control_group = self.create_solvation_control_group()
        layout.addWidget(control_group)
        
        self.structure_prep_tabs.addTab(self.solvation_tab, "溶剂化")

    def create_solvation_info_group(self):
        """创建溶剂化说明信息组"""
        info_group = QGroupBox("溶剂化流程说明")
        info_layout = QVBoxLayout(info_group)
        
        info_text = """
溶液模拟溶剂化四步流程：
1. 定义模拟盒子 - 设置盒子类型和边界距离
2. 添加溶剂 - 使用水模型填充盒子
3. 添加离子 - 中和电荷并设置离子浓度
4. 体系检查 - 验证体系完整性和参数

新手提示：
- 建议按顺序执行每个步骤
- 每步执行后检查输出文件是否正确生成
- 注意保持拓扑文件(topol.top)的一致性
- 请在'水模型与力场'中选择与你力场匹配的水模型，以确保拓扑一致性
- 请在 pdb2gmx 步骤中选择水模型，以确保拓扑一致性
        """
        
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { background-color: #f0f8ff; padding: 10px; border: 1px solid #cce6ff; border-radius: 5px; }")
        info_layout.addWidget(info_label)
        
        return info_group

    def create_box_definition_tab(self):
        """创建盒子定义选项卡"""
        tab = QWidget()
        layout = QGridLayout(tab)
        
        # 输入文件
        layout.addWidget(QLabel("输入结构文件:"), 0, 0)
        self.box_input_file = QLineEdit()
        self.box_input_file.setPlaceholderText("processed.gro 或其他结构文件")
        btn_box_input = QPushButton("浏览")
        btn_box_input.clicked.connect(lambda: self.browse_structure_file(self.box_input_file, "选择输入结构文件", "GRO Files (*.gro);;PDB Files (*.pdb);;All Files (*)"))
        layout.addWidget(self.box_input_file, 0, 1)
        layout.addWidget(btn_box_input, 0, 2)
        
        # 输出文件
        layout.addWidget(QLabel("输出盒子文件:"), 1, 0)
        self.box_output_file = QLineEdit()
        self.box_output_file.setPlaceholderText("newbox.gro")
        btn_box_output = QPushButton("保存")
        btn_box_output.clicked.connect(lambda: self.save_structure_file(self.box_output_file, "保存盒子文件", "GRO Files (*.gro);;All Files (*)"))
        layout.addWidget(self.box_output_file, 1, 1)
        layout.addWidget(btn_box_output, 1, 2)
        
        # 盒子类型
        layout.addWidget(QLabel("盒子类型:"), 2, 0)
        self.box_type_combo = QComboBox()
        self.box_type_combo.addItems(["立方体 (cubic)", "十二面体 (dodecahedron)", "八面体 (octahedron)", "三斜晶系 (triclinic)"])
        self.box_type_combo.setCurrentText("十二面体 (dodecahedron)")
        layout.addWidget(self.box_type_combo, 2, 1, 1, 2)
        
        # 边界距离
        layout.addWidget(QLabel("边界距离 (nm):"), 3, 0)
        self.box_distance_spin = QDoubleSpinBox()
        self.box_distance_spin.setRange(0.1, 5.0)
        self.box_distance_spin.setValue(1.0)
        self.box_distance_spin.setSingleStep(0.1)
        layout.addWidget(self.box_distance_spin, 3, 1, 1, 2)
        
        # 居中选项
        self.box_center_check = QCheckBox("将分子居中到盒子中心")
        self.box_center_check.setChecked(True)
        layout.addWidget(self.box_center_check, 4, 0, 1, 3)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        self.generate_box_cmd_btn = QPushButton("生成命令")
        self.execute_box_cmd_btn = QPushButton("执行命令")
        self.generate_box_cmd_btn.clicked.connect(self.generate_box_command)
        self.execute_box_cmd_btn.clicked.connect(self.execute_box_definition)
        btn_layout.addWidget(self.generate_box_cmd_btn)
        btn_layout.addWidget(self.execute_box_cmd_btn)
        layout.addLayout(btn_layout, 5, 0, 1, 3)
        
        return tab

    def create_solvation_tab_content(self):
        """创建溶剂化选项卡内容"""
        tab = QWidget()
        layout = QGridLayout(tab)
        
        # 输入文件
        layout.addWidget(QLabel("输入盒子文件:"), 0, 0)
        self.solvate_input_file = QLineEdit()
        self.solvate_input_file.setPlaceholderText("newbox.gro")
        btn_solvate_input = QPushButton("浏览")
        btn_solvate_input.clicked.connect(lambda: self.browse_structure_file(self.solvate_input_file, "选择输入盒子文件", "GRO Files (*.gro);;All Files (*)"))
        layout.addWidget(self.solvate_input_file, 0, 1)
        layout.addWidget(btn_solvate_input, 0, 2)
        
        # 输出文件
        layout.addWidget(QLabel("输出溶剂化文件:"), 1, 0)
        self.solvate_output_file = QLineEdit()
        self.solvate_output_file.setPlaceholderText("solvated.gro")
        btn_solvate_output = QPushButton("保存")
        btn_solvate_output.clicked.connect(lambda: self.save_structure_file(self.solvate_output_file, "保存溶剂化文件", "GRO Files (*.gro);;All Files (*)"))
        layout.addWidget(self.solvate_output_file, 1, 1)
        layout.addWidget(btn_solvate_output, 1, 2)
        
        # 水模型选择
        layout.addWidget(QLabel("水模型:"), 2, 0)
        self.water_model_combo = QComboBox()
        self.water_model_combo.addItems(["SPC", "SPC/E", "TIP3P", "TIP4P", "TIP5P", "spc216"])
        self.water_model_combo.setCurrentText("spc216")
        layout.addWidget(self.water_model_combo, 2, 1, 1, 2)
        
        # 添加提示文本
        water_model_tip = QLabel("水模型已在 pdb2gmx 步骤中指定，请确保此处的水结构文件（如 spc216.gro）与之前选择的水模型匹配。")
        water_model_tip.setWordWrap(True)
        water_model_tip.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        layout.addWidget(water_model_tip, 3, 0, 1, 3)
        
        # 水分子结构文件
        layout.addWidget(QLabel("水分子结构文件:"), 4, 0)
        self.water_structure_file = QLineEdit()
        self.water_structure_file.setText("spc216.gro")
        btn_water_structure = QPushButton("浏览")
        btn_water_structure.clicked.connect(lambda: self.browse_structure_file(self.water_structure_file, "选择水分子结构文件", "GRO Files (*.gro);;All Files (*)"))
        layout.addWidget(self.water_structure_file, 4, 1)
        layout.addWidget(btn_water_structure, 4, 2)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        self.generate_solvate_cmd_btn = QPushButton("生成命令")
        self.execute_solvate_cmd_btn = QPushButton("执行命令")
        self.generate_solvate_cmd_btn.clicked.connect(self.generate_solvate_command)
        self.execute_solvate_cmd_btn.clicked.connect(self.execute_solvation)
        btn_layout.addWidget(self.generate_solvate_cmd_btn)
        btn_layout.addWidget(self.execute_solvate_cmd_btn)
        layout.addLayout(btn_layout, 5, 0, 1, 3)
        
        return tab

    def create_ion_addition_tab(self):
        """创建离子添加选项卡"""
        tab = QWidget()
        layout = QGridLayout(tab)
        
        # 输入文件
        layout.addWidget(QLabel("输入溶剂化文件:"), 0, 0)
        self.ion_input_file = QLineEdit()
        self.ion_input_file.setPlaceholderText("solvated.gro")
        btn_ion_input = QPushButton("浏览")
        btn_ion_input.clicked.connect(lambda: self.browse_structure_file(self.ion_input_file, "选择输入溶剂化文件", "GRO Files (*.gro);;All Files (*)"))
        layout.addWidget(self.ion_input_file, 0, 1)
        layout.addWidget(btn_ion_input, 0, 2)
        
        # 输出文件
        layout.addWidget(QLabel("输出离子化文件:"), 1, 0)
        self.ion_output_file = QLineEdit()
        self.ion_output_file.setPlaceholderText("ionized.gro")
        btn_ion_output = QPushButton("保存")
        btn_ion_output.clicked.connect(lambda: self.save_structure_file(self.ion_output_file, "保存离子化文件", "GRO Files (*.gro);;All Files (*)"))
        layout.addWidget(self.ion_output_file, 1, 1)
        layout.addWidget(btn_ion_output, 1, 2)
        
        # 正离子类型
        layout.addWidget(QLabel("正离子类型:"), 2, 0)
        self.positive_ion_combo = QComboBox()
        self.positive_ion_combo.addItems(["NA", "K", "MG", "CA"])
        self.positive_ion_combo.setCurrentText("NA")
        layout.addWidget(self.positive_ion_combo, 2, 1, 1, 2)
        
        # 负离子类型
        layout.addWidget(QLabel("负离子类型:"), 3, 0)
        self.negative_ion_combo = QComboBox()
        self.negative_ion_combo.addItems(["CL", "BR", "F", "I"])
        self.negative_ion_combo.setCurrentText("CL")
        layout.addWidget(self.negative_ion_combo, 3, 1, 1, 2)
        
        # 离子浓度
        layout.addWidget(QLabel("离子浓度 (M):"), 4, 0)
        self.ion_concentration_spin = QDoubleSpinBox()
        self.ion_concentration_spin.setRange(0.0, 5.0)
        self.ion_concentration_spin.setValue(0.15)
        self.ion_concentration_spin.setSingleStep(0.01)
        layout.addWidget(self.ion_concentration_spin, 4, 1, 1, 2)
        
        # 电荷中和选项
        self.neutralize_check = QCheckBox("自动中和体系电荷")
        self.neutralize_check.setChecked(True)
        layout.addWidget(self.neutralize_check, 5, 0, 1, 3)
        
        # MDP文件设置
        layout.addWidget(QLabel("离子添加MDP文件:"), 6, 0)
        self.ion_mdp_file = QLineEdit()
        self.ion_mdp_file.setText("ions.mdp")
        btn_ion_mdp = QPushButton("保存")
        btn_ion_mdp.clicked.connect(lambda: self.save_structure_file(self.ion_mdp_file, "保存离子MDP文件", "MDP Files (*.mdp);;All Files (*)"))
        layout.addWidget(self.ion_mdp_file, 6, 1)
        layout.addWidget(btn_ion_mdp, 6, 2)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        self.generate_ion_cmd_btn = QPushButton("生成命令")
        self.execute_ion_cmd_btn = QPushButton("执行命令")
        self.generate_ion_cmd_btn.clicked.connect(self.generate_genion_command)
        self.execute_ion_cmd_btn.clicked.connect(self.execute_ion_addition)
        btn_layout.addWidget(self.generate_ion_cmd_btn)
        btn_layout.addWidget(self.execute_ion_cmd_btn)
        layout.addLayout(btn_layout, 7, 0, 1, 3)
        
        return tab

    def create_system_check_tab(self):
        """创建体系检查选项卡"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 文件验证组
        file_check_group = QGroupBox("文件验证")
        file_check_layout = QGridLayout(file_check_group)
        
        file_check_layout.addWidget(QLabel("检查文件:"), 0, 0)
        self.check_file_input = QLineEdit()
        self.check_file_input.setPlaceholderText("ionized.gro 或其他体系文件")
        btn_check_file = QPushButton("浏览")
        btn_check_file.clicked.connect(lambda: self.browse_structure_file(self.check_file_input, "选择体系文件", "GRO Files (*.gro);;PDB Files (*.pdb);;All Files (*)"))
        file_check_layout.addWidget(self.check_file_input, 0, 1)
        file_check_layout.addWidget(btn_check_file, 0, 2)
        
        self.check_file_btn = QPushButton("验证文件完整性")
        self.check_file_btn.clicked.connect(self.check_system_files)
        file_check_layout.addWidget(self.check_file_btn, 1, 0, 1, 3)
        
        layout.addWidget(file_check_group)
        
        # 原子数目统计组
        atom_count_group = QGroupBox("原子数目统计")
        atom_count_layout = QVBoxLayout(atom_count_group)
        
        self.atom_count_btn = QPushButton("统计原子数目")
        self.atom_count_btn.clicked.connect(self.count_atoms)
        atom_count_layout.addWidget(self.atom_count_btn)
        
        layout.addWidget(atom_count_group)
        
        # 电荷检查组
        charge_check_group = QGroupBox("电荷检查")
        charge_check_layout = QVBoxLayout(charge_check_group)
        
        self.charge_check_btn = QPushButton("检查体系总电荷")
        self.charge_check_btn.clicked.connect(self.check_total_charge)
        charge_check_layout.addWidget(self.charge_check_btn)
        
        layout.addWidget(charge_check_group)
        
        # 盒子尺寸验证组
        box_size_group = QGroupBox("盒子尺寸验证")
        box_size_layout = QVBoxLayout(box_size_group)
        
        self.box_size_btn = QPushButton("验证盒子尺寸")
        self.box_size_btn.clicked.connect(self.check_box_dimensions)
        box_size_layout.addWidget(self.box_size_btn)
        
        layout.addWidget(box_size_group)
        
        return tab

    def create_solvation_control_group(self):
        """创建溶剂化控制组"""
        control_group = QGroupBox("溶剂化控制")
        control_layout = QVBoxLayout(control_group)
        
        # 新手提示
        tip_label = QLabel("提示：请先在各步骤中设置好参数（如离子浓度），再点击‘一键执行’。")
        tip_label.setWordWrap(True)
        tip_label.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        control_layout.addWidget(tip_label)
        
        # 一键执行完整流程按钮
        self.run_complete_solvation_btn = QPushButton("一键执行完整溶剂化流程")
        self.run_complete_solvation_btn.setStyleSheet(self._btn_primary)
        self.run_complete_solvation_btn.clicked.connect(self.run_complete_solvation)
        control_layout.addWidget(self.run_complete_solvation_btn)
        
        # 状态显示标签
        self.solvation_status_label = QLabel("就绪")
        self.solvation_status_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 5px; border: 1px solid #ccc; border-radius: 3px; }")
        self.solvation_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 修复Qt常量引用
        control_layout.addWidget(self.solvation_status_label)
        
        return control_group

        self.structure_tabs.addTab(self.create_structure_clean_tab(), "结构清理修复")
        self.structure_tabs.addTab(self.create_format_convert_tab(), "格式转换")
        self.structure_tabs.addTab(self.create_structure_analysis_tab(), "结构分析")
        self.structure_tabs.addTab(self.create_structure_modify_tab(), "结构修改")

    # ----------------- 公共方法 -----------------
    def browse_structure_file(self, line_edit, title="选择文件", file_filter="All Files (*)"):
        path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
        if path:
            line_edit.setText(path)

    def save_structure_file(self, line_edit, title="保存文件", file_filter="All Files (*)"):
        path, _ = QFileDialog.getSaveFileName(self, title, "", file_filter)
        if path:
            line_edit.setText(path)

    def log_structure_message(self, message, level="INFO"):
        # 将结构操作的日志信息输出到右侧的实时输出区域
        self.append_output(f"[{level}] 结构操作: {message}", "info")

    def execute_gromacs_command(self, command):
        # 统一执行命令入口
        self.log_structure_message(command, "CMD")
        
        # 使用subprocess执行真实命令
        try:
            # 在实时输出中显示将要执行的命令
            self.append_output(f"执行命令: {command}", "command")
            
            # 执行命令并捕获输出
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.working_dir_edit.text() or os.getcwd())
            
            # 显示标准输出
            if result.stdout:
                self.append_output(result.stdout, "stdout")
            
            # 显示标准错误输出
            if result.stderr:
                self.append_output(result.stderr, "stderr")
            
            # 显示执行结果
            if result.returncode == 0:
                self.append_output("命令执行成功", "system")
            else:
                self.append_output(f"命令执行失败 (返回码: {result.returncode})", "stderr")
                
        except Exception as e:
            self.append_output(f"命令执行出错: {str(e)}", "stderr")

    # ----------------- Tab1: 结构居中对齐 -----------------
    def create_structure_center_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 结构居中组
        center_group = QGroupBox("结构居中组")
        cg_layout = QGridLayout(center_group)

        # 输入文件
        self.center_input = QLineEdit()
        self.center_input.setPlaceholderText("输入文件 (.pdb/.gro)")
        btn_in = QPushButton("浏览")
        btn_in.clicked.connect(lambda: self.browse_structure_file(self.center_input, "选择输入文件", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        cg_layout.addWidget(QLabel("输入文件:"), 0, 0)
        cg_layout.addWidget(self.center_input, 0, 1)
        cg_layout.addWidget(btn_in, 0, 2)

        # 输出文件
        self.center_output = QLineEdit()
        self.center_output.setPlaceholderText("输出文件 (.pdb/.gro)")
        btn_out = QPushButton("保存")
        btn_out.clicked.connect(lambda: self.save_structure_file(self.center_output, "保存输出文件", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        cg_layout.addWidget(QLabel("输出文件:"), 1, 0)
        cg_layout.addWidget(self.center_output, 1, 1)
        cg_layout.addWidget(btn_out, 1, 2)

        # TPR文件 (可选)
        self.center_tpr = QLineEdit()
        self.center_tpr.setPlaceholderText("TPR文件 (可选)")
        btn_tpr = QPushButton("浏览")
        btn_tpr.clicked.connect(lambda: self.browse_structure_file(self.center_tpr, "选择TPR文件", "TPR Files (*.tpr);;All Files (*)"))
        cg_layout.addWidget(QLabel("TPR文件 (可选):"), 2, 0)
        cg_layout.addWidget(self.center_tpr, 2, 1)
        cg_layout.addWidget(btn_tpr, 2, 2)

        # 居中类型
        self.center_type_cb = QComboBox()
        self.center_type_cb.addItems(["几何中心", "质量中心", "电荷中心"])
        cg_layout.addWidget(QLabel("居中类型:"), 3, 0)
        cg_layout.addWidget(self.center_type_cb, 3, 1)

        # 选择组
        self.center_group_cb = QComboBox()
        self.center_group_cb.addItems(["Protein", "Backbone", "System", "non-Water", "Water", "其他"])
        cg_layout.addWidget(QLabel("选择组:"), 4, 0)
        cg_layout.addWidget(self.center_group_cb, 4, 1)

        # 盒子尺寸设置
        box_size_layout = QHBoxLayout()
        self.box_x = QLineEdit()
        self.box_x.setPlaceholderText("X")
        self.box_y = QLineEdit()
        self.box_y.setPlaceholderText("Y")
        self.box_z = QLineEdit()
        self.box_z.setPlaceholderText("Z")
        box_size_layout.addWidget(QLabel("X:"))
        box_size_layout.addWidget(self.box_x)
        box_size_layout.addWidget(QLabel("Y:"))
        box_size_layout.addWidget(self.box_y)
        box_size_layout.addWidget(QLabel("Z:"))
        box_size_layout.addWidget(self.box_z)
        cg_layout.addWidget(QLabel("盒子尺寸 (nm):"), 5, 0)
        cg_layout.addLayout(box_size_layout, 5, 1)

        # 执行按钮
        exec_btn = QPushButton("执行")
        # exec_btn.setStyleSheet("background-color:#4CAF50; color:white; font-weight:bold;")
        exec_btn.clicked.connect(self.execute_center_structure)
        cg_layout.addWidget(exec_btn, 6, 0, 1, 3)

        layout.addWidget(center_group)

        # 结构对齐组
        align_group = QGroupBox("结构对齐组")
        ag_layout = QGridLayout(align_group)

        self.align_ref = QLineEdit()
        self.align_ref.setPlaceholderText("参考结构文件 (.pdb/.gro)")
        btn_ref = QPushButton("浏览")
        btn_ref.clicked.connect(lambda: self.browse_structure_file(self.align_ref, "选择参考结构", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        ag_layout.addWidget(QLabel("参考结构:"), 0, 0)
        ag_layout.addWidget(self.align_ref, 0, 1)
        ag_layout.addWidget(btn_ref, 0, 2)

        self.align_target = QLineEdit()
        self.align_target.setPlaceholderText("待对齐结构文件 (.pdb/.gro)")
        btn_tgt = QPushButton("浏览")
        btn_tgt.clicked.connect(lambda: self.browse_structure_file(self.align_target, "选择待对齐结构", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        ag_layout.addWidget(QLabel("待对齐结构:"), 1, 0)
        ag_layout.addWidget(self.align_target, 1, 1)
        ag_layout.addWidget(btn_tgt, 1, 2)

        self.align_output = QLineEdit()
        self.align_output.setPlaceholderText("对齐输出文件 (.pdb/.gro)")
        btn_align_out = QPushButton("保存")
        btn_align_out.clicked.connect(lambda: self.save_structure_file(self.align_output, "保存对齐输出", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        ag_layout.addWidget(QLabel("输出文件:"), 2, 0)
        ag_layout.addWidget(self.align_output, 2, 1)
        ag_layout.addWidget(btn_align_out, 2, 2)

        self.fit_rot_trans_cb = QCheckBox("拟合旋转和平移")
        self.fit_rot_cb = QCheckBox("仅拟合旋转")
        ag_layout.addWidget(self.fit_rot_trans_cb, 3, 0, 1, 2)
        ag_layout.addWidget(self.fit_rot_cb, 3, 2)

        exec_align_btn = QPushButton("执行")
        # exec_align_btn.setStyleSheet("background-color:#2196F3; color:white; font-weight:bold;")
        exec_align_btn.clicked.connect(self.execute_structure_alignment)
        ag_layout.addWidget(exec_align_btn, 4, 0, 1, 3)

        layout.addWidget(align_group)
        # layout.addStretch()
        return tab

    # ----------------- Tab2: 结构分组 -----------------
    def create_structure_group_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 原子组选择组
        group_box = QGroupBox("原子组选择组")
        gb_layout = QGridLayout(group_box)

        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("输入结构文件 (.pdb/.gro)")
        btn_group_in = QPushButton("浏览")
        btn_group_in.clicked.connect(lambda: self.browse_structure_file(self.group_input, "选择输入文件", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        gb_layout.addWidget(QLabel("输入文件:"), 0, 0)
        gb_layout.addWidget(self.group_input, 0, 1)
        gb_layout.addWidget(btn_group_in, 0, 2)

        self.predefined_list = QListWidget()
        self.predefined_list.setSelectionMode(QListWidget.MultiSelection)
        items = ["System","Protein","Protein-H","C-alpha","Backbone","MainChain","SideChain","Water","SOL","non-Water","Ion","NA","CL","Water_and_ions"]
        for it in items:
            QListWidgetItem(it, self.predefined_list)
        gb_layout.addWidget(QLabel("预定义组:"), 1, 0)
        gb_layout.addWidget(self.predefined_list, 1, 1, 3, 1)

        self.custom_select = QTextEdit()
        self.custom_select.setPlaceholderText("例如: resname LIG or name CA or resid 1-100")
        gb_layout.addWidget(QLabel("自定义选择:"), 1, 2)
        gb_layout.addWidget(self.custom_select, 2, 2, 2, 1)

        self.ndx_output = QLineEdit()
        self.ndx_output.setPlaceholderText("输出组文件 (.ndx)")
        btn_ndx = QPushButton("保存")
        btn_ndx.clicked.connect(lambda: self.save_structure_file(self.ndx_output, "保存 ndx 文件", "Index Files (*.ndx);;All Files (*)"))
        gb_layout.addWidget(QLabel("输出文件:"), 4, 0)
        gb_layout.addWidget(self.ndx_output, 4, 1)
        gb_layout.addWidget(btn_ndx, 4, 2)

        exec_groups_btn = QPushButton("执行")
        # exec_groups_btn.setStyleSheet("background-color:#FF9800; color:white; font-weight:bold;")
        exec_groups_btn.clicked.connect(self.create_atom_groups)
        gb_layout.addWidget(exec_groups_btn, 5, 0, 1, 3)

        layout.addWidget(group_box)

        # 结构提取组
        extract_box = QGroupBox("结构提取组")
        eb_layout = QGridLayout(extract_box)

        self.extract_type = QComboBox()
        self.extract_type.addItems(["蛋白质", "配体", "水分子", "离子", "自定义组"])
        eb_layout.addWidget(QLabel("提取内容:"), 0, 0)
        eb_layout.addWidget(self.extract_type, 0, 1)

        self.extract_output = QLineEdit()
        self.extract_output.setPlaceholderText("提取输出文件 (.pdb/.gro)")
        btn_extract_out = QPushButton("保存")
        btn_extract_out.clicked.connect(lambda: self.save_structure_file(self.extract_output, "保存提取输出", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        eb_layout.addWidget(QLabel("输出文件:"), 1, 0)
        eb_layout.addWidget(self.extract_output, 1, 1)
        eb_layout.addWidget(btn_extract_out, 1, 2)

        exec_extract_btn = QPushButton("执行")
        # exec_extract_btn.setStyleSheet("background-color:#9C27B0; color:white; font-weight:bold;")
        exec_extract_btn.clicked.connect(self.extract_structure)
        eb_layout.addWidget(exec_extract_btn, 2, 0, 1, 3)

        layout.addWidget(extract_box)
        # layout.addStretch()
        return tab

    # ----------------- Tab3: 结构清理修复 -----------------
    def create_structure_clean_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 结构清理组
        clean_box = QGroupBox("结构清理组")
        cb_layout = QGridLayout(clean_box)

        self.clean_input = QLineEdit()
        self.clean_input.setPlaceholderText("输入文件 (.pdb/.gro)")
        btn_clean_in = QPushButton("浏览")
        btn_clean_in.clicked.connect(lambda: self.browse_structure_file(self.clean_input, "选择输入文件", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        cb_layout.addWidget(QLabel("输入文件:"), 0, 0)
        cb_layout.addWidget(self.clean_input, 0, 1)
        cb_layout.addWidget(btn_clean_in, 0, 2)

        # 清理选项（2行3列）
        self.chk_remove_water = QCheckBox("移除水分子")
        self.chk_remove_ions = QCheckBox("移除离子")
        self.chk_remove_h = QCheckBox("移除氢原子")
        self.chk_remove_alt = QCheckBox("移除替代位置")
        self.chk_fix_pdb = QCheckBox("修复PDB格式")
        self.chk_renumber = QCheckBox("重新编号残基")

        cb_layout.addWidget(self.chk_remove_water, 1, 0)
        cb_layout.addWidget(self.chk_remove_ions, 1, 1)
        cb_layout.addWidget(self.chk_remove_h, 1, 2)
        cb_layout.addWidget(self.chk_remove_alt, 2, 0)
        cb_layout.addWidget(self.chk_fix_pdb, 2, 1)
        cb_layout.addWidget(self.chk_renumber, 2, 2)

        self.clean_output = QLineEdit()
        self.clean_output.setPlaceholderText("清理输出文件 (.pdb/.gro)")
        btn_clean_out = QPushButton("保存")
        btn_clean_out.clicked.connect(lambda: self.save_structure_file(self.clean_output, "保存清理输出", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        cb_layout.addWidget(QLabel("输出文件:"), 3, 0)
        cb_layout.addWidget(self.clean_output, 3, 1)
        cb_layout.addWidget(btn_clean_out, 3, 2)

        exec_clean_btn = QPushButton("执行")
        # exec_clean_btn.setStyleSheet("background-color:#F44336; color:white; font-weight:bold;")
        exec_clean_btn.clicked.connect(self.clean_structure)
        cb_layout.addWidget(exec_clean_btn, 4, 0, 1, 3)

        layout.addWidget(clean_box)

        # 结构修复组
        repair_box = QGroupBox("结构修复组")
        rb_layout = QGridLayout(repair_box)

        self.repair_type = QComboBox()
        self.repair_type.addItems(["添加氢原子", "修复缺失原子", "优化几何结构", "修复化学键"])
        rb_layout.addWidget(QLabel("修复类型:"), 0, 0)
        rb_layout.addWidget(self.repair_type, 0, 1)

        self.ph_spin = QDoubleSpinBox()
        self.ph_spin.setRange(0.0, 14.0)
        self.ph_spin.setValue(7.0)
        self.ph_spin.setSingleStep(0.1)
        rb_layout.addWidget(QLabel("pH 值:"), 1, 0)
        rb_layout.addWidget(self.ph_spin, 1, 1)

        self.force_field_cb = QComboBox()
        self.force_field_cb.addItems(["amber99sb-ildn", "charmm27", "oplsaa", "gromos54a7"])
        rb_layout.addWidget(QLabel("力场:"), 2, 0)
        rb_layout.addWidget(self.force_field_cb, 2, 1)

        self.repair_output = QLineEdit()
        self.repair_output.setPlaceholderText("修复输出文件 (.pdb/.gro)")
        btn_repair_out = QPushButton("保存")
        btn_repair_out.clicked.connect(lambda: self.save_structure_file(self.repair_output, "保存修复输出", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        rb_layout.addWidget(QLabel("输出文件:"), 3, 0)
        rb_layout.addWidget(self.repair_output, 3, 1)
        rb_layout.addWidget(btn_repair_out, 3, 2)

        exec_repair_btn = QPushButton("执行")
        # exec_repair_btn.setStyleSheet("background-color:#607D8B; color:white; font-weight:bold;")
        exec_repair_btn.clicked.connect(self.repair_structure)
        rb_layout.addWidget(exec_repair_btn, 4, 0, 1, 3)

        layout.addWidget(repair_box)
        # layout.addStretch()
        return tab

    # ----------------- Tab4: 格式转换 -----------------
    def create_format_convert_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 格式转换组
        format_box = QGroupBox("格式转换组")
        fb_layout = QGridLayout(format_box)

        self.conv_input = QLineEdit()
        self.conv_input.setPlaceholderText("输入文件")
        btn_conv_in = QPushButton("浏览")
        btn_conv_in.clicked.connect(lambda: self.browse_structure_file(self.conv_input, "选择输入文件", "All Files (*)"))
        fb_layout.addWidget(QLabel("输入文件:"), 0, 0)
        fb_layout.addWidget(self.conv_input, 0, 1)
        fb_layout.addWidget(btn_conv_in, 0, 2)

        self.input_fmt = QComboBox()
        self.input_fmt.addItems(["自动检测", "PDB", "GRO", "XYZ", "MOL2", "SDF"])
        self.output_fmt = QComboBox()
        self.output_fmt.addItems(["PDB", "GRO", "XYZ", "MOL2", "SDF"])
        fb_layout.addWidget(QLabel("输入格式:"), 1, 0)
        fb_layout.addWidget(self.input_fmt, 1, 1)
        fb_layout.addWidget(QLabel("输出格式:"), 2, 0)
        fb_layout.addWidget(self.output_fmt, 2, 1)

        self.conv_output = QLineEdit()
        self.conv_output.setPlaceholderText("输出文件")
        btn_conv_out = QPushButton("保存")
        btn_conv_out.clicked.connect(lambda: self.save_structure_file(self.conv_output, "保存输出文件", "All Files (*)"))
        fb_layout.addWidget(QLabel("输出文件:"), 3, 0)
        fb_layout.addWidget(self.conv_output, 3, 1)
        fb_layout.addWidget(btn_conv_out, 3, 2)

        self.chk_keep_bonds = QCheckBox("保持连接信息")
        self.chk_keep_charges = QCheckBox("保持电荷信息")
        fb_layout.addWidget(self.chk_keep_bonds, 4, 0)
        fb_layout.addWidget(self.chk_keep_charges, 4, 1)

        exec_conv_btn = QPushButton("执行")
        # exec_conv_btn.setStyleSheet("background-color:#00BCD4; color:white; font-weight:bold;")
        exec_conv_btn.clicked.connect(self.convert_format)
        fb_layout.addWidget(exec_conv_btn, 5, 0, 1, 3)

        layout.addWidget(format_box)

        # 轨迹转换组
        traj_box = QGroupBox("轨迹转换组")
        tb_layout = QGridLayout(traj_box)

        self.traj_file = QLineEdit()
        self.traj_file.setPlaceholderText("轨迹文件 (.xtc/.trr/.dcd)")
        btn_traj = QPushButton("浏览")
        btn_traj.clicked.connect(lambda: self.browse_structure_file(self.traj_file, "选择轨迹文件", "Trajectory Files (*.xtc *.trr *.dcd);;All Files (*)"))
        tb_layout.addWidget(QLabel("轨迹文件:"), 0, 0)
        tb_layout.addWidget(self.traj_file, 0, 1)
        tb_layout.addWidget(btn_traj, 0, 2)

        self.topo_file = QLineEdit()
        self.topo_file.setPlaceholderText("拓扑文件 (.pdb/.gro/.tpr)")
        btn_topo = QPushButton("浏览")
        btn_topo.clicked.connect(lambda: self.browse_structure_file(self.topo_file, "选择拓扑文件", "PDB/GRO/TPR Files (*.pdb *.gro *.tpr);;All Files (*)"))
        tb_layout.addWidget(QLabel("拓扑文件:"), 1, 0)
        tb_layout.addWidget(self.topo_file, 1, 1)
        tb_layout.addWidget(btn_topo, 1, 2)

        self.start_time = QSpinBox()
        self.start_time.setMaximum(1000000)
        self.start_time.setValue(0)
        self.end_time = QSpinBox()
        self.end_time.setMaximum(1000000)
        self.end_time.setValue(10000)
        self.frame_step = QSpinBox()
        self.frame_step.setRange(1, 1000)
        self.frame_step.setValue(1)
        tb_layout.addWidget(QLabel("起始时间:"), 2, 0)
        tb_layout.addWidget(self.start_time, 2, 1)
        tb_layout.addWidget(QLabel("结束时间:"), 3, 0)
        tb_layout.addWidget(self.end_time, 3, 1)
        tb_layout.addWidget(QLabel("帧间隔:"), 4, 0)
        tb_layout.addWidget(self.frame_step, 4, 1)

        self.traj_output = QLineEdit()
        self.traj_output.setPlaceholderText("轨迹输出文件")
        btn_traj_out = QPushButton("保存")
        btn_traj_out.clicked.connect(lambda: self.save_structure_file(self.traj_output, "保存轨迹输出", "Trajectory Files (*.xtc *.trr *.dcd);;All Files (*)"))
        tb_layout.addWidget(QLabel("输出文件:"), 5, 0)
        tb_layout.addWidget(self.traj_output, 5, 1)
        tb_layout.addWidget(btn_traj_out, 5, 2)

        exec_traj_btn = QPushButton("执行")
        # exec_traj_btn.setStyleSheet("background-color:#8BC34A; color:white; font-weight:bold;")
        exec_traj_btn.clicked.connect(self.convert_trajectory)
        tb_layout.addWidget(exec_traj_btn, 6, 0, 1, 3)

        layout.addWidget(traj_box)
        # layout.addStretch()
        return tab

    # ----------------- Tab5: 结构分析 -----------------
    def create_structure_analysis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 基本结构分析组
        basic_box = QGroupBox("基本结构分析组")
        bb_layout = QGridLayout(basic_box)

        self.analy_input = QLineEdit()
        self.analy_input.setPlaceholderText("输入文件 (.pdb/.gro)")
        btn_analy_in = QPushButton("浏览")
        btn_analy_in.clicked.connect(lambda: self.browse_structure_file(self.analy_input, "选择输入文件", "PDB Files (*.pdb);;GRO Files (*.gro);;All Files (*)"))
        bb_layout.addWidget(QLabel("输入文件:"), 0, 0)
        bb_layout.addWidget(self.analy_input, 0, 1)
        bb_layout.addWidget(btn_analy_in, 0, 2)

        self.analysis_list = QListWidget()
        self.analysis_list.setSelectionMode(QListWidget.MultiSelection)
        analysis_items = ["结构信息统计", "原子数目统计", "残基类型统计", "二级结构分析", "氢键分析", "盐桥分析", "疏水接触分析"]
        for it in analysis_items:
            QListWidgetItem(it, self.analysis_list)
        bb_layout.addWidget(QLabel("分析类型:"), 1, 0)
        bb_layout.addWidget(self.analysis_list, 1, 1, 3, 1)

        self.analysis_output = QLineEdit()
        self.analysis_output.setPlaceholderText("分析报告输出文件 (.txt/.log)")
        btn_analysis_out = QPushButton("保存")
        btn_analysis_out.clicked.connect(lambda: self.save_structure_file(self.analysis_output, "保存分析报告", "Text Files (*.txt);;Log Files (*.log);;All Files (*)"))
        bb_layout.addWidget(QLabel("输出文件:"), 4, 0)
        bb_layout.addWidget(self.analysis_output, 4, 1)
        bb_layout.addWidget(btn_analysis_out, 4, 2)

        exec_analysis_btn = QPushButton("执行")
        # exec_analysis_btn.setStyleSheet("background-color:#795548; color:white; font-weight:bold;")
        exec_analysis_btn.clicked.connect(self.analyze_structure)
        bb_layout.addWidget(exec_analysis_btn, 5, 0, 1, 3)

        layout.addWidget(basic_box)

        # 几何分析组
        geo_box = QGroupBox("几何分析组")
        gb_layout = QGridLayout(geo_box)

        self.atom1_input = QLineEdit()
        self.atom1_input.setPlaceholderText("例如: resid 1 and name CA")
        self.atom2_input = QLineEdit()
        self.atom2_input.setPlaceholderText("例如: resid 50 and name CA")
        gb_layout.addWidget(QLabel("原子1:"), 0, 0)
        gb_layout.addWidget(self.atom1_input, 0, 1)
        gb_layout.addWidget(QLabel("原子2:"), 1, 0)
        gb_layout.addWidget(self.atom2_input, 1, 1)

        self.chk_distance = QCheckBox("计算距离")
        self.chk_angle = QCheckBox("计算角度")
        self.chk_dihedral = QCheckBox("计算二面角")
        gb_layout.addWidget(self.chk_distance, 2, 0)
        gb_layout.addWidget(self.chk_angle, 2, 1)
        gb_layout.addWidget(self.chk_dihedral, 2, 2)

        exec_geo_btn = QPushButton("执行")
        # exec_geo_btn.setStyleSheet("background-color:#3F51B5; color:white; font-weight:bold;")
        exec_geo_btn.clicked.connect(self.geometric_analysis)
        gb_layout.addWidget(exec_geo_btn, 3, 0, 1, 3)

        layout.addWidget(geo_box)
        # layout.addStretch()
        return tab

    # ----------------- Tab6: 结构修改 -----------------
    def create_structure_modify_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 原子操作组
        atom_box = QGroupBox("原子操作组")
        ab_layout = QGridLayout(atom_box)

        self.atom_op_cb = QComboBox()
        self.atom_op_cb.addItems(["添加原子", "删除原子", "修改原子类型", "修改电荷"])
        ab_layout.addWidget(QLabel("操作类型:"), 0, 0)
        ab_layout.addWidget(self.atom_op_cb, 0, 1)

        self.atom_select_input = QLineEdit()
        self.atom_select_input.setPlaceholderText("原子选择输入")
        ab_layout.addWidget(QLabel("原子选择:"), 1, 0)
        ab_layout.addWidget(self.atom_select_input, 1, 1)

        # 参数设置区域（动态变化：这里用 QTextEdit 简单替代）
        self.atom_param_area = QTextEdit()
        self.atom_param_area.setPlaceholderText("参数设置（根据操作动态变化）")
        ab_layout.addWidget(QLabel("参数设置:"), 2, 0)
        ab_layout.addWidget(self.atom_param_area, 2, 1)

        exec_atom_btn = QPushButton("执行")
        # exec_atom_btn.setStyleSheet("background-color:#673AB7; color:white; font-weight:bold;")
        exec_atom_btn.clicked.connect(self.modify_atoms)
        ab_layout.addWidget(exec_atom_btn, 3, 0, 1, 2)

        layout.addWidget(atom_box)

        # 残基操作组
        res_box = QGroupBox("残基操作组")
        rb_layout = QGridLayout(res_box)

        self.res_op_cb = QComboBox()
        self.res_op_cb.addItems(["添加残基", "删除残基", "修改残基名称", "突变残基"])
        rb_layout.addWidget(QLabel("操作类型:"), 0, 0)
        rb_layout.addWidget(self.res_op_cb, 0, 1)

        self.res_select_input = QLineEdit()
        self.res_select_input.setPlaceholderText("残基选择输入")
        rb_layout.addWidget(QLabel("残基选择:"), 1, 0)
        rb_layout.addWidget(self.res_select_input, 1, 1)

        self.res_target_input = QLineEdit()
        self.res_target_input.setPlaceholderText("目标残基类型")
        rb_layout.addWidget(QLabel("目标残基:"), 2, 0)
        rb_layout.addWidget(self.res_target_input, 2, 1)

        exec_res_btn = QPushButton("执行")
        # exec_res_btn.setStyleSheet("background-color:#FF5722; color:white; font-weight:bold;")
        exec_res_btn.clicked.connect(self.modify_residues)
        rb_layout.addWidget(exec_res_btn, 3, 0, 1, 2)

        layout.addWidget(res_box)

        # 坐标变换组
        transform_box = QGroupBox("坐标变换组")
        tb_layout = QGridLayout(transform_box)

        self.transform_type = QComboBox()
        self.transform_type.addItems(["平移", "旋转", "缩放", "反射"])
        tb_layout.addWidget(QLabel("变换类型:"), 0, 0)
        tb_layout.addWidget(self.transform_type, 0, 1)

        self.trans_x = QLineEdit()
        self.trans_x.setPlaceholderText("X")
        self.trans_y = QLineEdit()
        self.trans_y.setPlaceholderText("Y")
        self.trans_z = QLineEdit()
        self.trans_z.setPlaceholderText("Z")
        tb_layout.addWidget(QLabel("参数 X/Y/Z:"), 1, 0)
        tb_layout.addWidget(self.trans_x, 1, 1)
        tb_layout.addWidget(self.trans_y, 1, 2)
        tb_layout.addWidget(self.trans_z, 1, 3)

        self.transform_center = QLineEdit()
        self.transform_center.setPlaceholderText("变换中心（例如: resid 1 and name CA）")
        tb_layout.addWidget(QLabel("变换中心:"), 2, 0)
        tb_layout.addWidget(self.transform_center, 2, 1, 1, 3)

        exec_transform_btn = QPushButton("执行")
        # exec_transform_btn.setStyleSheet("background-color:#546E7A; color:white; font-weight:bold;")
        exec_transform_btn.clicked.connect(self.transform_coordinates)
        tb_layout.addWidget(exec_transform_btn, 3, 0, 1, 4)

        layout.addWidget(transform_box)
        # layout.addStretch()
        return tab

    # ----------------- 业务方法（占位） -----------------
    def execute_center_structure(self):
        self.log_structure_message("开始：结构居中对齐")
        # 获取输入参数
        input_file = self.center_input.text()
        output_file = self.center_output.text()
        tpr_file = self.center_tpr.text()
        
        # 获取盒子尺寸
        box_x = self.box_x.text().strip()
        box_y = self.box_y.text().strip()
        box_z = self.box_z.text().strip()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 检查TPR文件
        if tpr_file:
            # 检查文件路径是否有效
            if not os.path.exists(tpr_file):
                self.log_structure_message("错误：TPR文件路径无效", "ERROR")
                return
            
            # 检查扩展名是否为.tpr
            if not tpr_file.lower().endswith('.tpr'):
                self.log_structure_message("错误：TPR文件扩展名必须为.tpr", "ERROR")
                return
            
            # 使用trjconv命令（忽略盒子尺寸设置）
            command = f"gmx trjconv -f {input_file} -o {output_file} -s {tpr_file} -center -pbc mol"
            self.log_structure_message("使用trjconv方式居中结构", "INFO")
        else:
            # 检查盒子尺寸输入
            if box_x or box_y or box_z:
                # 如果用户填写了任何盒子尺寸，则需要全部填写且为数字
                if not (box_x and box_y and box_z):
                    self.log_structure_message("错误：请填写完整的盒子尺寸 X, Y, Z", "ERROR")
                    return
                    
                # 检查盒子尺寸是否为数字
                try:
                    float(box_x)
                    float(box_y)
                    float(box_z)
                except ValueError:
                    self.log_structure_message("错误：盒子尺寸必须为数字", "ERROR")
                    return
                    
                # 使用editconf命令并设置盒子尺寸
                command = f"gmx editconf -f {input_file} -o {output_file} -c -box {box_x} {box_y} {box_z}"
                self.log_structure_message("使用editconf方式居中结构并设置盒子尺寸", "INFO")
            else:
                # 使用editconf命令，不设置盒子尺寸
                command = f"gmx editconf -f {input_file} -o {output_file} -c"
                self.log_structure_message("使用editconf方式居中结构", "INFO")
            
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def execute_structure_alignment(self):
        self.log_structure_message("开始：结构对齐")
        # 获取输入参数
        ref_file = self.align_ref.text()
        target_file = self.align_target.text()
        output_file = self.align_output.text()
        
        if not ref_file or not target_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        fit_option = ""
        if self.fit_rot_trans_cb.isChecked():
            fit_option = "-fit rot+trans"
        elif self.fit_rot_cb.isChecked():
            fit_option = "-fit rot"
            
        command = f"gmx confrms {fit_option} {ref_file} {target_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)

    def create_atom_groups(self):
        self.log_structure_message("开始：创建原子组")
        # 获取输入参数
        input_file = self.group_input.text()
        output_file = self.ndx_output.text()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 获取选中的预定义组
        selected_groups = [item.text() for item in self.predefined_list.selectedItems()]
        custom_selection = self.custom_select.toPlainText()
        
        # 构建gmx命令
        command = f"gmx make_ndx -f {input_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def extract_structure(self):
        self.log_structure_message("开始：提取结构")
        # 获取输入参数
        input_file = self.group_input.text()  # 使用分组输入的文件
        output_file = self.extract_output.text()
        extract_type = self.extract_type.currentText()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx trjconv -f {input_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def clean_structure(self):
        self.log_structure_message("开始：结构清理")
        # 获取输入参数
        input_file = self.clean_input.text()
        output_file = self.clean_output.text()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx editconf -f {input_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def repair_structure(self):
        self.log_structure_message("开始：结构修复")
        # 获取输入参数
        input_file = self.clean_input.text()  # 使用清理输入的文件
        output_file = self.repair_output.text()
        repair_type = self.repair_type.currentText()
        ph_value = self.ph_spin.value()
        force_field = self.force_field_cb.currentText()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx pdb2gmx -f {input_file} -o {output_file} -ff {force_field} -water tip3p"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def convert_format(self):
        self.log_structure_message("开始：格式转换")
        # 获取输入参数
        input_file = self.conv_input.text()
        output_file = self.conv_output.text()
        input_fmt = self.input_fmt.currentText()
        output_fmt = self.output_fmt.currentText()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx editconf -f {input_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def convert_trajectory(self):
        self.log_structure_message("开始：轨迹转换")
        # 获取输入参数
        traj_file = self.traj_file.text()
        topo_file = self.topo_file.text()
        output_file = self.traj_output.text()
        
        if not traj_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx trjconv -f {traj_file} -s {topo_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def analyze_structure(self):
        self.log_structure_message("开始：结构分析")
        # 获取输入参数
        input_file = self.analy_input.text()
        output_file = self.analysis_output.text()
        
        if not input_file or not output_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx gyrate -f {input_file} -s {input_file} -o {output_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def geometric_analysis(self):
        self.log_structure_message("开始：几何分析")
        # 获取输入参数
        input_file = self.analy_input.text()  # 使用分析输入的文件
        atom1 = self.atom1_input.text()
        atom2 = self.atom2_input.text()
        
        if not input_file:
            self.log_structure_message("错误：请输入完整的文件路径", "ERROR")
            return
            
        # 构建gmx命令
        command = f"gmx distance -f {input_file} -s {input_file}"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def modify_atoms(self):
        self.log_structure_message("开始：原子操作")
        # 获取输入参数
        op_type = self.atom_op_cb.currentText()
        atom_selection = self.atom_select_input.text()
        
        # 构建gmx命令
        command = f"gmx editconf -f input.gro -o output.gro"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def modify_residues(self):
        self.log_structure_message("开始：残基操作")
        # 获取输入参数
        op_type = self.res_op_cb.currentText()
        res_selection = self.res_select_input.text()
        target_res = self.res_target_input.text()
        
        # 构建gmx命令
        command = f"gmx editconf -f input.gro -o output.gro"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def transform_coordinates(self):
        self.log_structure_message("开始：坐标变换")
        # 获取输入参数
        transform_type = self.transform_type.currentText()
        x_val = self.trans_x.text()
        y_val = self.trans_y.text()
        z_val = self.trans_z.text()
        center = self.transform_center.text()
        
        # 构建gmx命令
        command = f"gmx editconf -f input.gro -o output.gro"
        self.log_structure_message(f"执行命令: {command}")
        self.execute_gromacs_command(command)
        
    def connect_signals(self):
        """连接所有信号和槽"""
        # 文件选择按钮
        self.working_dir_button.clicked.connect(self.select_working_directory)
        self.pdb_file_button.clicked.connect(lambda: self.select_file(self.pdb_file_edit, "PDB Files (*.pdb)"))
        self.gro_file_button.clicked.connect(lambda: self.select_file(self.gro_file_edit, "GRO Files (*.gro)"))
        self.top_file_button.clicked.connect(lambda: self.select_file(self.top_file_edit, "TOP Files (*.top)"))
        self.itp_file_button.clicked.connect(lambda: self.select_file(self.itp_file_edit, "ITP Files (*.itp)"))
        self.auto_fill_button.clicked.connect(lambda: self.auto_fill_input_files(self.working_dir_edit.text()))
        
        # MDP生成按钮 - 修复方法名称
        self.generate_em_mdp_button.clicked.connect(self.generate_minimization_mdp_content)
        self.generate_nvt_mdp_button.clicked.connect(self.generate_nvt_mdp)
        self.generate_npt_mdp_button.clicked.connect(self.generate_npt_mdp)
        self.generate_prod_mdp_button.clicked.connect(self.generate_production_mdp)
        
        # 能量最小化参数变化时更新MDP预览
        self.em_integrator_combo.currentTextChanged.connect(self.update_current_mdp_preview)
        self.em_nsteps_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_emtol_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_emstep_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_coulombtype_combo.currentTextChanged.connect(self.update_current_mdp_preview)
        self.em_rvdw_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_rcoulomb_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_nstxout_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_nstenergy_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_nstlog_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_lincs_iter_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_lincs_order_spin.valueChanged.connect(self.update_current_mdp_preview)
        self.em_pbc_combo.currentTextChanged.connect(self.update_current_mdp_preview)
        
        # 结构操作按钮信号连接在各Tab中已连接
        
        # 结构操作信号连接已在各Tab中完成
        
        # MDP预览选项卡按钮 - 修复保存按钮连接的方法
        self.save_mdp_btn.clicked.connect(self.save_current_mdp)
        self.select_mdp_btn.clicked.connect(self.select_existing_mdp_file)
        
        # 命令预览选项卡按钮
        self.generate_command_btn.clicked.connect(self.generate_current_command)
        self.execute_command_btn.clicked.connect(self.execute_current_command)
        self.copy_command_btn.clicked.connect(self.copy_to_clipboard)
        self.save_script_btn.clicked.connect(self.save_current_command)
        
        # 实时输出选项卡按钮
        self.start_btn.clicked.connect(self.on_execute_command_clicked)
        self.stop_btn.clicked.connect(self.on_stop_command_clicked)
        self.clear_output_btn.clicked.connect(self.clear_realtime_output)
        
        # 执行日志选项卡按钮
        self.clear_log_button.clicked.connect(self.clear_log)
        
        # 文件状态选项卡按钮
        self.update_file_status_btn.clicked.connect(self.update_file_status)
        self.preview_file_btn.clicked.connect(self.preview_selected_file)
        
        # 语言设置选项卡按钮 - 移除对不存在的switch_language_btn的连接
        # self.switch_language_btn.clicked.connect(self.switch_language)
        
        # 工作目录改变时更新文件管理器
        self.working_dir_edit.textChanged.connect(self.update_file_manager)
        
        # PBC参数变化时更新命令预览
        prefixes = ['em', 'nvt', 'npt', 'md']
        for prefix in prefixes:
            if hasattr(self, f'{prefix}_pbc_combo'):
                getattr(self, f'{prefix}_pbc_combo').currentTextChanged.connect(
                    lambda text, p=prefix: self.on_pbc_changed(p, text))
            if hasattr(self, f'{prefix}_cutoff_scheme_combo'):
                getattr(self, f'{prefix}_cutoff_scheme_combo').currentTextChanged.connect(
                    lambda text, p=prefix: self.on_cutoff_scheme_changed(p, text))
        
        # MDP参数搜索信号连接
        if hasattr(self, 'mdp_search_btn'):
            self.mdp_search_btn.clicked.connect(self.search_mdp_parameters)
        if hasattr(self, 'mdp_search_edit'):
            self.mdp_search_edit.returnPressed.connect(self.search_mdp_parameters)
            
    def clear_realtime_output(self):
        """清空实时输出显示"""
        if hasattr(self, 'output_display'):
            self.output_display.clear()
            
    def clear_log(self):
        """清空执行日志显示"""
        if hasattr(self, 'log_output'):
            self.log_output.clear()
            
    def get_file_generation_time(self, file_path):
        """获取文件的生成时间"""
        try:
            # 获取文件的修改时间
            mtime = os.path.getmtime(file_path)
            # 转换为可读格式
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        except:
            return "未知时间"
    
    def get_file_size(self, file_path):
        """获取文件大小并格式化为可读字符串"""
        try:
            size = os.path.getsize(file_path)
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            elif size < 1024 * 1024 * 1024:
                return f"{size / (1024 * 1024):.1f} MB"
            else:
                return f"{size / (1024 * 1024 * 1024):.2f} GB"
        except:
            return "未知大小"
    
    def get_file_category(self, file_name):
        """根据文件名判断文件类别"""
        # 转换为小写进行匹配
        name_lower = file_name.lower()
        
        # 根据文件名前缀判断类别
        if name_lower.startswith('em.'):
            return "em files"
        elif name_lower.startswith('nvt.'):
            return "nvt files"
        elif name_lower.startswith('npt.'):
            return "npt files"
        elif name_lower.startswith('md.'):
            return "md files"
        else:
            return "other files"
    
    def update_file_status(self):
        """更新文件状态显示"""
        # 清空现有的文件列表
        if hasattr(self, 'file_list_layout'):
            # 移除所有现有的文件按钮，但保留最后一个stretch
            while self.file_list_layout.count() > 1:
                item = self.file_list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            # 获取当前工作目录
            working_dir = self.working_dir_edit.text()
            if working_dir and os.path.exists(working_dir) and os.path.isdir(working_dir):
                # 定义要查找的文件类型
                file_extensions = ['*.gro', '*.pdb', '*.top', '*.itp', '*.mdp', '*.tpr', '*.trr', '*.xtc', '*.edr', '*.log', '*.cpt']
                
                # 查找所有相关文件
                all_files = []
                try:
                    # 获取目录中的所有文件
                    all_directory_files = os.listdir(working_dir)
                    for pattern in file_extensions:
                        # 移除通配符符号以进行匹配
                        for file_name in all_directory_files:
                            if fnmatch.fnmatch(file_name, pattern):
                                all_files.append(os.path.join(working_dir, file_name))
                except OSError:
                    # 如果无法列出目录内容，保持all_files为空
                    pass
                
                # 按文件名排序
                all_files.sort()
                
                # 按文件类别分组
                file_categories = {}
                for file_path in all_files:
                    file_name = os.path.basename(file_path)
                    category = self.get_file_category(file_name)
                    if category not in file_categories:
                        file_categories[category] = []
                    file_categories[category].append(file_path)
                
                # 为每个类别和文件创建显示
                categories_order = ["em files", "nvt files", "npt files", "md files", "other files"]
                for category in categories_order:
                    if category in file_categories and file_categories[category]:
                        # 添加类别标题
                        category_label = QLabel(f"=== {category} ===")
                        category_label.setStyleSheet("QLabel { font-weight: bold; color: #2c3e50; margin-top: 10px; }")
                        self.file_list_layout.insertWidget(self.file_list_layout.count() - 1, category_label)
                        
                        # 为每个文件创建按钮
                        for file_path in file_categories[category]:
                            file_name = os.path.basename(file_path)
                            # 获取文件生成时间
                            gen_time = self.get_file_generation_time(file_path)
                            # 获取文件大小
                            file_size = self.get_file_size(file_path)
                            # 创建带时间和大小信息的按钮文本
                            button_text = f"{file_name} ({gen_time}, {file_size})"
                            file_button = QPushButton(button_text)
                            file_button.setToolTip(file_path)
                            file_button.setCheckable(True)
                            
                            # 连接按钮点击事件
                            file_button.clicked.connect(lambda checked, path=file_path, btn=file_button: self.on_file_button_clicked(path, btn))
                            
                            self.file_list_layout.insertWidget(self.file_list_layout.count() - 1, file_button)
                
                # 如果没有文件，显示提示信息
                if not all_files:
                    no_files_label = QLabel("当前目录中没有找到相关文件")
                    no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.file_list_layout.insertWidget(self.file_list_layout.count() - 1, no_files_label)
                    
    def on_file_button_clicked(self, file_path, button):
        """文件按钮点击事件处理"""
        # 取消之前选中的按钮
        if hasattr(self, 'selected_file_button') and self.selected_file_button and self.selected_file_button != button:
            # 检查按钮对象是否仍然有效
            try:
                self.selected_file_button.setChecked(False)
            except RuntimeError:
                # 如果按钮已被删除，忽略错误
                pass
        
        # 设置当前选中的按钮
        self.selected_file_button = button
        
        # 如果按钮被取消选中，清空选中状态
        if not button.isChecked():
            self.selected_file_button = None

    def preview_selected_file(self):
        """预览选中的文件"""
        if hasattr(self, 'selected_file_button') and self.selected_file_button:
            try:
                file_path = self.selected_file_button.toolTip()
            except RuntimeError:
                # 如果按钮已被删除，显示错误信息
                QMessageBox.information(self, "文件按钮已失效", "选中的文件按钮已被删除，请重新选择文件")
                self.selected_file_button = None
                return
                
            if os.path.exists(file_path):
                # 根据文件扩展名选择合适的预览方法
                file_ext = os.path.splitext(file_path)[1].lower()
                
                if file_ext in ['.gro', '.pdb']:
                    self.preview_structure_file(file_path)
                elif file_ext == '.edr':
                    self.preview_edr_file(file_path)
                elif file_ext == '.xtc':
                    self.preview_xtc_file(file_path)
                elif file_ext == '.cpt':
                    self.preview_cpt_file(file_path)
                elif file_ext == '.tpr':
                    self.preview_tpr_file(file_path)
                else:
                    # 默认文本预览
                    self.show_text_file(file_path)
            else:
                QMessageBox.warning(self, "文件不存在", f"文件不存在: {file_path}")
        else:
            QMessageBox.information(self, "未选择文件", "请先在文件列表中选择一个文件")

    def create_energy_minimization_tab(self):
        """创建能量最小化选项卡"""
        self.em_tab = QWidget()
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        layout = QGridLayout(scroll_widget)
        # 参数控件
        layout.addWidget(QLabel("积分器 (integrator):"), 0, 0)
        self.em_integrator_combo = QComboBox()
        self.em_integrator_combo.addItems(['steep', 'cg', 'sd', 'bd', 'md'])
        self.em_integrator_combo.setCurrentText('steep')
        layout.addWidget(self.em_integrator_combo, 0, 1)
        layout.addWidget(QLabel("能量收敛阈值 (emtol):"), 1, 0)
        self.em_emtol_spin = QDoubleSpinBox()
        self.em_emtol_spin.setRange(1.0, 10000.0)
        self.em_emtol_spin.setValue(1000.0)
        self.em_emtol_spin.setSuffix(" kJ/mol/nm")
        layout.addWidget(self.em_emtol_spin, 1, 1)
        layout.addWidget(QLabel("最大步数 (nsteps):"), 2, 0)
        self.em_nsteps_spin = QSpinBox()
        self.em_nsteps_spin.setRange(100, 1000000)
        self.em_nsteps_spin.setValue(50000)
        layout.addWidget(self.em_nsteps_spin, 2, 1)
        layout.addWidget(QLabel("初始步长 (emstep):"), 3, 0)
        self.em_emstep_spin = QDoubleSpinBox()
        self.em_emstep_spin.setRange(0.001, 1.0)
        self.em_emstep_spin.setValue(0.01)
        self.em_emstep_spin.setSuffix(" nm")
        layout.addWidget(self.em_emstep_spin, 3, 1)
        layout.addWidget(QLabel("静电方法 (coulombtype):"), 4, 0)
        self.em_coulombtype_combo = QComboBox()
        self.em_coulombtype_combo.addItems(['PME', 'Ewald', 'Cut-off'])
        self.em_coulombtype_combo.setCurrentText('PME')
        layout.addWidget(self.em_coulombtype_combo, 4, 1)
        layout.addWidget(QLabel("范德华截断 (rvdw):"), 5, 0)
        self.em_rvdw_spin = QDoubleSpinBox()

        self.em_rvdw_spin.setRange(0.5, 2.0)
        self.em_rvdw_spin.setValue(1.0)
        self.em_rvdw_spin.setSuffix(" nm")
        layout.addWidget(self.em_rvdw_spin, 5, 1)
        layout.addWidget(QLabel("静电截断 (rcoulomb):"), 6, 0)
        self.em_rcoulomb_spin = QDoubleSpinBox()
        self.em_rcoulomb_spin.setRange(0.5, 2.0)
        self.em_rcoulomb_spin.setValue(1.0)
        self.em_rcoulomb_spin.setSuffix(" nm")
        layout.addWidget(self.em_rcoulomb_spin, 6, 1)
        
        # 添加输出控制参数
        layout.addWidget(QLabel("坐标输出频率 (nstxout):"), 7, 0)
        self.em_nstxout_spin = QSpinBox()
        self.em_nstxout_spin.setRange(0, 50000)
        self.em_nstxout_spin.setValue(1000)
        layout.addWidget(self.em_nstxout_spin, 7, 1)
        
        layout.addWidget(QLabel("能量输出频率 (nstenergy):"), 8, 0)
        self.em_nstenergy_spin = QSpinBox()
        self.em_nstenergy_spin.setRange(0, 50000)
        self.em_nstenergy_spin.setValue(1000)
        layout.addWidget(self.em_nstenergy_spin, 8, 1)
        
        layout.addWidget(QLabel("日志输出频率 (nstlog):"), 9, 0)
        self.em_nstlog_spin = QSpinBox()
        self.em_nstlog_spin.setRange(0, 50000)
        self.em_nstlog_spin.setValue(1000)
        layout.addWidget(self.em_nstlog_spin, 9, 1)
        
        # 添加约束参数
        layout.addWidget(QLabel("LINCS精度参数 (lincs_iter):"), 10, 0)
        self.em_lincs_iter_spin = QSpinBox()
        self.em_lincs_iter_spin.setRange(1, 20)
        self.em_lincs_iter_spin.setValue(1)
        layout.addWidget(self.em_lincs_iter_spin, 10, 1)
        
        layout.addWidget(QLabel("LINCS阶数参数 (lincs_order):"), 11, 0)
        self.em_lincs_order_spin = QSpinBox()
        self.em_lincs_order_spin.setRange(1, 10)
        self.em_lincs_order_spin.setValue(4)
        layout.addWidget(self.em_lincs_order_spin, 11, 1)
        
        # 添加 tc-grps 下拉选项
        layout.addWidget(QLabel("温度耦合组 (tc-grps):"), 12, 0)
        self.em_tc_grps_combo = QComboBox()
        self.em_tc_grps_combo.addItem("System", ("System", "0.1", "300"))
        self.em_tc_grps_combo.addItem("Protein Water_and_ions", ("Protein Water_and_ions", "0.1 0.1", "300 300"))
        self.em_tc_grps_combo.addItem("Protein_Membrane Water_and_ions", ("Protein_Membrane Water_and_ions", "0.1 0.1", "310 310"))
        self.em_tc_grps_combo.addItem("Molecule Water_and_ions", ("Molecule Water_and_ions", "0.1 0.1", "300 300"))
        self.em_tc_grps_combo.addItem("Solid Liquid", ("Solid Liquid", "0.1 0.1", "300 300"))
        layout.addWidget(self.em_tc_grps_combo, 12, 1)
        
        # PBC设置组
        pbc_group = self.create_pbc_group('em')
        layout.addWidget(pbc_group, 13, 0, 1, 2)
        
        # 生成MDP按钮
        self.generate_em_mdp_button = QPushButton("生成能量最小化MDP")
        layout.addWidget(self.generate_em_mdp_button, 14, 0, 1, 2)
        scroll_widget.setLayout(layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        self.em_tab.setLayout(QVBoxLayout())
        self.em_tab.layout().addWidget(scroll_area)
        self.sim_run_tabs.addTab(self.em_tab, "能量最小化")

################################################
    def create_nvt_equilibration_tab(self):
        """创建NVT平衡选项卡"""
        self.nvt_tab = QWidget()
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        layout = QGridLayout(scroll_widget)
        # 参数控件
        layout.addWidget(QLabel("积分器 (integrator):"), 0, 0)
        self.nvt_integrator_combo = QComboBox()
        self.nvt_integrator_combo.addItems(['md', 'md-vv', 'sd', 'bd'])
        self.nvt_integrator_combo.setCurrentText('md')
        layout.addWidget(self.nvt_integrator_combo, 0, 1)
        layout.addWidget(QLabel("时间步长 (dt):"), 1, 0)
        self.nvt_dt_spin = QDoubleSpinBox()
        self.nvt_dt_spin.setRange(0.001, 0.01)
        self.nvt_dt_spin.setValue(0.002)
        self.nvt_dt_spin.setSuffix(" ps")
        layout.addWidget(self.nvt_dt_spin, 1, 1)
        layout.addWidget(QLabel("步数 (nsteps):"), 2, 0)
        self.nvt_nsteps_spin = QSpinBox()
        self.nvt_nsteps_spin.setRange(10000, 10000000)
        self.nvt_nsteps_spin.setValue(50000)
        layout.addWidget(self.nvt_nsteps_spin, 2, 1)
        layout.addWidget(QLabel("温度耦合方法 (tcoupl):"), 3, 0)
        self.nvt_tcoupl_combo = QComboBox()
        self.nvt_tcoupl_combo.addItems(['V-rescale', 'Berendsen', 'nose-hoover'])
        self.nvt_tcoupl_combo.setCurrentText('V-rescale')
        layout.addWidget(self.nvt_tcoupl_combo, 3, 1)
        layout.addWidget(QLabel("参考温度 (gen_temp):"), 4, 0)
        self.nvt_gen_temp_spin = QSpinBox()
        self.nvt_gen_temp_spin.setRange(0, 1000)
        self.nvt_gen_temp_spin.setValue(300)
        layout.addWidget(self.nvt_gen_temp_spin, 4, 1)
        
        # 添加 tc-grps 下拉选项
        layout.addWidget(QLabel("温度耦合组 (tc-grps):"), 5, 0)
        self.nvt_tc_grps_combo = QComboBox()
        self.nvt_tc_grps_combo.addItem("System", ("System", "0.1", "300"))
        self.nvt_tc_grps_combo.addItem("Protein Water_and_ions", ("Protein Water_and_ions", "0.1 0.1", "300 300"))
        self.nvt_tc_grps_combo.addItem("Protein_Membrane Water_and_ions", ("Protein_Membrane Water_and_ions", "0.1 0.1", "310 310"))
        self.nvt_tc_grps_combo.addItem("Molecule Water_and_ions", ("Molecule Water_and_ions", "0.1 0.1", "300 300"))
        self.nvt_tc_grps_combo.addItem("Solid Liquid", ("Solid Liquid", "0.1 0.1", "300 300"))
        layout.addWidget(self.nvt_tc_grps_combo, 5, 1)
        
        # 添加 tau-t 和 ref-t 可编辑输入框
        layout.addWidget(QLabel("温度时间常数 (tau-t):"), 6, 0)
        self.nvt_tau_t_edit = QLineEdit("0.1")
        layout.addWidget(self.nvt_tau_t_edit, 6, 1)
        
        layout.addWidget(QLabel("参考温度 (ref-t):"), 7, 0)
        self.nvt_ref_t_edit = QLineEdit("300")
        layout.addWidget(self.nvt_ref_t_edit, 7, 1)
        
        # 添加轨迹输出参数
        # 连接信号槽以更新 tau-t 和 ref-t 值
        self.nvt_tc_grps_combo.currentIndexChanged.connect(self.update_nvt_tc_params)
        
        layout.addWidget(QLabel("约束算法 (constraint_algorithm):"), 8, 0)
        self.nvt_constraint_algorithm_combo = QComboBox()
        self.nvt_constraint_algorithm_combo.addItems(['lincs', 'shake'])
        self.nvt_constraint_algorithm_combo.setCurrentText('lincs')
        layout.addWidget(self.nvt_constraint_algorithm_combo, 8, 1)
        layout.addWidget(QLabel("约束类型 (constraints):"), 9, 0)
        self.nvt_constraints_combo = QComboBox()
        self.nvt_constraints_combo.addItems(['none', 'all-bonds', 'h-bonds'])
        self.nvt_constraints_combo.setCurrentText('all-bonds')
        layout.addWidget(self.nvt_constraints_combo, 9, 1)
        
        # 添加轨迹输出参数
        layout.addWidget(QLabel("坐标输出频率 (nstxout):"), 10, 0)
        self.nvt_nstxout_spin = QSpinBox()
        self.nvt_nstxout_spin.setRange(0, 50000)
        self.nvt_nstxout_spin.setValue(1000)
        self.nvt_nstxout_spin.setToolTip("输出.trr文件的频率，0表示不输出")
        layout.addWidget(self.nvt_nstxout_spin, 10, 1)
        
        layout.addWidget(QLabel("能量输出频率 (nstenergy):"), 11, 0)
        self.nvt_nstenergy_spin = QSpinBox()
        self.nvt_nstenergy_spin.setRange(0, 50000)
        self.nvt_nstenergy_spin.setValue(500)
        layout.addWidget(self.nvt_nstenergy_spin, 11, 1)
        
        layout.addWidget(QLabel("日志输出频率 (nstlog):"), 12, 0)
        self.nvt_nstlog_spin = QSpinBox()
        self.nvt_nstlog_spin.setRange(0, 50000)
        self.nvt_nstlog_spin.setValue(500)
        layout.addWidget(self.nvt_nstlog_spin, 12, 1)
        
        layout.addWidget(QLabel("压缩轨迹输出频率 (nstxout-compressed):"), 13, 0)
        self.nvt_nstxtcout_spin = QSpinBox()
        self.nvt_nstxtcout_spin.setRange(0, 50000)
        self.nvt_nstxtcout_spin.setValue(1000)
        self.nvt_nstxtcout_spin.setToolTip("输出.xtc文件的频率，0表示不输出")
        layout.addWidget(self.nvt_nstxtcout_spin, 13, 1)
        
        # 添加约束参数
        layout.addWidget(QLabel("LINCS精度参数 (lincs_iter):"), 14, 0)
        self.nvt_lincs_iter_spin = QSpinBox()
        self.nvt_lincs_iter_spin.setRange(1, 20)
        self.nvt_lincs_iter_spin.setValue(1)
        layout.addWidget(self.nvt_lincs_iter_spin, 14, 1)
        
        layout.addWidget(QLabel("LINCS阶数参数 (lincs_order):"), 15, 0)
        self.nvt_lincs_order_spin = QSpinBox()
        self.nvt_lincs_order_spin.setRange(1, 10)
        self.nvt_lincs_order_spin.setValue(4)
        layout.addWidget(self.nvt_lincs_order_spin, 15, 1)
        
        # 添加继续运行参数
        layout.addWidget(QLabel("继续上一步模拟 (continuation):"), 16, 0)
        self.nvt_continuation_combo = QComboBox()
        self.nvt_continuation_combo.addItems(['yes', 'no'])
        self.nvt_continuation_combo.setCurrentText('no')
        layout.addWidget(self.nvt_continuation_combo, 16, 1)
        
        # 添加色散校正参数
        layout.addWidget(QLabel("色散校正 (DispCorr):"), 17, 0)
        self.nvt_disp_corr_combo = QComboBox()
        self.nvt_disp_corr_combo.addItems(['no', 'EnerPres', 'Ener'])
        self.nvt_disp_corr_combo.setCurrentText('EnerPres')
        layout.addWidget(self.nvt_disp_corr_combo, 17, 1)
        
        # 添加压力耦合参数（NVT中通常为no，但提供选项）
        layout.addWidget(QLabel("压力耦合方法 (pcoupl):"), 18, 0)
        self.nvt_pcoupl_combo = QComboBox()
        self.nvt_pcoupl_combo.addItems(['no', 'Berendsen', 'Parrinello-Rahman'])
        self.nvt_pcoupl_combo.setCurrentText('no')
        layout.addWidget(self.nvt_pcoupl_combo, 18, 1)
        
        # 添加随机种子参数
        layout.addWidget(QLabel("速度生成随机种子 (gen_seed):"), 19, 0)
        self.nvt_gen_seed_spin = QSpinBox()
        self.nvt_gen_seed_spin.setRange(-1, 1000000)
        self.nvt_gen_seed_spin.setValue(-1)
        self.nvt_gen_seed_spin.setSpecialValueText("随机")
        layout.addWidget(self.nvt_gen_seed_spin, 19, 1)
        
        self.nvt_posres_checkbox = QCheckBox("启用位置约束(-DPOSRES)")
        self.nvt_posres_checkbox.setChecked(True)
        layout.addWidget(self.nvt_posres_checkbox, 20, 0, 1, 2)
        self.nvt_gen_vel_checkbox = QCheckBox("生成初始速度")
        self.nvt_gen_vel_checkbox.setChecked(True)
        layout.addWidget(self.nvt_gen_vel_checkbox, 21, 0, 1, 2)
        # PBC设置组
        pbc_group = self.create_pbc_group('nvt')
        layout.addWidget(pbc_group, 22, 0, 1, 2)
        # 生成MDP按钮
        self.generate_nvt_mdp_button = QPushButton("生成NVT平衡MDP")
        layout.addWidget(self.generate_nvt_mdp_button, 24, 0, 1, 2)
        scroll_widget.setLayout(layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        self.nvt_tab.setLayout(QVBoxLayout())
        self.nvt_tab.layout().addWidget(scroll_area)
        self.sim_run_tabs.addTab(self.nvt_tab, "NVT平衡")

    def create_npt_equilibration_tab(self):
        """创建NPT平衡选项卡"""
        self.npt_tab = QWidget()
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        layout = QGridLayout(scroll_widget)
        # 参数控件
        layout.addWidget(QLabel("积分器 (integrator):"), 0, 0)
        self.npt_integrator_combo = QComboBox()
        self.npt_integrator_combo.addItems(['md', 'md-vv', 'sd', 'bd'])
        self.npt_integrator_combo.setCurrentText('md')
        layout.addWidget(self.npt_integrator_combo, 0, 1)
        layout.addWidget(QLabel("时间步长 (dt):"), 1, 0)
        self.npt_dt_spin = QDoubleSpinBox()
        self.npt_dt_spin.setRange(0.001, 0.01)
        self.npt_dt_spin.setValue(0.002)
        self.npt_dt_spin.setSuffix(" ps")
        layout.addWidget(self.npt_dt_spin, 1, 1)
        layout.addWidget(QLabel("步数 (nsteps):"), 2, 0)
        self.npt_nsteps_spin = QSpinBox()
        self.npt_nsteps_spin.setRange(10000, 10000000)
        self.npt_nsteps_spin.setValue(50000)
        layout.addWidget(self.npt_nsteps_spin, 2, 1)
        layout.addWidget(QLabel("温度耦合方法 (tcoupl):"), 3, 0)
        self.npt_tcoupl_combo = QComboBox()
        self.npt_tcoupl_combo.addItems(['V-rescale', 'Berendsen', 'nose-hoover'])
        self.npt_tcoupl_combo.setCurrentText('V-rescale')
        layout.addWidget(self.npt_tcoupl_combo, 3, 1)
        layout.addWidget(QLabel("压力耦合方法 (pcoupl):"), 4, 0)
        self.npt_pcoupl_combo = QComboBox()
        self.npt_pcoupl_combo.addItems(['no', 'Berendsen', 'Parrinello-Rahman', 'c-rescale'])
        self.npt_pcoupl_combo.setCurrentText('Berendsen')
        layout.addWidget(self.npt_pcoupl_combo, 4, 1)
        layout.addWidget(QLabel("压力耦合类型 (pcoupltype):"), 5, 0)
        self.npt_pcoupltype_combo = QComboBox()
        self.npt_pcoupltype_combo.addItems(['isotropic', 'semiisotropic', 'anisotropic', 'surface-tension'])
        self.npt_pcoupltype_combo.setCurrentText('isotropic')
        layout.addWidget(self.npt_pcoupltype_combo, 5, 1)
        layout.addWidget(QLabel("参考压力 (ref_p):"), 6, 0)
        self.npt_ref_p_spin = QDoubleSpinBox()
        self.npt_ref_p_spin.setRange(0.1, 10.0)
        self.npt_ref_p_spin.setValue(1.0)
        self.npt_ref_p_spin.setSuffix(" bar")
        layout.addWidget(self.npt_ref_p_spin, 6, 1)
        layout.addWidget(QLabel("压力时间常数 (tau_p):"), 7, 0)
        self.npt_tau_p_spin = QDoubleSpinBox()
        self.npt_tau_p_spin.setRange(0.1, 10.0)
        self.npt_tau_p_spin.setValue(2.0)
        self.npt_tau_p_spin.setSuffix(" ps")
        layout.addWidget(self.npt_tau_p_spin, 7, 1)
        layout.addWidget(QLabel("压缩系数 (compressibility):"), 8, 0)
        self.npt_compressibility_edit = QLineEdit("4.5e-5")
        layout.addWidget(self.npt_compressibility_edit, 8, 1)
        layout.addWidget(QLabel("色散校正 (DispCorr):"), 9, 0)
        self.npt_disp_corr_combo = QComboBox()
        self.npt_disp_corr_combo.addItems(['no', 'EnerPres', 'Ener'])
        self.npt_disp_corr_combo.setCurrentText('EnerPres')
        layout.addWidget(self.npt_disp_corr_combo, 9, 1)
        self.npt_continuation_checkbox = QCheckBox("继续上一步模拟(continuation=yes)")
        self.npt_continuation_checkbox.setChecked(True)
        layout.addWidget(self.npt_continuation_checkbox, 10, 0, 1, 2)
        
        # 添加 tc-grps 下拉选项
        layout.addWidget(QLabel("温度耦合组 (tc-grps):"), 11, 0)
        self.npt_tc_grps_combo = QComboBox()
        self.npt_tc_grps_combo.addItem("System", ("System", "0.1", "300"))
        self.npt_tc_grps_combo.addItem("Protein Water_and_ions", ("Protein Water_and_ions", "0.1 0.1", "300 300"))
        self.npt_tc_grps_combo.addItem("Protein_Membrane Water_and_ions", ("Protein_Membrane Water_and_ions", "0.1 0.1", "310 310"))
        self.npt_tc_grps_combo.addItem("Molecule Water_and_ions", ("Molecule Water_and_ions", "0.1 0.1", "300 300"))
        self.npt_tc_grps_combo.addItem("Solid Liquid", ("Solid Liquid", "0.1 0.1", "300 300"))
        layout.addWidget(self.npt_tc_grps_combo, 11, 1)
        
        # 添加 tau-t 和 ref-t 可编辑输入框
        layout.addWidget(QLabel("温度时间常数 (tau-t):"), 12, 0)
        self.npt_tau_t_edit = QLineEdit("0.1")
        layout.addWidget(self.npt_tau_t_edit, 12, 1)
        
        layout.addWidget(QLabel("参考温度 (ref-t):"), 13, 0)
        self.npt_ref_t_edit = QLineEdit("300")
        layout.addWidget(self.npt_ref_t_edit, 13, 1)
        
        # 连接信号槽以更新 tau-t 和 ref-t 值
        self.npt_tc_grps_combo.currentIndexChanged.connect(self.update_npt_tc_params)
        
        # 添加轨迹输出参数
        layout.addWidget(QLabel("坐标输出频率 (nstxout):"), 14, 0)
        self.npt_nstxout_spin = QSpinBox()
        self.npt_nstxout_spin.setRange(0, 50000)
        self.npt_nstxout_spin.setValue(1000)
        self.npt_nstxout_spin.setToolTip("输出.trr文件的频率，0表示不输出")
        layout.addWidget(self.npt_nstxout_spin, 14, 1)
        
        layout.addWidget(QLabel("能量输出频率 (nstenergy):"), 15, 0)
        self.npt_nstenergy_spin = QSpinBox()
        self.npt_nstenergy_spin.setRange(0, 50000)
        self.npt_nstenergy_spin.setValue(500)
        layout.addWidget(self.npt_nstenergy_spin, 15, 1)
        
        layout.addWidget(QLabel("日志输出频率 (nstlog):"), 16, 0)
        self.npt_nstlog_spin = QSpinBox()
        self.npt_nstlog_spin.setRange(0, 50000)
        self.npt_nstlog_spin.setValue(500)
        layout.addWidget(self.npt_nstlog_spin, 16, 1)
        
        layout.addWidget(QLabel("压缩轨迹输出频率 (nstxtcout):"), 17, 0)
        self.npt_nstxtcout_spin = QSpinBox()
        self.npt_nstxtcout_spin.setRange(0, 50000)
        self.npt_nstxtcout_spin.setValue(1000)
        self.npt_nstxtcout_spin.setToolTip("输出.xtc文件的频率，0表示不输出")
        layout.addWidget(self.npt_nstxtcout_spin, 17, 1)
        
        # 添加约束参数
        layout.addWidget(QLabel("LINCS精度参数 (lincs_iter):"), 18, 0)
        self.npt_lincs_iter_spin = QSpinBox()
        self.npt_lincs_iter_spin.setRange(1, 20)
        self.npt_lincs_iter_spin.setValue(1)
        layout.addWidget(self.npt_lincs_iter_spin, 18, 1)
        
        layout.addWidget(QLabel("LINCS阶数参数 (lincs_order):"), 19, 0)
        self.npt_lincs_order_spin = QSpinBox()
        self.npt_lincs_order_spin.setRange(1, 10)
        self.npt_lincs_order_spin.setValue(4)
        layout.addWidget(self.npt_lincs_order_spin, 19, 1)
        
        # 添加随机种子参数
        layout.addWidget(QLabel("速度生成随机种子 (gen_seed):"), 20, 0)
        self.npt_gen_seed_spin = QSpinBox()
        self.npt_gen_seed_spin.setRange(-1, 1000000)
        self.npt_gen_seed_spin.setValue(-1)
        self.npt_gen_seed_spin.setSpecialValueText("随机")
        layout.addWidget(self.npt_gen_seed_spin, 20, 1)
        
        # PBC设置组
        pbc_group = self.create_pbc_group('npt')
        layout.addWidget(pbc_group, 21, 0, 1, 2)
        
        # 添加弹簧以确保生成MDP按钮在最下面
        layout.addWidget(QWidget(), 22, 0, 1, 2)
        
        # 生成MDP按钮
        self.generate_npt_mdp_button = QPushButton("生成NPT平衡MDP")
        layout.addWidget(self.generate_npt_mdp_button, 23, 0, 1, 2)
        scroll_widget.setLayout(layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        self.npt_tab.setLayout(QVBoxLayout())
        self.npt_tab.layout().addWidget(scroll_area)
        self.sim_run_tabs.addTab(self.npt_tab, "NPT平衡")

    def create_production_md_tab(self):
        """创建生产运行MD选项卡"""
        self.prod_tab = QWidget()
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        layout = QGridLayout(scroll_widget)
        # 积分器参数
        layout.addWidget(QLabel("积分器 (integrator):"), 0, 0)
        self.prod_integrator_combo = QComboBox()
        self.prod_integrator_combo.addItems(['md', 'md-vv', 'sd', 'bd'])
        self.prod_integrator_combo.setCurrentText('md')
        layout.addWidget(self.prod_integrator_combo, 0, 1)
        # 时间参数
        layout.addWidget(QLabel("时间步长 (dt, ps):"), 1, 0)
        self.prod_dt_spin = QDoubleSpinBox()
        self.prod_dt_spin.setRange(0.001, 0.002)
        self.prod_dt_spin.setValue(0.002)
        self.prod_dt_spin.setDecimals(3)
        layout.addWidget(self.prod_dt_spin, 1, 1)
        layout.addWidget(QLabel("步数 (nsteps):"), 2, 0)
        self.prod_nsteps_spin = QSpinBox()
        self.prod_nsteps_spin.setRange(1000, 10000000)
        self.prod_nsteps_spin.setValue(500000)
        layout.addWidget(self.prod_nsteps_spin, 2, 1)
        
        # 输出频率参数
        layout.addWidget(QLabel("日志输出频率 (nstlog):"), 3, 0)
        self.prod_nstlog_spin = QSpinBox()
        self.prod_nstlog_spin.setRange(0, 100000)
        self.prod_nstlog_spin.setValue(1000)
        layout.addWidget(self.prod_nstlog_spin, 3, 1)
        
        layout.addWidget(QLabel("能量输出频率 (nstenergy):"), 4, 0)
        self.prod_nstenergy_spin = QSpinBox()
        self.prod_nstenergy_spin.setRange(0, 100000)
        self.prod_nstenergy_spin.setValue(1000)
        layout.addWidget(self.prod_nstenergy_spin, 4, 1)
        
        # 温度耦合方法
        layout.addWidget(QLabel("温度耦合方法 (tcoupl):"), 5, 0)
        self.prod_tcoupl_combo = QComboBox()
        self.prod_tcoupl_combo.addItems(['V-rescale', 'Berendsen', 'nose-hoover'])
        self.prod_tcoupl_combo.setCurrentText('V-rescale')
        layout.addWidget(self.prod_tcoupl_combo, 5, 1)
        # 温度耦合组
        layout.addWidget(QLabel("温度耦合组 (tc-grps):"), 6, 0)
        self.prod_tc_grps_combo = QComboBox()
        # 添加预设选项，每个选项包含组名、tau_t和ref_t
        self.prod_tc_grps_combo.addItem("Protein Water_and_ions", ("Protein Water_and_ions", "0.1 0.1", "300 300"))
        self.prod_tc_grps_combo.addItem("Protein Non-Protein", ("Protein Non-Protein", "0.1 0.1", "300 300"))
        self.prod_tc_grps_combo.addItem("System", ("System", "0.1", "300"))
        self.prod_tc_grps_combo.addItem("Protein Water Ions", ("Protein Water Ions", "0.1 0.1 0.1", "300 300 300"))
        self.prod_tc_grps_combo.setCurrentText("Protein Water_and_ions")
        # 连接信号
        self.prod_tc_grps_combo.currentTextChanged.connect(self.update_prod_tc_params)
        layout.addWidget(self.prod_tc_grps_combo, 6, 1)
        # tau_t 和 ref_t
        layout.addWidget(QLabel("温度耦合时间常数 (tau_t, ps):"), 7, 0)
        self.prod_tau_t_edit = QLineEdit("0.1 0.1")
        layout.addWidget(self.prod_tau_t_edit, 7, 1)
        layout.addWidget(QLabel("参考温度 (ref_t, K):"), 8, 0)
        self.prod_ref_t_edit = QLineEdit("300 300")
        layout.addWidget(self.prod_ref_t_edit, 8, 1)
        # 压力耦合
        layout.addWidget(QLabel("压力耦合方法 (pcoupl):"), 9, 0)
        self.prod_pcoupl_combo = QComboBox()
        self.prod_pcoupl_combo.addItems(['no', 'Berendsen', 'Parrinello-Rahman'])
        self.prod_pcoupl_combo.setCurrentText('Parrinello-Rahman')
        layout.addWidget(self.prod_pcoupl_combo, 9, 1)
        layout.addWidget(QLabel("压力耦合类型 (pcoupltype):"), 10, 0)
        self.prod_pcoupltype_combo = QComboBox()
        self.prod_pcoupltype_combo.addItems(['isotropic', 'anisotropic', 'semiisotropic'])
        self.prod_pcoupltype_combo.setCurrentText('isotropic')
        layout.addWidget(self.prod_pcoupltype_combo, 10, 1)
        layout.addWidget(QLabel("压力耦合时间常数 (tau_p, ps):"), 11, 0)
        self.prod_tau_p_spin = QDoubleSpinBox()
        self.prod_tau_p_spin.setRange(0.1, 5.0)
        self.prod_tau_p_spin.setValue(1.0)
        self.prod_tau_p_spin.setDecimals(1)
        layout.addWidget(self.prod_tau_p_spin, 11, 1)
        layout.addWidget(QLabel("参考压力 (ref_p, bar):"), 12, 0)
        self.prod_ref_p_spin = QDoubleSpinBox()
        self.prod_ref_p_spin.setRange(0.0, 1000.0)
        self.prod_ref_p_spin.setValue(1.0)
        self.prod_ref_p_spin.setDecimals(1)
        layout.addWidget(self.prod_ref_p_spin, 12, 1)
        layout.addWidget(QLabel("压缩系数 (compressibility):"), 13, 0)
        self.prod_compressibility_edit = QLineEdit("4.5e-5")
        layout.addWidget(self.prod_compressibility_edit, 13, 1)
        # 添加色散校正控件
        layout.addWidget(QLabel("色散校正 (DispCorr):"), 14, 0)
        self.prod_disp_corr_combo = QComboBox()
        self.prod_disp_corr_combo.addItems(['no', 'EnerPres', 'Ener'])
        self.prod_disp_corr_combo.setCurrentText('EnerPres')
        layout.addWidget(self.prod_disp_corr_combo, 14, 1)
        # 约束参数
        constraint_group = QGroupBox("约束参数")
        constraint_layout = QGridLayout(constraint_group)
        constraint_layout.addWidget(QLabel("约束算法 (constraint-algorithm):"), 0, 0)
        self.prod_constraint_algorithm_combo = QComboBox()
        self.prod_constraint_algorithm_combo.addItems(['Lincs', 'Shake'])
        self.prod_constraint_algorithm_combo.setCurrentText('Lincs')
        constraint_layout.addWidget(self.prod_constraint_algorithm_combo, 0, 1)
        constraint_layout.addWidget(QLabel("约束类型 (constraints):"), 1, 0)
        self.prod_constraints_combo = QComboBox()
        self.prod_constraints_combo.addItems(['none', 'h-bonds', 'all-bonds', 'h-angles'])
        self.prod_constraints_combo.setCurrentText('h-bonds')
        constraint_layout.addWidget(self.prod_constraints_combo, 1, 1)
        layout.addWidget(constraint_group, 15, 0, 1, 2)
        # 添加继续运行参数
        layout.addWidget(QLabel("继续上一步模拟 (continuation):"), 16, 0)
        self.prod_continuation_combo = QComboBox()
        self.prod_continuation_combo.addItems(['yes', 'no'])
        self.prod_continuation_combo.setCurrentText('yes')
        layout.addWidget(self.prod_continuation_combo, 16, 1)
        # 添加随机种子参数
        layout.addWidget(QLabel("速度生成随机种子 (gen_seed):"), 17, 0)
        self.prod_gen_seed_spin = QSpinBox()
        self.prod_gen_seed_spin.setRange(-1, 1000000)
        self.prod_gen_seed_spin.setValue(-1)
        self.prod_gen_seed_spin.setSpecialValueText("随机")
        layout.addWidget(self.prod_gen_seed_spin, 17, 1)
        
        # 轨迹输出参数
        traj_group = QGroupBox("轨迹输出参数")
        traj_layout = QGridLayout(traj_group)
        traj_layout.addWidget(QLabel("坐标输出频率 (nstxout):"), 0, 0)
        self.prod_nstxout_spin = QSpinBox()
        self.prod_nstxout_spin.setRange(0, 100000)
        self.prod_nstxout_spin.setValue(0)
        traj_layout.addWidget(self.prod_nstxout_spin, 0, 1)
        traj_layout.addWidget(QLabel("压缩轨迹输出频率 (nstxout-compressed):"), 1, 0)
        self.prod_nstxtcout_spin = QSpinBox()
        self.prod_nstxtcout_spin.setRange(0, 100000)
        self.prod_nstxtcout_spin.setValue(5000)
        traj_layout.addWidget(self.prod_nstxtcout_spin, 1, 1)
        layout.addWidget(traj_group, 18, 0, 1, 2)
        
        # 约束精度参数
        constraint_params_group = QGroupBox("LINCS约束精度参数")
        constraint_params_layout = QGridLayout(constraint_params_group)
        constraint_params_layout.addWidget(QLabel("LINCS精度参数 (lincs_iter):"), 0, 0)
        self.prod_lincs_iter_spin = QSpinBox()
        self.prod_lincs_iter_spin.setRange(1, 20)
        self.prod_lincs_iter_spin.setValue(1)
        constraint_params_layout.addWidget(self.prod_lincs_iter_spin, 0, 1)
        constraint_params_layout.addWidget(QLabel("LINCS阶数参数 (lincs_order):"), 1, 0)
        self.prod_lincs_order_spin = QSpinBox()
        self.prod_lincs_order_spin.setRange(1, 10)
        self.prod_lincs_order_spin.setValue(4)
        constraint_params_layout.addWidget(self.prod_lincs_order_spin, 1, 1)
        layout.addWidget(constraint_params_group, 19, 0, 1, 2)
        # 位置约束选项
        self.prod_posres_checkbox = QCheckBox("启用位置约束(-DPOSRES)")
        self.prod_posres_checkbox.setChecked(False)  # 默认不启用位置约束
        layout.addWidget(self.prod_posres_checkbox, 20, 0, 1, 2)
        # PBC设置组
        pbc_group = self.create_pbc_group('md')
        layout.addWidget(pbc_group, 21, 0, 1, 2)
        # 添加弹簧以确保生成MDP按钮在最下面
        layout.addWidget(QWidget(), 22, 0, 1, 2)
        # 生成MDP按钮
        self.generate_prod_mdp_button = QPushButton("生成生产运行MDP")
        layout.addWidget(self.generate_prod_mdp_button, 23, 0, 1, 2)
        scroll_widget.setLayout(layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        self.prod_tab.setLayout(QVBoxLayout())
        self.prod_tab.layout().addWidget(scroll_area)
        self.sim_run_tabs.addTab(self.prod_tab, "生产运行")

    def create_mdp_search_tab(self):
        """创建MDP参数搜索选项卡"""
        self.mdp_search_tab = QWidget()
        layout = QVBoxLayout(self.mdp_search_tab)
        
        # 添加说明
        info_label = QLabel("MDP参数搜索：输入关键词搜索MDP参数的详细说明")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        layout.addWidget(info_label)
        
        # 搜索区域
        search_group = QGroupBox("参数搜索")
        search_layout = QHBoxLayout(search_group)
        
        search_layout.addWidget(QLabel("搜索关键词:"))
        self.mdp_search_edit = QLineEdit()
        self.mdp_search_edit.setPlaceholderText("输入参数名称或相关关键词...")
        search_layout.addWidget(self.mdp_search_edit)
        
        self.mdp_search_btn = QPushButton("搜索")
        search_layout.addWidget(self.mdp_search_btn)
        
        layout.addWidget(search_group)
        
        # 搜索结果区域
        result_group = QGroupBox("搜索结果")
        result_layout = QVBoxLayout(result_group)
        
        self.mdp_search_results = QTextEdit()
        self.mdp_search_results.setReadOnly(True)
        result_layout.addWidget(self.mdp_search_results)
        
        layout.addWidget(result_group)
        
        # 连接信号
        # 移除这里过早的信号连接，让connect_signals方法统一处理
        # self.mdp_search_btn.clicked.connect(self.search_mdp_parameters)
        # self.mdp_search_edit.returnPressed.connect(self.search_mdp_parameters)
        
        self.tools_tabs.addTab(self.mdp_search_tab, "MDP参数搜索")
        
    def search_mdp_parameters(self):
        """搜索MDP参数"""
        keyword = self.mdp_search_edit.text().strip().lower()
        if not keyword:
            self.mdp_search_results.setPlainText("请输入搜索关键词")
            return
            
        # 从MDP_KNOWLEDGE_BASE中搜索匹配的参数
        results = []
        for param in MDP_KNOWLEDGE_BASE:
            # 检查关键词是否在参数的任何字段中
            match = False
            for key, value in param.items():
                if isinstance(value, str) and keyword in value.lower():
                    match = True
                    break
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and keyword in item.lower():
                            match = True
                            break
                    if match:
                        break
                        
            if match:
                results.append(param)
                
        # 显示搜索结果
        if results:
            result_text = f"找到 {len(results)} 个匹配的参数:\n\n"
            for param in results:
                result_text += f"参数名称: {param['title']} ({param['key']})\n"
                result_text += f"语法: {param['syntax']}\n"
                result_text += f"描述: {param['description']}\n"
                result_text += f"可选值: {param['values']}\n"
                result_text += f"使用场景: {param['when_to_use']}\n"
                result_text += f"影响: {param['effects']}\n"
                result_text += f"示例: {param['examples']}\n"
                if param['notes']:
                    result_text += f"注意事项: {param['notes']}\n"
                result_text += "-" * 50 + "\n\n"
                
            self.mdp_search_results.setPlainText(result_text)
        else:
            self.mdp_search_results.setPlainText(f"未找到包含关键词 '{keyword}' 的参数")
            
    def update_nvt_tc_params(self):
        """更新NVT温度耦合参数显示"""
        data = self.nvt_tc_grps_combo.currentData()
        if data:
            _, tau_t, ref_t = data
            self.nvt_tau_t_edit.setText(tau_t)
            self.nvt_ref_t_edit.setText(ref_t)

    def update_npt_tc_params(self):
        """更新NPT温度耦合参数显示"""
        data = self.npt_tc_grps_combo.currentData()
        if data:
            _, tau_t, ref_t = data
            self.npt_tau_t_edit.setText(tau_t)
            self.npt_ref_t_edit.setText(ref_t)

    def update_prod_tc_params(self):
        """更新生产运行温度耦合参数显示"""
        data = self.prod_tc_grps_combo.currentData()
        if data:
            _, tau_t, ref_t = data
            self.prod_tau_t_edit.setText(tau_t)
            self.prod_ref_t_edit.setText(ref_t)

    def create_cmd_preview_tab(self):
        """创建命令预览选项卡"""
        self.cmd_preview_tab = QWidget()
        layout = QVBoxLayout(self.cmd_preview_tab)
        
        # 添加说明文本 - 提示用户可以手动编辑命令
        info_label = QLabel("命令预览：显示将要执行的GROMACS命令，您可以直接编辑命令后点击执行")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        layout.addWidget(info_label)
        
        # 命令预览区域 - 设置为可编辑
        self.cmd_preview_text = QTextEdit()
        self.cmd_preview_text.setReadOnly(False)
        self.cmd_preview_text.setFont(QFont("Courier", 10))
        self.cmd_preview_text.setStyleSheet("QTextEdit { background-color: #fafafa; border: 1px solid #ccc; }")
        layout.addWidget(self.cmd_preview_text)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        self.generate_command_btn = QPushButton("生成命令")
        self.generate_command_btn.setStyleSheet(self._btn_secondary)
        self.execute_command_btn = QPushButton("执行命令")
        self.execute_command_btn.setStyleSheet(self._btn_primary)
        self.copy_command_btn = QPushButton("复制命令")
        self.copy_command_btn.setStyleSheet(self._btn_tool)
        self.save_script_btn = QPushButton("保存脚本")
        self.save_script_btn.setStyleSheet(self._btn_tool)
        button_layout.addWidget(self.generate_command_btn)
        button_layout.addWidget(self.execute_command_btn)
        button_layout.addWidget(self.copy_command_btn)
        button_layout.addWidget(self.save_script_btn)
        layout.addLayout(button_layout)
        
        # 命令选项区域 - 重新组织布局
        self.mdrun_options_group = QGroupBox("MDRun选项")
        
        # 使用分组布局
        main_layout = QVBoxLayout(self.mdrun_options_group)
        
        # ===== 第1行：计算设备选择 =====
        device_group = QGroupBox("计算设备")
        device_layout = QHBoxLayout(device_group)
        
        device_layout.addWidget(QLabel("计算模式:"))
        self.compute_mode_combo = QComboBox()
        self.compute_mode_combo.addItems(["自动检测", "GPU加速(推荐)", "仅CPU"])
        self.compute_mode_combo.setCurrentIndex(0)
        device_layout.addWidget(self.compute_mode_combo)
        
        self.gpu_info_label = QLabel("检测GPU...")
        self.gpu_info_label.setStyleSheet("color: #666; font-size: 10px;")
        device_layout.addWidget(self.gpu_info_label)
        
        device_layout.addStretch()
        main_layout.addWidget(device_group)
        
        # ===== 第2行：MPI和GPU =====
        row1_layout = QHBoxLayout()
        
        # MPI选项
        mpi_widget = QWidget()
        mpi_layout = QHBoxLayout(mpi_widget)
        mpi_layout.setContentsMargins(0, 0, 0, 0)
        self.mpi_checkbox = QCheckBox("使用MPI")
        mpi_layout.addWidget(self.mpi_checkbox)
        mpi_layout.addWidget(QLabel("进程数:"))
        self.mpi_np_spinbox = QSpinBox()
        self.mpi_np_spinbox.setRange(1, 64)
        self.mpi_np_spinbox.setValue(1)
        self.mpi_np_spinbox.setEnabled(False)
        self.mpi_np_spinbox.setPrefix("np ")
        self.mpi_np_spinbox.setMaximumWidth(80)
        mpi_layout.addWidget(self.mpi_np_spinbox)
        row1_layout.addWidget(mpi_widget)
        
        # GPU选项
        gpu_widget = QWidget()
        gpu_layout = QHBoxLayout(gpu_widget)
        gpu_layout.setContentsMargins(0, 0, 0, 0)
        gpu_layout.addWidget(QLabel("GPU ID:"))
        self.gpu_edit = QLineEdit()
        self.gpu_edit.setPlaceholderText("0")
        self.gpu_edit.setMaximumWidth(60)
        gpu_layout.addWidget(self.gpu_edit)
        row1_layout.addWidget(gpu_widget)
        
        # 最大运行时间
        time_widget = QWidget()
        time_layout = QHBoxLayout(time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.addWidget(QLabel("最大运行:"))
        self.maxh_spinbox = QDoubleSpinBox()
        self.maxh_spinbox.setRange(0, 1000)
        self.maxh_spinbox.setValue(0)
        self.maxh_spinbox.setSpecialValueText("无限制")
        self.maxh_spinbox.setSuffix(" h")
        self.maxh_spinbox.setMaximumWidth(100)
        time_layout.addWidget(self.maxh_spinbox)
        row1_layout.addWidget(time_widget)
        
        main_layout.addLayout(row1_layout)
        
        # ===== 第3行：CPU线程设置 =====
        thread_group = QGroupBox("CPU/线程设置")
        thread_layout = QGridLayout(thread_group)
        
        # 总线程数
        thread_layout.addWidget(QLabel("总线程(-nt):"), 0, 0)
        self.nt_spinbox = QSpinBox()
        self.nt_spinbox.setRange(0, 128)
        self.nt_spinbox.setValue(0)
        self.nt_spinbox.setSpecialValueText("自动")
        self.nt_spinbox.setMaximumWidth(80)
        thread_layout.addWidget(self.nt_spinbox, 0, 1)
        
        # OpenMP线程
        thread_layout.addWidget(QLabel("OpenMP(-ntomp):"), 0, 2)
        self.ntomp_spinbox = QSpinBox()
        self.ntomp_spinbox.setRange(0, 64)
        self.ntomp_spinbox.setValue(0)
        self.ntomp_spinbox.setSpecialValueText("自动")
        self.ntomp_spinbox.setMaximumWidth(80)
        thread_layout.addWidget(self.ntomp_spinbox, 0, 3)
        
        # 线程绑定
        thread_layout.addWidget(QLabel("线程绑定(-pin):"), 1, 0)
        self.pin_combo = QComboBox()
        self.pin_combo.addItems(["自动", "on", "off"])
        self.pin_combo.setCurrentIndex(0)
        self.pin_combo.setMaximumWidth(80)
        thread_layout.addWidget(self.pin_combo, 1, 1)
        
        # 绑定偏移
        thread_layout.addWidget(QLabel("绑定偏移(-pinoffset):"), 1, 2)
        self.pinoffset_spinbox = QSpinBox()
        self.pinoffset_spinbox.setRange(0, 64)
        self.pinoffset_spinbox.setValue(0)
        self.pinoffset_spinbox.setMaximumWidth(80)
        thread_layout.addWidget(self.pinoffset_spinbox, 1, 3)
        
        main_layout.addWidget(thread_group)
        
        # ===== 第4行：计算选项 =====
        compute_group = QGroupBox("计算选项")
        compute_layout = QGridLayout(compute_group)
        
        # 非键计算
        compute_layout.addWidget(QLabel("非键计算(-nb):"), 0, 0)
        self.nb_combo = QComboBox()
        self.nb_combo.addItems(["自动", "gpu", "cpu"])
        self.nb_combo.setCurrentIndex(0)
        self.nb_combo.setMaximumWidth(80)
        compute_layout.addWidget(self.nb_combo, 0, 1)
        
        # PME计算
        compute_layout.addWidget(QLabel("PME计算(-pme):"), 0, 2)
        self.pme_combo = QComboBox()
        self.pme_combo.addItems(["自动", "gpu", "cpu"])
        self.pme_combo.setCurrentIndex(0)
        self.pme_combo.setMaximumWidth(80)
        compute_layout.addWidget(self.pme_combo, 0, 3)
        
        # 动态负载均衡
        compute_layout.addWidget(QLabel("动态负载(-dlb):"), 1, 0)
        self.dlb_combo = QComboBox()
        self.dlb_combo.addItems(["自动", "yes", "no"])
        self.dlb_combo.setCurrentIndex(0)
        self.dlb_combo.setMaximumWidth(80)
        compute_layout.addWidget(self.dlb_combo, 1, 1)
        
        # 输出间隔
        compute_layout.addWidget(QLabel("输出间隔(-stepout):"), 1, 2)
        self.stepout_spinbox = QSpinBox()
        self.stepout_spinbox.setRange(0, 100000)
        self.stepout_spinbox.setValue(1000)
        self.stepout_spinbox.setMaximumWidth(80)
        compute_layout.addWidget(self.stepout_spinbox, 1, 3)
        
        main_layout.addWidget(compute_group)
        
        # ===== 第5行：输出控制 =====
        output_group = QGroupBox("输出控制")
        output_layout = QHBoxLayout(output_group)
        
        self.append_checkbox = QCheckBox("追加输出(-append)")
        self.append_checkbox.setChecked(True)
        output_layout.addWidget(self.append_checkbox)
        
        output_layout.addWidget(QLabel("检查点间隔(-cpt):"))
        self.cpt_spinbox = QSpinBox()
        self.cpt_spinbox.setRange(0, 60)
        self.cpt_spinbox.setValue(15)
        self.cpt_spinbox.setSuffix(" 分钟")
        self.cpt_spinbox.setMaximumWidth(100)
        output_layout.addWidget(self.cpt_spinbox)
        
        output_layout.addStretch()
        main_layout.addWidget(output_group)
        
        # 初始化默认参数和GPU检测
        self.init_mdrun_defaults()
        
        # 连接参数关联信号
        self.compute_mode_combo.currentIndexChanged.connect(self.on_compute_mode_changed)
        self.gpu_edit.textChanged.connect(self.on_gpu_id_changed)
        
        # 连接信号
        # 移除这里过早的信号连接，让connect_signals方法统一处理
        # self.mpi_checkbox.stateChanged.connect(self.toggle_mpi_options)
        
        layout.addWidget(self.mdrun_options_group)
        
        # 只添加一次命令预览选项卡，使用语言管理器，提供默认值
        tab_text = self.lang_manager.get_text('command_preview')
        if tab_text is None:
            tab_text = "命令预览"
        self.output_tab_widget.addTab(self.cmd_preview_tab, tab_text)
        ############################
    
    def init_mdrun_defaults(self):
        """初始化MDRun默认参数"""
        import platform
        import os
        
        # 检测WSL
        is_wsl = False
        try:
            result = subprocess.run(['uname', '-r'], capture_output=True, text=True, timeout=5)
            if 'WSL' in result.stdout or 'Microsoft' in result.stdout:
                is_wsl = True
        except:
            pass
        
        # WSL环境下默认关闭线程绑定
        if is_wsl and hasattr(self, 'pin_combo'):
            self.pin_combo.setCurrentText("off")
        
        # 检测GPU可用性
        gpu_info = self.detect_gpu_availability()
        self.update_gpu_info_display(gpu_info)
        
        # 根据GPU检测结果设置默认计算模式
        if hasattr(self, 'compute_mode_combo'):
            if gpu_info['has_gpu']:
                # 有GPU，默认使用GPU加速
                self.compute_mode_combo.setCurrentIndex(1)  # GPU加速(推荐)
            else:
                # 无GPU，使用CPU
                self.compute_mode_combo.setCurrentIndex(2)  # 仅CPU
        
        # 设置推荐的线程数
        n_cores = os.cpu_count() or 4
        if hasattr(self, 'nt_spinbox') and self.nt_spinbox.value() == 0:
            self.nt_spinbox.setValue(n_cores)
    
    def detect_gpu_availability(self):
        """检测系统GPU情况"""
        gpus = []
        has_nvidia = False
        
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=index,name,memory.total', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                has_nvidia = True
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(', ')
                        if len(parts) >= 3:
                            gpu_id = parts[0].strip()
                            gpu_name = parts[1].strip()
                            gpu_mem = parts[2].replace('MiB', '').strip()
                            gpus.append({
                                'id': gpu_id,
                                'name': gpu_name,
                                'memory': int(gpu_mem)
                            })
        except:
            pass
        
        return {
            'has_gpu': has_nvidia and len(gpus) > 0,
            'gpus': gpus,
            'gpu_count': len(gpus)
        }
    
    def update_gpu_info_display(self, gpu_info):
        """更新GPU信息显示"""
        if not hasattr(self, 'gpu_info_label'):
            return
            
        if gpu_info['has_gpu'] and gpu_info['gpus']:
            gpu = gpu_info['gpus'][0]
            self.gpu_info_label.setText(f"✓ 检测到GPU: {gpu['name']} ({gpu['memory']}MB)")
            self.gpu_info_label.setStyleSheet("color: green; font-size: 10px;")
        else:
            self.gpu_info_label.setText("✗ 未检测到NVIDIA GPU")
            self.gpu_info_label.setStyleSheet("color: red; font-size: 10px;")
    
    def on_compute_mode_changed(self, index):
        """计算模式改变时的关联逻辑"""
        mode_text = self.compute_mode_combo.currentText() if hasattr(self, 'compute_mode_combo') else ""
        
        # 模式: 0=自动检测, 1=GPU加速, 2=仅CPU
        if index == 1:  # GPU加速
            # 设置GPU相关参数
            if hasattr(self, 'nb_combo'):
                self.nb_combo.setCurrentText("gpu")
            if hasattr(self, 'pme_combo'):
                self.pme_combo.setCurrentText("gpu")
            
            # 自动检测GPU并设置ID
            gpu_info = self.detect_gpu_availability()
            if gpu_info['has_gpu'] and hasattr(self, 'gpu_edit'):
                self.gpu_edit.setText("0")
                self.gpu_edit.setEnabled(True)
            
            # GPU模式建议 ntomp=1
            if hasattr(self, 'ntomp_spinbox'):
                self.ntomp_spinbox.setValue(1)
                
        elif index == 2:  # 仅CPU
            # 设置CPU相关参数
            if hasattr(self, 'nb_combo'):
                self.nb_combo.setCurrentText("cpu")
            if hasattr(self, 'pme_combo'):
                self.pme_combo.setCurrentText("cpu")
            
            # 禁用GPU ID输入
            if hasattr(self, 'gpu_edit'):
                self.gpu_edit.setEnabled(False)
                
        else:  # 自动检测
            gpu_info = self.detect_gpu_availability()
            if gpu_info['has_gpu']:
                if hasattr(self, 'nb_combo'):
                    self.nb_combo.setCurrentText("自动")
                if hasattr(self, 'pme_combo'):
                    self.pme_combo.setCurrentText("自动")
                if hasattr(self, 'gpu_edit'):
                    self.gpu_edit.setEnabled(True)
            else:
                if hasattr(self, 'nb_combo'):
                    self.nb_combo.setCurrentText("cpu")
                if hasattr(self, 'pme_combo'):
                    self.pme_combo.setCurrentText("cpu")
                if hasattr(self, 'gpu_edit'):
                    self.gpu_edit.setEnabled(False)
    
    def on_gpu_id_changed(self, text):
        """GPU ID变化时的关联逻辑"""
        if hasattr(self, 'nb_combo') and hasattr(self, 'gpu_edit'):
            if text.strip():
                # 设置了GPU，nb自动设为gpu
                self.nb_combo.setCurrentText("gpu")
        
    def create_realtime_output_tab(self):
        """创建实时输出选项卡"""
        self.realtime_output_tab = QWidget()
        layout = QVBoxLayout(self.realtime_output_tab)
        # 输出显示区域
        self.output_display = QPlainTextEdit()
        self.output_display.setReadOnly(True)
        layout.addWidget(self.output_display)
        # 控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始执行")
        self.stop_btn = QPushButton("停止执行")
        self.stop_btn.setEnabled(False)
        self.clear_output_btn = QPushButton("清空输出")
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.clear_output_btn)
        layout.addLayout(control_layout)
        # 进度指示
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.status_label = QLabel("就绪")
        progress_layout.addWidget(QLabel("状态:"))
        progress_layout.addWidget(self.status_label)
        layout.addLayout(progress_layout)
        
        # 添加进程监控表格
        self.process_monitor_group = QGroupBox("进程监控")
        # 设置字体大小
        font = self.process_monitor_group.font()
        font.setPointSize(8)  # 减小字体
        self.process_monitor_group.setFont(font)
        
        process_monitor_layout = QVBoxLayout(self.process_monitor_group)
        
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(6)
        self.process_table.setHorizontalHeaderLabels(["PID", "命令", "CPU%", "内存%", "状态", "操作"])
        self.process_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.process_table.horizontalHeader().setStretchLastSection(True)
        self.process_table.verticalHeader().setVisible(False)
        # 设置表格字体大小
        table_font = self.process_table.font()
        table_font.setPointSize(8)  # 减小字体
        self.process_table.setFont(table_font)
        process_monitor_layout.addWidget(self.process_table)
        
        # 设置进程监控组的最大高度为窗口高度的1/5
        self.process_monitor_group.setMaximumHeight(120)  # 大约是窗口高度的1/5
        
        layout.addWidget(self.process_monitor_group)
        
        # 初始化进程监控定时器
        self.process_monitor_timer = QTimer()
        self.process_monitor_timer.timeout.connect(self.update_process_monitor)
        self.process_monitor_timer.start(2000)  # 每2秒刷新一次
        
        self.output_tab_widget.addTab(self.realtime_output_tab, "实时输出")

    def create_execution_log_tab(self):
        """创建执行日志选项卡"""
        self.log_tab = QWidget()
        layout = QVBoxLayout(self.log_tab)
        # 日志输出
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        # 清空日志按钮
        self.clear_log_button = QPushButton("清空日志")
        layout.addWidget(self.clear_log_button)
        self.output_tab_widget.addTab(self.log_tab, "执行日志")

    def create_file_status_tab(self):
        """创建文件状态选项卡"""
        self.file_status_tab = QWidget()
        layout = QVBoxLayout(self.file_status_tab)
        
        # 文件列表区域
        file_list_group = QGroupBox("生成文件状态")
        file_list_layout = QVBoxLayout(file_list_group)
        
        # 文件列表滚动区域
        self.file_list_scroll = QScrollArea()
        self.file_list_scroll.setWidgetResizable(True)
        self.file_list_widget = QWidget()
        self.file_list_layout = QVBoxLayout(self.file_list_widget)
        self.file_list_layout.addStretch()
        self.file_list_scroll.setWidget(self.file_list_widget)
        file_list_layout.addWidget(self.file_list_scroll)
        
        layout.addWidget(file_list_group)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        self.update_file_status_btn = QPushButton("更新文件状态")
        self.preview_file_btn = QPushButton("文件预览")
        # 移除这里过早的信号连接，让connect_signals方法统一处理
        # self.update_file_status_btn.clicked.connect(self.update_file_status)
        # self.preview_file_btn.clicked.connect(self.preview_selected_file)
        control_layout.addWidget(self.update_file_status_btn)
        control_layout.addWidget(self.preview_file_btn)
        layout.addLayout(control_layout)
        
        # 只添加一次文件状态选项卡，使用语言管理器，提供默认值
        tab_text = self.lang_manager.get_text('file_status')
        if tab_text is None:
            tab_text = "文件状态"
        self.output_tab_widget.addTab(self.file_status_tab, tab_text)
        
        # 存储当前选中的文件按钮
        self.selected_file_button = None
        self.file_buttons = []

    def update_process_monitor(self):
        """更新进程监控表格"""
        if not PSUTIL_AVAILABLE:
            return
            
        try:
            # 清空表格
            self.process_table.setRowCount(0)
            
            # 查找所有gmx mdrun进程
            row = 0
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_percent', 'status']):
                try:
                    # 检查是否是gmx mdrun进程
                    if 'gmx' in proc.info['name'].lower() and 'mdrun' in ' '.join(proc.info['cmdline']).lower():
                        # 添加新行
                        self.process_table.insertRow(row)
                        
                        # PID
                        pid_item = QTableWidgetItem(str(proc.info['pid']))
                        self.process_table.setItem(row, 0, pid_item)
                        
                        # 命令
                        cmd_item = QTableWidgetItem(' '.join(proc.info['cmdline']))
                        self.process_table.setItem(row, 1, cmd_item)
                        
                        # CPU%
                        cpu_item = QTableWidgetItem(f"{proc.info['cpu_percent']:.1f}")
                        self.process_table.setItem(row, 2, cpu_item)
                        
                        # 内存%
                        mem_item = QTableWidgetItem(f"{proc.info['memory_percent']:.1f}")
                        self.process_table.setItem(row, 3, mem_item)
                        
                        # 状态
                        status_item = QTableWidgetItem(proc.info['status'])
                        self.process_table.setItem(row, 4, status_item)
                        
                        # 操作按钮
                        kill_btn = QPushButton("终止")
                        kill_btn.clicked.connect(lambda checked, p=proc.info['pid']: self.kill_process(p))
                        self.process_table.setCellWidget(row, 5, kill_btn)
                        
                        row += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # 进程可能已经结束或无权限访问
                    continue
        except Exception as e:
            print(f"更新进程监控时出错: {e}")

    def kill_process(self, pid):
        """终止指定PID的进程"""
        if not PSUTIL_AVAILABLE:
            return
            
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            # 等待进程结束，如果超时则强制杀死
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait()
            # 更新监控表格
            self.update_process_monitor()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            QMessageBox.warning(self, "警告", f"无法终止进程 {pid}: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"终止进程时出错: {str(e)}")

    def create_language_settings_tab(self):
        """创建语言设置选项卡"""
        self.language_tab = QWidget()
        layout = QVBoxLayout(self.language_tab)
        
        # 主标题
        title_label = QLabel("[+] Language / 语言设置")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #2c3e50;
                padding: 20px;
                text-align: center;
            }
        """)
        layout.addWidget(title_label)
        
        # 语言选择器
        self.language_combo = QComboBox()
        self.language_combo.addItems(["English", "简体中文", "繁体中文"])
        self.language_combo.currentIndexChanged.connect(self.on_language_changed)
        layout.addWidget(self.language_combo)
        
        # 健康检查信息
        self.health_summary_label = QLabel("系统状态检查中...")
        self.health_summary_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
                text-align: center;
            }
        """)
        self.health_summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 语言选择组
        language_group = QGroupBox(self.lang_manager.get_text('current_language'))
        language_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                margin-top: 20px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                background-color: #f8f9fa;
            }
        """)
        
        language_layout = QVBoxLayout(language_group)
        language_layout.setSpacing(15)
        
        # 当前语言显示
        current_lang_layout = QHBoxLayout()
        current_lang_label = QLabel(self.lang_manager.get_text('current_language'))
        current_lang_label.setStyleSheet("font-size: 12px; color: #34495e;")
        
        self.current_language_display = QLabel()
        self.update_current_language_display()
        self.current_language_display.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: bold;
                color: #27ae60;
                background-color: #e8f5e8;
                padding: 5px 10px;
                border-radius: 4px;
                border: 1px solid #27ae60;
            }
        """)
        
        current_lang_layout.addWidget(current_lang_label)
        current_lang_layout.addWidget(self.current_language_display)
        current_lang_layout.addStretch()
        language_layout.addLayout(current_lang_layout)
        
        # 语言选择按钮
        button_layout = QHBoxLayout()
        
        # 中文按钮
        self.chinese_button = QPushButton("[中] 中文")
        self.chinese_button.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                padding: 12px 20px;
                border: 2px solid #3498db;
                border-radius: 8px;
                background-color: #ecf0f1;
                color: #2c3e50;
            }
            QPushButton:hover {
                background-color: #3498db;
                color: white;
            }
            QPushButton:pressed {
                background-color: #2980b9;
            }
        """)
        self.chinese_button.clicked.connect(lambda: self.switch_language('zh'))
        
        # 英文按钮
        self.english_button = QPushButton("[E] English")
        self.english_button.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                padding: 12px 20px;
                border: 2px solid #e74c3c;
                border-radius: 8px;
                background-color: #ecf0f1;
                color: #2c3e50;
            }
            QPushButton:hover {
                background-color: #e74c3c;
                color: white;
            }
            QPushButton:pressed {
                background-color: #c0392b;
            }
        """)
        self.english_button.clicked.connect(lambda: self.switch_language('en'))
        
        button_layout.addWidget(self.chinese_button)
        button_layout.addWidget(self.english_button)
        language_layout.addLayout(button_layout)
        
        # 说明文本
        note_label = QLabel(self.lang_manager.get_text('restart_note'))
        note_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #7f8c8d;
                background-color: #fff3cd;
                padding: 10px;
                border: 1px solid #ffeaa7;
                border-radius: 4px;
                margin-top: 10px;
            }
        """)
        note_label.setWordWrap(True)
        language_layout.addWidget(note_label)
        
        layout.addWidget(language_group)
        
        # 示例区域
        example_group = QGroupBox("[*] Preview / 预览效果")
        example_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                margin-top: 20px;
                padding-top: 10px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                background-color: #f8f9fa;
            }
        """)
        
        example_layout = QVBoxLayout(example_group)
        
        # 显示一些关键界面元素的双语言对照
        preview_text = f"""
• {self.lang_manager.get_text('file_selection')} / File Selection
• {self.lang_manager.get_text('simulation_type')} / Simulation Type  
• {self.lang_manager.get_text('energy_minimization')} / Energy Minimization
• {self.lang_manager.get_text('nvt_equilibration')} / NVT Equilibration
• {self.lang_manager.get_text('npt_equilibration')} / NPT Equilibration
• {self.lang_manager.get_text('production_run')} / Production Run
• {self.lang_manager.get_text('start_execution')} / Start Execution
• {self.lang_manager.get_text('file_status')} / File Status
        """
        
        self.preview_label = QLabel(preview_text.strip())
        self.preview_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #2c3e50;
                background-color: white;
                padding: 15px;
                border: 1px solid #ddd;
                border-radius: 4px;
                line-height: 1.6;
            }
        """)
        self.preview_label.setWordWrap(True)
        example_layout.addWidget(self.preview_label)
        
        layout.addWidget(example_group)
        
        # 添加弹簧
        layout.addStretch()
        
        # 将语言设置标签页添加到输出面板
        self.output_tab_widget.addTab(self.language_tab, self.lang_manager.get_text('language_settings'))

    def on_language_changed(self, index):
        """语言选择改变时的处理"""
        languages = ['en', 'zh', 'zh']  # 简体中文和繁体中文都使用zh
        if 0 <= index < len(languages):
            self.switch_language(languages[index])
    
    def switch_language(self, language):
        """切换语言功能"""
        if self.lang_manager.set_language(language):
            # 更新界面文本
            self.update_ui_language()
            
            # 显示成功消息
            lang_name = self.lang_manager.get_language_name(language)
            success_msg = self.lang_manager.get_text('language_switch_success', lang_name)
            
            QMessageBox.information(
                self, 
                self.lang_manager.get_text('success'), 
                success_msg
            )
        else:
            QMessageBox.warning(
                self, 
                self.lang_manager.get_text('error'), 
                "Invalid language code"
            )
    
    def update_current_language_display(self):
        """更新当前语言显示"""
        current_lang = self.lang_manager.get_current_language()
        display_text = self.lang_manager.get_language_name(current_lang)
        if hasattr(self, 'current_language_display'):
            self.current_language_display.setText(display_text)
    
    def update_ui_language(self):
        """更新界面语言"""
        try:
            # 更新当前语言显示
            self.update_current_language_display()
            
            # 更新输出面板标签页标题
            if hasattr(self, 'output_tab_widget'):
                tab_count = self.output_tab_widget.count()
                tab_keys = [
                    'mdp_preview', 
                    'command_preview',
                    'realtime_output',
                    'execution_log',
                    'file_status',
                    'language_settings'
                ]
                
                for i, key in enumerate(tab_keys):
                    if i < tab_count:
                        self.output_tab_widget.setTabText(i, self.lang_manager.get_text(key))
            
            # 更新左侧控制面板标签页标题
            if hasattr(self, 'tab_widget'):
                tab_count = self.tab_widget.count()
                tab_keys = [
                    'structure_centering',
                    'energy_minimization',
                    'nvt_equilibration', 
                    'npt_equilibration',
                    'production_run',
                    'command_generation'
                ]
                
                for i, key in enumerate(tab_keys):
                    if i < tab_count:
                        self.tab_widget.setTabText(i, self.lang_manager.get_text(key))
            
            # 更新分组框标题
            if hasattr(self, 'file_group'):
                self.file_group.setTitle(self.lang_manager.get_text('file_selection'))
            if hasattr(self, 'sim_type_group'):
                self.sim_type_group.setTitle(self.lang_manager.get_text('simulation_type'))
            if hasattr(self, 'workflow_group'):
                self.workflow_group.setTitle(self.lang_manager.get_text('workflow_status'))
            
            # 更新按钮文本
            if hasattr(self, 'preview_file_button'):
                self.preview_file_button.setText(self.lang_manager.get_text('file_preview'))
            if hasattr(self, 'update_file_status_btn'):
                self.update_file_status_btn.setText(self.lang_manager.get_text('update_file_status'))
            if hasattr(self, 'preview_structure_button'):
                self.preview_structure_button.setText(self.lang_manager.get_text('structure_preview_vmd'))
            if hasattr(self, 'save_mdp_button'):
                self.save_mdp_button.setText(self.lang_manager.get_text('save_mdp_file'))
            if hasattr(self, 'select_mdp_file_button'):
                self.select_mdp_file_button.setText(self.lang_manager.get_text('select_existing_mdp'))
            if hasattr(self, 'generate_command_btn'):
                self.generate_command_btn.setText(self.lang_manager.get_text('generate_command'))
            if hasattr(self, 'execute_command_btn'):
                self.execute_command_btn.setText(self.lang_manager.get_text('execute_command'))
            if hasattr(self, 'copy_command_btn'):
                self.copy_command_btn.setText(self.lang_manager.get_text('copy_command'))
            if hasattr(self, 'save_script_btn'):
                self.save_script_btn.setText(self.lang_manager.get_text('save_script'))
            if hasattr(self, 'start_btn'):
                self.start_btn.setText(self.lang_manager.get_text('start_execution'))
            if hasattr(self, 'stop_btn'):
                self.stop_btn.setText(self.lang_manager.get_text('stop_execution'))
            if hasattr(self, 'clear_output_btn'):
                self.clear_output_btn.setText(self.lang_manager.get_text('clear_output'))
            if hasattr(self, 'clear_log_button'):
                self.clear_log_button.setText(self.lang_manager.get_text('clear_log'))
            if hasattr(self, 'auto_fill_button'):
                self.auto_fill_button.setText(self.lang_manager.get_text('auto_fill_files'))
            
            # 更新MDP生成按钮
            if hasattr(self, 'generate_em_mdp_button'):
                self.generate_em_mdp_button.setText(self.lang_manager.get_text('generate_mdp', self.lang_manager.get_text('energy_minimization')))
            if hasattr(self, 'generate_nvt_mdp_button'):
                self.generate_nvt_mdp_button.setText(self.lang_manager.get_text('generate_mdp', 'NVT'))
            if hasattr(self, 'generate_npt_mdp_button'):
                self.generate_npt_mdp_button.setText(self.lang_manager.get_text('generate_mdp', 'NPT'))
            if hasattr(self, 'generate_prod_mdp_button'):
                self.generate_prod_mdp_button.setText(self.lang_manager.get_text('generate_mdp', self.lang_manager.get_text('production_run')))
            
            # 更新模拟类型下拉框
            if hasattr(self, 'sim_type_combo'):
                current_index = self.sim_type_combo.currentIndex()
                self.sim_type_combo.clear()
                sim_types = [
                    self.lang_manager.get_text('solution_simulation'),
                    self.lang_manager.get_text('gas_simulation'),
                    self.lang_manager.get_text('crystal_simulation'),
                    self.lang_manager.get_text('membrane_simulation'),
                    self.lang_manager.get_text('vacuum_simulation'),
                    self.lang_manager.get_text('free_energy_calculation')
                ]
                self.sim_type_combo.addItems(sim_types)
                if current_index >= 0 and current_index < len(sim_types):
                    self.sim_type_combo.setCurrentIndex(current_index)
            
            # 更新模拟类型相关显示
            self.update_workflow_hint()
            self.update_sim_type_description()
            current_sim_type = self.get_simulation_type_internal_name()
            self.update_parameter_recommendations(current_sim_type)
            
            # 更新状态标签
            if hasattr(self, 'status_label') and self.status_label.text() == '就绪':
                self.status_label.setText(self.lang_manager.get_text('ready'))
            
            # 更新复选框文本
            if hasattr(self, 'show_stdout_cb'):
                self.show_stdout_cb.setText("显示标准输出" if self.lang_manager.get_current_language() == 'zh' else 'Show Standard Output')
            if hasattr(self, 'show_stderr_cb'):
                self.show_stderr_cb.setText("显示错误输出" if self.lang_manager.get_current_language() == 'zh' else 'Show Error Output')
            # 修复：移除对不存在的auto_scroll_cb控件的依赖
            # if hasattr(self, 'auto_scroll_cb'):
            #     self.auto_scroll_cb.setText("自动滚动" if self.lang_manager.get_current_language() == 'zh' else 'Auto Scroll')
            
            # 更新语言预览区域
            if hasattr(self, 'preview_label'):
                self.update_language_preview()
                
        except Exception as e:
            print(f"Error updating UI language: {e}")
    
    def get_simulation_type_internal_name(self):
        """获取模拟类型的内部名称（中文）"""
        if not hasattr(self, 'sim_type_combo'):
            return '溶液模拟'
            
        current_index = self.sim_type_combo.currentIndex()
        internal_names = [
            '溶液模拟',
            '气相模拟', 
            '晶体模拟',
            '膜模拟',
            '真空模拟',
            '自由能计算'
        ]
        
        if current_index >= 0 and current_index < len(internal_names):
            return internal_names[current_index]
        return '溶液模拟'
    
    def update_language_preview(self):
        """更新语言预览区域"""
        preview_text = f"""
• {self.lang_manager.get_text('file_selection')} / File Selection
• {self.lang_manager.get_text('simulation_type')} / Simulation Type  
• {self.lang_manager.get_text('energy_minimization')} / Energy Minimization
• {self.lang_manager.get_text('nvt_equilibration')} / NVT Equilibration
• {self.lang_manager.get_text('npt_equilibration')} / NPT Equilibration
• {self.lang_manager.get_text('production_run')} / Production Run
• {self.lang_manager.get_text('start_execution')} / Start Execution
• {self.lang_manager.get_text('file_status')} / File Status
        """
        self.preview_label.setText(preview_text.strip())

    def select_working_directory(self):
        """选择工作目录"""
        from functools import partial
        QApplication.processEvents()
        directory = QFileDialog.getExistingDirectory(
            self, "选择工作目录", self.work_dir,
            options=QFileDialog.DontUseNativeDialog
        )
        if directory:
            self.working_dir_edit.setText(directory)
            self.work_dir = directory
            # 视觉反馈
            highlight_style = (
                "QLineEdit { border: 2px solid #4CAF50; background-color: #e8f5e9; }"
            )
            default_style = (
                "QLineEdit { border: 1px solid #ccc; border-radius: 3px; "
                "background: white; font-size: 11px; min-height: 20px; }"
            )
            self.working_dir_edit.setStyleSheet(highlight_style)
            QApplication.processEvents()
            QTimer.singleShot(1200, partial(self.working_dir_edit.setStyleSheet, default_style))

            # 更新文件管理器
            self.file_manager.update_directory(directory)

            # 自动填充输入文件
            self.auto_fill_input_files(directory)

    def select_file(self, line_edit, file_filter):
        """通用文件选择方法"""
        from functools import partial
        initial_dir = self.working_dir_edit.text() if self.working_dir_edit.text() else ""
        QApplication.processEvents()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", initial_dir, file_filter,
            options=QFileDialog.DontUseNativeDialog
        )
        if file_path:
            line_edit.setText(file_path)
            # 视觉反馈：高亮绿色表示选择成功
            highlight_style = (
                "QLineEdit { border: 2px solid #4CAF50; background-color: #e8f5e9; }"
            )
            default_style = (
                "QLineEdit { border: 1px solid #ccc; border-radius: 3px; "
                "background: white; font-size: 11px; min-height: 20px; }"
            )
            line_edit.setStyleSheet(highlight_style)
            QApplication.processEvents()
            # 用 partial 确保正确捕获 line_edit
            QTimer.singleShot(1200, partial(line_edit.setStyleSheet, default_style))

    def auto_fill_input_files(self, directory):
        """自动浏览和填充GRO、TOP、ITP、MDP和CPT文件"""
        
        # 检查目录是否存在
        if not directory or not os.path.exists(directory) or not os.path.isdir(directory):
            return
        
        try:
            # 用于跟踪是否找到了任何文件
            found_files = False
            
            # 查找GRO文件
            gro_files = [f for f in os.listdir(directory) if f.endswith('.gro')]
            if gro_files:
                # 选择第一个GRO文件
                gro_file = os.path.join(directory, gro_files[0])
                self.gro_file_edit.setText(gro_file)
                found_files = True
                
            # 查找TOP文件
            top_files = [f for f in os.listdir(directory) if f.endswith('.top')]
            if top_files:
                # 选择第一个TOP文件
                top_file = os.path.join(directory, top_files[0])
                self.top_file_edit.setText(top_file)
                found_files = True
                
            # 查找ITP文件
            itp_files = [f for f in os.listdir(directory) if f.endswith('.itp')]
            if itp_files:
                # 选择第一个ITP文件
                itp_file = os.path.join(directory, itp_files[0])
                self.itp_file_edit.setText(itp_file)
                found_files = True
                
            # 查找MDP文件
            mdp_files = [f for f in os.listdir(directory) if f.endswith('.mdp')]
            
            # 查找CPT文件
            cpt_files = [f for f in os.listdir(directory) if f.endswith('.cpt')]
            
            # 显示提示信息
            if found_files or mdp_files or cpt_files:
                # 创建文件类型列表
                file_types = []
                if gro_files:
                    file_types.append('.gro')
                if top_files:
                    file_types.append('.top')
                if itp_files:
                    file_types.append('.itp')
                if mdp_files:
                    file_types.append('.mdp')
                if cpt_files:
                    file_types.append('.cpt')
                
                print(f"[DEBUG] 自动填充成功，已填充文件类型: {file_types}")
            else:
                print("[DEBUG] 未找到任何可填充的文件")
                
        except Exception as e:
            print(f"[DEBUG] 自动填充文件时出错: {str(e)}")
    def collect_pbc_params(self, tab_prefix):
        """收集PBC相关参数 - 通用方法"""
        return {
            'pbc': getattr(self, f'{tab_prefix}_pbc_combo').currentText(),
            'cutoff-scheme': getattr(self, f'{tab_prefix}_cutoff_scheme_combo').currentText(),
            'nstlist': getattr(self, f'{tab_prefix}_nstlist_spinbox').value(),
            'rlist': getattr(self, f'{tab_prefix}_rlist_spinbox').value()
        }

    def validate_pbc_parameters(self):
        """验证PBC参数的合理性"""
        warnings = []
        # 检查所有选项卡的PBC设置一致性
        pbc_values = []
        prefixes = ['em', 'nvt', 'npt', 'md']
        for prefix in prefixes:
            if hasattr(self, f'{prefix}_pbc_combo'):
                pbc_values.append(getattr(self, f'{prefix}_pbc_combo').currentText())
        if len(set(pbc_values)) > 1:
            warnings.append("不同步骤的PBC设置不一致，建议保持一致")
        # 检查气相模拟参数
        if 'no' in pbc_values:
            for prefix in prefixes:
                if hasattr(self, f'{prefix}_pbc_combo'):
                    if getattr(self, f'{prefix}_pbc_combo').currentText() == 'no':
                        nstlist = getattr(self, f'{prefix}_nstlist_spinbox').value()
                        rlist = getattr(self, f'{prefix}_rlist_spinbox').value()
                        if nstlist != 0 or rlist != 0.0:
                            warnings.append(f"{prefix}步骤：pbc=no时，nstlist和rlist应该为0")
        return warnings

    def generate_minimization_mdp_content(self):
        """生成能量最小化MDP文件"""
        # 检查依赖文件
        if not self.validate_before_generation('minimization'):
            return
        
        # 统一参数字典，使用实际存在的控件或提供默认值
        params = {
            'integrator': self.em_integrator_combo.currentText(),
            'emtol': self.em_emtol_spin.value(),
            'emstep': self.em_emstep_spin.value(),
            'nsteps': self.em_nsteps_spin.value(),
            'coulombtype': self.em_coulombtype_combo.currentText(),
            'rcoulomb': self.em_rcoulomb_spin.value(),
            'rvdw': self.em_rvdw_spin.value(),
            'nstenergy': self.em_nstenergy_spin.value(),
            'nstlog': self.em_nstlog_spin.value(),
            'lincs_iter': self.em_lincs_iter_spin.value(),
            'lincs_order': self.em_lincs_order_spin.value(),
            'continuation': 'no',  # 能量最小化默认不继续
            'DispCorr': 'EnerPres',  # 默认色散校正
            'gen_seed': -1,  # 默认随机种子
            'pcoupl': 'no',  # 能量最小化不使用压力耦合
            # 使用默认值或从PBC组获取参数
            'constraints': 'all-bonds',  # 默认约束所有键
            'constraint_algorithm': 'lincs',  # 默认使用LINCS算法
            'cutoff-scheme': 'Verlet',  # 默认使用Verlet截断方案
            'nstlist': 10,  # 默认邻居列表更新频率
            'rlist': 1.0,  # 默认邻居列表截断半径
            'vdwtype': 'Cut-off',  # 默认范德华相互作用方法
            'pbc': 'xyz',  # 默认周期性边界条件
            'pme_order': 4,  # 默认PME插值阶数
            'fourierspacing': 0.16,  # 默认FFT网格间距
            'nstxout': self.em_nstxout_spin.value()  # 坐标输出频率
        }
        # 添加PBC参数
        pbc_params = self.collect_pbc_params('em')
        params.update(pbc_params)
        
        # 使用统一生成函数生成MDP内容
        mdp_content = MDPGenerator.generate_mdp_content('minimization', params)
        
        # 更新预览显示
        self.mdp_preview_text.setPlainText(mdp_content)
        self.current_step_type = 'minimization'
        
        # 保存参数以便后续使用
        self.selected_mdp_parameters = params

    def generate_nvt_mdp(self):
        """生成NVT平衡MDP文件"""
        # 检查依赖文件
        if not self.validate_before_generation('nvt'):
            return
        
        # 获取当前模拟类型
        sim_type = self.sim_type_combo.currentText()
        
        # 统一参数字典
        params = {
            'integrator': self.nvt_integrator_combo.currentText(),
            'dt': self.nvt_dt_spin.value(),
            'nsteps': self.nvt_nsteps_spin.value(),
            'tcoupl': self.nvt_tcoupl_combo.currentText(),
            'ref_t': self.nvt_ref_t_edit.text(),
            'tc-grps': self.nvt_tc_grps_combo.currentText(),
            'tau_t': self.nvt_tau_t_edit.text(),
            'constraint_algorithm': self.nvt_constraint_algorithm_combo.currentText(),
            'constraints': self.nvt_constraints_combo.currentText(),
            'posres': self.nvt_posres_checkbox.isChecked(),
            'gen_vel': self.nvt_gen_vel_checkbox.isChecked(),
            'gen_temp': self.nvt_gen_temp_spin.value(),
            'gen_seed': self.nvt_gen_seed_spin.value(),
            'nstxout': self.nvt_nstxout_spin.value(),
            'nstenergy': self.nvt_nstenergy_spin.value(),
            'nstlog': self.nvt_nstlog_spin.value(),
            'nstxout-compressed': self.nvt_nstxtcout_spin.value(),
            'lincs_iter': self.nvt_lincs_iter_spin.value(),
            'lincs_order': self.nvt_lincs_order_spin.value(),
            'continuation': self.nvt_continuation_combo.currentText(),
            'DispCorr': self.nvt_disp_corr_combo.currentText(),
            'pcoupl': self.nvt_pcoupl_combo.currentText(),
            'coulombtype': 'PME',  # 默认值
            'pme_order': 4,  # 默认值
            'fourierspacing': 0.16,  # 默认值
            'sim_type': sim_type  # 添加模拟类型参数
        }
        # 添加PBC参数
        pbc_params = self.collect_pbc_params('nvt')
        params.update(pbc_params)
        
        # 使用统一生成函数生成MDP内容
        mdp_content = MDPGenerator.generate_mdp_content('nvt', params)
        
        # 更新预览显示
        self.mdp_preview_text.setPlainText(mdp_content)
        self.current_step_type = 'nvt'
        
        # 保存参数以便后续使用
        self.selected_mdp_parameters = params
# ... existing code ...

    # ... existing code ...
    def generate_npt_mdp(self):
        """生成NPT平衡MDP文件"""
        # 检查依赖文件
        if not self.validate_before_generation('npt'):
            return
        
        # 获取当前模拟类型
        sim_type = self.sim_type_combo.currentText()
        
        # 统一参数字典
        params = {
            'integrator': self.npt_integrator_combo.currentText(),
            'dt': self.npt_dt_spin.value(),
            'nsteps': self.npt_nsteps_spin.value(),
            'tcoupl': self.npt_tcoupl_combo.currentText(),
            'pcoupl': self.npt_pcoupl_combo.currentText(),
            'pcoupltype': self.npt_pcoupltype_combo.currentText(),
            'ref_p': self.npt_ref_p_spin.value(),
            'tau_p': self.npt_tau_p_spin.value(),
            'compressibility': self.npt_compressibility_edit.text(),
            'DispCorr': self.npt_disp_corr_combo.currentText(),
            'continuation': 'yes' if self.npt_continuation_checkbox.isChecked() else 'no',
            'tc-grps': self.npt_tc_grps_combo.currentText(),
            'ref_t': self.npt_ref_t_edit.text(),
            'tau_t': self.npt_tau_t_edit.text(),
            'nstxout': self.npt_nstxout_spin.value(),
            'nstenergy': self.npt_nstenergy_spin.value(),
            'nstlog': self.npt_nstlog_spin.value(),
            'nstxout-compressed': self.npt_nstxtcout_spin.value(),
            'lincs_iter': self.npt_lincs_iter_spin.value(),
            'lincs_order': self.npt_lincs_order_spin.value(),
            'gen_seed': self.npt_gen_seed_spin.value(),
            'coulombtype': 'PME',  # 默认值
            'pme_order': 4,  # 默认值
            'fourierspacing': 0.16,  # 默认值
            'sim_type': sim_type  # 添加模拟类型参数
        }
        # 添加PBC参数
        pbc_params = self.collect_pbc_params('npt')
        params.update(pbc_params)
        
        # 使用统一生成函数生成MDP内容
        mdp_content = MDPGenerator.generate_mdp_content('npt', params)
        
        # 更新预览显示
        self.mdp_preview_text.setPlainText(mdp_content)
        self.current_step_type = 'npt'
        
        # 保存参数以便后续使用
        self.selected_mdp_parameters = params
        
    def generate_production_mdp(self):
        """生成生产运行MDP文件"""
        # 检查依赖文件
        if not self.validate_before_generation('production'):
            return
        
        # 获取当前模拟类型
        sim_type = self.sim_type_combo.currentText()
        
        # 统一参数字典
        params = {
            'integrator': self.prod_integrator_combo.currentText(),
            'dt': self.prod_dt_spin.value(),
            'nsteps': self.prod_nsteps_spin.value(),
            'nstlog': self.prod_nstlog_spin.value(),
            'nstenergy': self.prod_nstenergy_spin.value(),
            'nstxout-compressed': self.prod_nstxtcout_spin.value(),
            'nstxout': self.prod_nstxout_spin.value(),
            'tcoupl': self.prod_tcoupl_combo.currentText(),
            'pcoupl': self.prod_pcoupl_combo.currentText(),
            'pcoupltype': self.prod_pcoupltype_combo.currentText(),
            'ref_p': self.prod_ref_p_spin.value(),
            'tau_p': self.prod_tau_p_spin.value(),
            'compressibility': self.prod_compressibility_edit.text(),
            'DispCorr': self.prod_disp_corr_combo.currentText(),
            'posres': self.prod_posres_checkbox.isChecked(),
            'tc-grps': self.prod_tc_grps_combo.currentText(),
            'ref_t': self.prod_ref_t_edit.text(),
            'tau_t': self.prod_tau_t_edit.text(),
            'lincs_iter': self.prod_lincs_iter_spin.value(),
            'lincs_order': self.prod_lincs_order_spin.value(),
            'constraint_algorithm': self.prod_constraint_algorithm_combo.currentText(),
            'constraints': self.prod_constraints_combo.currentText(),
            'continuation': 'yes',  # 生产运行默认继续
            'gen_seed': self.prod_gen_seed_spin.value(),  # 随机种子
            'coulombtype': 'PME',  # 默认值
            'pme_order': 4,  # 默认值
            'fourierspacing': 0.16,  # 默认值
            'sim_type': sim_type  # 添加模拟类型参数
        }
        # 添加PBC参数
        pbc_params = self.collect_pbc_params('md')
        params.update(pbc_params)
        
        # 使用统一生成函数生成MDP内容
        mdp_content = MDPGenerator.generate_mdp_content('production', params)
        
        # 更新预览显示，确保与保存的内容一致
        self.mdp_preview_text.setPlainText(mdp_content)
        self.current_step_type = 'production'
        # 切换到MDP预览选项卡，确保用户能看到生成的内容
        self.output_tab_widget.setCurrentWidget(self.mdp_preview_tab)
        
        # 保存参数以便后续使用
        self.selected_mdp_parameters = params


    def validate_before_generation(self, step_type):
        """生成MDP前的验证"""
        missing_files = self.check_file_dependencies(step_type)
        if missing_files:
            QMessageBox.warning(self, "文件缺失",
                              f"以下文件缺失，无法生成{step_type} MDP:\n" +
                              "\n".join(missing_files))
            return False
        # 验证PBC参数
        pbc_warnings = self.validate_pbc_parameters()
        if pbc_warnings:
            warning_msg = "发现以下PBC参数设置问题：\n" + "\n".join(pbc_warnings)
            reply = QMessageBox.question(self, "PBC参数警告", warning_msg + "\n是否继续生成MDP文件？",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return False
        return True

    def check_file_dependencies(self, step_type):
        """检查文件依赖关系 - 根据模拟类型和用户选择"""
        user_files = self.file_manager.get_user_selected_files()
        sim_type = self.sim_type_combo.currentText()
        missing_files = []
        if step_type == 'minimization':
            # 检查结构文件
            if not (user_files['gro'] or user_files['pdb']):
                missing_files.append("结构文件(.gro或.pdb)")
            else:
                # 检查文件是否实际存在
                gro_exists = user_files['gro'] and os.path.exists(user_files['gro'])
                pdb_exists = user_files['pdb'] and os.path.exists(user_files['pdb'])
                if not (gro_exists or pdb_exists):
                    missing_files.append("结构文件(所选文件不存在)")
            # 检查拓扑文件
            if not user_files['top']:
                missing_files.append("拓扑文件(.top)")
            elif not os.path.exists(user_files['top']):
                missing_files.append("拓扑文件(所选文件不存在)")
            # ITP 文件是可选的，不检查其存在性
        elif step_type in ['nvt', 'npt', 'production']:
            # 检查上一步的输出文件
            prev_step_map = {
                'nvt': 'em',
                'npt': 'nvt',
                'production': 'nvt' if sim_type == '气相模拟' else ('em' if sim_type == '真空模拟' else 'npt')
            }
            prev_step = prev_step_map[step_type]
            prev_gro = f"{prev_step}.gro"
            working_dir = self.working_dir_edit.text()
            if not os.path.exists(os.path.join(working_dir, prev_gro)):
                missing_files.append(f"{prev_gro} (需要先完成{prev_step}步骤)")
            # 检查拓扑文件 (ITP 文件可选)
            if not user_files['top']:
                missing_files.append("拓扑文件(.top)")
            elif not os.path.exists(user_files['top']):
                missing_files.append("拓扑文件(所选文件不存在)")
        return missing_files

    def update_simulation_time(self):
        """更新模拟时间显示"""
        # 计算模拟时间: 步数 * 时间步长 / 1000 (转换为ns)
        steps = self.prod_nsteps_spin.value()
        dt = self.prod_dt_spin.value()
        simulation_time = steps * dt / 1000.0
        self.simulation_time_label.setText(f"模拟时间: {simulation_time:.2f} ns")

    def generate_gromacs_command(self, step_type):
        """生成GROMACS命令 - 使用用户实际选择的文件"""
        user_files = self.file_manager.get_user_selected_files()
        step_name = self.file_manager.step_names[step_type]
        sim_type = self.sim_type_combo.currentText()
        # 获取实际的输入文件
        if step_type == 'minimization':
            input_structure = self.file_manager.get_input_structure(step_type, [])
            topology_file = self.file_manager.get_topology_file()
        else:
            completed_steps = self.workflow_manager.get_completed_steps()
            input_structure = self.file_manager.get_input_structure(step_type, completed_steps)
            topology_file = self.file_manager.get_topology_file()

        # 生成grompp命令
        if input_structure:
            input_basename = os.path.basename(input_structure)
        else:
            input_basename = "input.gro"  # 默认值
        topology_basename = os.path.basename(topology_file)
        grompp_cmd = f"gmx grompp -f {step_name}.mdp -c {input_basename} -p {topology_basename} -o {step_name}.tpr"

        # 对于NVT及以后的步骤，添加位置约束引用
        if step_type == 'nvt':
            grompp_cmd += f" -r {input_basename}"
        elif step_type in ['npt', 'production']:
            if sim_type == '气相模拟' and step_type == 'production':
                # 气相模拟的生产运行使用nvt的检查点
                grompp_cmd += f" -t nvt.cpt"
            elif sim_type == '真空模拟' and step_type == 'production':
                # 真空模拟的生产运行直接从em继续，无检查点
                pass  # 真空模拟不需要检查点
            elif step_type == 'npt':
                grompp_cmd += f" -t nvt.cpt"
            elif step_type == 'production':
                grompp_cmd += f" -t npt.cpt"

        #// ... existing code ...
        #// ... existing code ...
        # 生成mdrun命令
        mdrun_cmd = f"gmx mdrun -s {step_name}.tpr -deffnm {step_name}"
        
        # 添加MPI前缀
        if self.mpi_checkbox.isChecked():
            mpi_nprocs = self.mpi_np_spinbox.value()
            mdrun_cmd = f"mpirun -np {mpi_nprocs} {mdrun_cmd}"
        
        # 添加GPU选项
        if hasattr(self.ui, 'gpu_edit') and self.ui.gpu_edit.text().strip():
            mdrun_cmd += f" -gpu_id {self.ui.gpu_edit.text().strip()}"
                
        # 添加OpenMP线程数选项
        if hasattr(self.ui, 'ntomp_spinbox') and self.ui.ntomp_spinbox.value() > 0:
            ntomp = self.ui.ntomp_spinbox.value()
            mdrun_cmd += f" -ntomp {ntomp}"
                
        # 添加最大运行时间
        if hasattr(self.ui, 'maxh_spinbox') and self.ui.maxh_spinbox.value() > 0:
            mdrun_cmd += f" -maxh {self.ui.maxh_spinbox.value()}"

        return grompp_cmd, mdrun_cmd
#// ... existing code ...
#// ... existing code ...

    def generate_command(self, command_type):
        """生成指定类型的GROMACS命令"""
        # 获取参数
        pdb_file = self.pdb_file_edit.text()
        forcefield = self.forcefield_combo.currentText()
        water_model = self.water_model_combo.currentText()
        box_type = self.box_type_combo.currentText()
        box_distance = self.box_distance_spin.value()
        concentration = self.ion_concentration_spin.value()
        sim_type = self.sim_type_combo.currentText()
        # 获取已完成步骤
        completed_steps = self.workflow_manager.get_completed_steps()

        # 生成命令
        if command_type == 'pdb2gmx':
            command = f"gmx pdb2gmx -f {pdb_file} -o processed.gro -p topol.top -ff {forcefield} -water {water_model}"
        elif command_type == 'editconf':
            command = f"gmx editconf -f processed.gro -o newbox.gro -bt {box_type} -d {box_distance}"
        elif command_type == 'solvate':
            command = f"gmx solvate -cp newbox.gro -cs spc216.gro -o solvated.gro -p topol.top"
        elif command_type == 'genion':
            command = f"gmx grompp -f ions.mdp -c solvated.gro -p topol.top -o ions.tpr && echo SOL | gmx genion -s ions.tpr -o ionized.gro -p topol.top -pname NA -nname CL -conc {concentration}"
        elif command_type == 'grompp':
            # 根据当前步骤生成相应的grompp命令
            if hasattr(self, 'current_step_type'):
                step_type = self.current_step_type
                grompp_cmd, _ = self.generate_gromacs_command(step_type)
                command = grompp_cmd
            else:
                command = "# 请先生成对应的MDP文件"
        elif command_type == 'mdrun':
            # 根据当前步骤生成相应的mdrun命令
            if hasattr(self, 'current_step_type'):
                command = self.command_generator.generate_mdrun_command(self.current_step_type)
                # 如果命令为 None，说明用户取消了操作或者需要先运行grompp
                if command is None:
                    # 检查是否是因为缺少TPR文件而需要运行grompp
                    step_names = {'minimization': 'em', 'nvt': 'nvt', 'npt': 'npt', 'production': 'md'}
                    step_name = step_names.get(self.current_step_type, self.current_step_type)
                    if not self.command_generator._check_tpr_file_exists(self.current_step_type):
                        # 建议用户先运行grompp
                        reply = QMessageBox.question(
                            self,
                            "提示",
                            f"检测到需要先生成 {step_name}.tpr 文件。\n是否切换到grompp命令生成?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.Yes:
                            # 切换到grompp标签页
                            self.current_step_type = self.current_step_type
                            self.generate_command('grompp')
                    return
                # 显示命令
                if isinstance(command, tuple) and len(command) == 2 and command[0] == "RESUME_MODE":
                    # 修复：使用正确的属性名 cmd_preview_text 而不是 command_preview
                    if hasattr(self, 'cmd_preview_text'):
                        self.cmd_preview_text.setPlainText(command[1])
                else:
                    # 修复：使用正确的属性名 cmd_preview_text 而不是 command_preview
                    if hasattr(self, 'cmd_preview_text'):
                        self.cmd_preview_text.setPlainText(str(command))
            else:
                command = "# 请先运行grompp命令"

        # 修复：使用正确的属性名 cmd_preview_text 而不是 command_preview
        if hasattr(self, 'cmd_preview_text'):
            self.cmd_preview_text.setPlainText(str(command))

    def save_mdp_file(self):
        """保存MDP文件"""
        # 从MDP预览区域获取内容
        mdp_content = self.mdp_preview_text.toPlainText()
        if not mdp_content:
            QMessageBox.warning(self, "警告", "没有可保存的MDP内容")
            return
            
        # 确定文件名 - 修复逻辑：根据当前选中的标签页确定文件名
        filename = None
        # 获取当前活跃的子标签页文本（适配嵌套Tab结构）
        current_tab_text = ""
        if hasattr(self, 'sim_run_tabs'):
            idx = self.sim_run_tabs.currentIndex()
            if idx >= 0:
                current_tab_text = self.sim_run_tabs.tabText(idx)
        
        # 根据当前标签页确定文件名和步骤类型
        if "能量最小化" in current_tab_text:
            filename = "em.mdp"
            self.current_step_type = "minimization"
        elif "NVT" in current_tab_text:
            filename = "nvt.mdp"
            self.current_step_type = "nvt"
        elif "NPT" in current_tab_text:
            filename = "npt.mdp"
            self.current_step_type = "npt"
        elif "生产运行" in current_tab_text:
            filename = "md.mdp"
            self.current_step_type = "production"
        else:
            # 如果没有匹配的标签页，使用默认逻辑
            # 检查selected_mdp_label是否存在，如果不存在则创建一个默认的
            if not hasattr(self, 'selected_mdp_label'):
                self.selected_mdp_label = QLabel("未选择MDP文件")
                self.selected_mdp_label.setStyleSheet("color: blue;")
            selected_text = self.selected_mdp_label.text()
            
            # 检查是否已选择了MDP文件
            if selected_text.startswith("已选择: "):
                filename = selected_text.replace("已选择: ", "")
            
            # 如果没有选择文件或使用的是默认标签，则根据当前步骤类型确定文件名
            if not filename or filename == "未选择MDP文件":
                if hasattr(self, 'current_step_type'):
                    filename = self.file_manager.get_mdp_filename(self.current_step_type)
                    print(f"[DEBUG] 根据current_step_type={self.current_step_type}生成文件名: {filename}")
                else:
                    filename = "md.mdp"  # 默认文件名
                    print("[DEBUG] 使用默认文件名: md.mdp")
                
        working_dir = self.working_dir_edit.text()
        if not working_dir:
            QMessageBox.warning(self, "错误", "请先设置工作目录")
            return
            
        file_path = os.path.join(working_dir, filename)
        print(f"[DEBUG] 准备保存到: {file_path}")
        
        # 调试输出：打印生成的MDP内容
        print("=== MDP内容调试输出 ===")
        print(mdp_content)
        print("=== MDP内容调试输出结束 ===")
        
        # 一致性校验：重新生成MDP内容并比较
        if hasattr(self, 'current_step_type') and hasattr(self, 'selected_mdp_parameters'):
            regenerated_content = MDPGenerator.generate_mdp_content(self.current_step_type, self.selected_mdp_parameters)
            if mdp_content != regenerated_content:
                reply = QMessageBox.question(self, "内容不一致",
                                           "预览内容与重新生成的内容不一致，是否继续保存？",
                                           QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    return  # 用户取消，直接返回
        
        # 修复逻辑：在保存之前就检查文件是否存在
        if os.path.exists(file_path):
            reply = QMessageBox.question(self, "文件已存在",
                                       f"文件 {filename} 已存在，是否覆盖？",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                # 询问是否使用新文件名保存
                new_filename, ok = QInputDialog.getText(self, "新文件名", 
                                                       "请输入新的文件名:", 
                                                       QLineEdit.Normal, filename)
                if ok and new_filename:
                    if not new_filename.endswith('.mdp'):
                        new_filename += '.mdp'
                    filename = new_filename  # 更新文件名
                    file_path = os.path.join(working_dir, new_filename)
                else:
                    return  # 用户取消，直接返回
        
        # 执行保存操作
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(mdp_content)
            
            QMessageBox.information(self, "成功", f"MDP文件已保存到:\n{file_path}")
            
            # 更新标签显示 - 修复：确保selected_mdp_label存在后再访问
            if not hasattr(self, 'selected_mdp_label'):
                self.selected_mdp_label = QLabel("未选择MDP文件")
                self.selected_mdp_label.setStyleSheet("color: blue;")
            self.selected_mdp_label.setText(f"已选择: {os.path.basename(file_path)}")
            self.selected_mdp_label.setStyleSheet("color: green;")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存MDP文件:\n{str(e)}")

    def select_existing_mdp_file(self):
        """选择现有的MDP文件并加载其内容"""
        working_dir = self.working_dir_edit.text()
        if not working_dir or not os.path.exists(working_dir):
            QMessageBox.warning(self, "错误", "请先设置有效的工作目录")
            return
            
        # 打开文件选择对话框，只显示MDP文件
        mdp_file, _ = QFileDialog.getOpenFileName(
            self, 
            "选择MDP文件", 
            working_dir, 
            "MDP Files (*.mdp);;All Files (*)"
        )
        
        if mdp_file:
            try:
                # 读取MDP文件内容
                with open(mdp_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 显示在MDP预览区域
                self.mdp_preview_text.setPlainText(content)
                
                # 显示选中的文件名
                filename = os.path.basename(mdp_file)
                # 如果selected_mdp_label不存在，创建一个
                if not hasattr(self, 'selected_mdp_label'):
                    self.selected_mdp_label = QLabel("未选择MDP文件")
                    self.selected_mdp_label.setStyleSheet("color: blue;")
                self.selected_mdp_label.setText(f"已选择: {filename}")
                self.selected_mdp_label.setStyleSheet("color: green;")
                
                # 根据文件名推断步骤类型
                self.infer_step_type_from_mdp(filename)
                
                # 清空参数字典，因为我们加载的是现有文件
                self.selected_mdp_parameters = {}
                
                # 不再显示成功弹窗，因为文件内容已显示在预览区域
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法读取MDP文件:\n{str(e)}")

    def copy_to_clipboard(self):
        """将命令行预览区的内容复制到系统剪贴板"""
        command_text = self.cmd_preview_text.toPlainText().strip()
        if command_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(command_text)
            QMessageBox.information(self, "复制成功", "命令已复制到剪贴板！")
        else:
            QMessageBox.warning(self, "复制失败", "没有可复制的命令！")

    def on_execute_command_clicked(self):
        """执行命令按钮点击事件"""
        # --- 修复点：正确检查 command_executor 是否存在且正在运行 ---
        # 原代码可能导致 AttributeError: 'NoneType' object has no attribute 'isRunning'
        # 旧代码: if hasattr(self, 'command_executor') and self.command_executor.isRunning():
        # 新的检查方式：直接检查实例是否不为 None 且正在运行
        if self.command_executor is not None and self.command_executor.isRunning():
            QMessageBox.warning(self, "正在执行", "已有命令正在执行中")
            return
        # --- 修复点结束 ---
        # 获取要执行的命令
        # 修复：使用正确的属性名 cmd_preview_text 而不是 command_preview
        command_text = self.cmd_preview_text.toPlainText() if hasattr(self, 'cmd_preview_text') else ""
        if not command_text.strip():
            QMessageBox.warning(self, "无命令", "请先生成命令")
            return
        # 过滤掉注释行，只执行实际命令
        commands = [line.strip() for line in command_text.split('\n')
                    if line.strip() and not line.strip().startswith('#')]
        if not commands:
            QMessageBox.warning(self, "无效命令", "未找到有效的执行命令")
            return

        # --- 新增逻辑：处理可选的 ITP 文件 ---
        user_files = self.command_generator.get_user_files()
        itp_path = user_files.get('itp')
        working_dir = self.working_dir_edit.text() or os.getcwd()
        if itp_path and os.path.exists(itp_path):
            # 如果用户选择了 ITP 文件且文件存在，则将其复制到工作目录
            try:
                dest_path = os.path.join(working_dir, os.path.basename(itp_path))
                if not os.path.exists(dest_path): # 避免覆盖已存在的同名文件
                    shutil.copy2(itp_path, dest_path)
                    self.append_output(f"已将 ITP 文件 '{itp_path}' 复制到工作目录 '{dest_path}'", 'command')
                else:
                     self.append_output(f"工作目录中已存在 '{os.path.basename(itp_path)}'，跳过复制。", 'command')
            except Exception as e:
                 self.append_output(f"复制 ITP 文件失败: {e}", 'stderr')
        # --- 新增逻辑结束 ---

        # 创建执行线程
        # --- 确保每次都创建一个新的实例 ---
        self.command_executor = CommandExecutor(commands, working_dir)
        # --- 结束 ---
        # 连接信号 (这部分保持不变，但确保 command_executor 已创建)
        # 注意：需要断开旧的连接（如果有的话），以避免信号多次触发
        # 但通常创建新实例会自动处理这个问题。为安全起见，可以在类初始化时连接一次，
        # 或者在这里确保只连接一次。这里我们保持原样，因为新实例不会有旧连接。
        try:
            self.command_executor.output_ready.connect(
                lambda text: self.append_output(text, self._get_output_type(text)))
            self.command_executor.error_ready.connect(
                lambda text: self.append_output(text, 'stderr'))
            self.command_executor.finished_signal.connect(self.on_command_finished)
            self.command_executor.progress_update.connect(
                lambda msg: self.status_label.setText(msg))
        except TypeError:
            # 如果信号已经连接，可能会抛出 TypeError，可以忽略或先断开
            pass

        # 更新UI状态
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.execute_command_btn.setEnabled(False) # 也应该禁用，防止重复点击
        self.status_label.setText("正在执行...")
        self.progress_bar.setRange(0, 0)  # 不确定进度
        # 启动执行
        self.command_executor.start()
        # 在输出区域显示开始执行的命令
        self.append_output(f"=== 开始执行 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
        for cmd in commands:
            self.append_output(f"$ {cmd}", 'command')
        # 添加到日志
        self.log_output.append(f"<b>开始执行命令:</b><br>{'<br>'.join(commands)}<br>")

    def on_stop_command_clicked(self):
        """停止命令执行"""
        # --- 修复点：同样检查实例是否不为 None ---
        if self.command_executor is not None and self.command_executor.isRunning():
            reply = QMessageBox.question(self, "确认停止", "确定要停止当前命令执行吗？",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.command_executor.stop()
                self.status_label.setText("正在停止...")
        else:
            QMessageBox.information(self, "信息", "当前没有正在执行的命令")

    def on_generate_command_clicked(self):
        """生成命令按钮点击事件"""
        try:
            # 获取当前选中的步骤类型
            current_step = getattr(self, 'current_step_type', None)
            if not current_step:
                QMessageBox.warning(self, "无步骤", "请先生成MDP文件以确定当前步骤")
                return
            
            # 初始化变量
            input_file = ""
            output_file = ""
            validation_errors = []
            commands = []
            
            # 验证文件 (ITP 文件可选)
            missing_files = self.command_generator.validate_files(current_step)
            if missing_files:
                QMessageBox.warning(self, "文件缺失",
                                  f"以下文件缺失:\n" + '\n'.join(missing_files))
                return
                
            # 使用新的统一方法生成命令
            commands = self.command_generator.generate_single_step_commands(current_step)
            if commands is None:
                # 用户取消操作
                return
                
            # 显示命令
            full_command = f"# {current_step.upper()}步骤\n" + "\n".join(commands)
            
            # 获取历史命令
            history_text = getattr(self, 'command_history_text', '')
            
            # 如果有历史命令，则显示历史命令+当前新命令
            if history_text:
                full_command = f"{history_text}\n{full_command}"
            
            # 修复：使用正确的属性名 cmd_preview_text 而不是 command_preview
            if hasattr(self, 'cmd_preview_text'):
                self.cmd_preview_text.setPlainText(full_command)
            # 启用执行按钮
            self.execute_command_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "生成失败", f"命令生成失败: {str(e)}")
    ############################################
    
    def on_command_finished(self, return_code, message):
        """命令执行完成处理"""
        # 更新UI状态
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.execute_command_btn.setEnabled(True)  # 重新启用执行按钮
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if return_code == 0 else 0)
        
        # 显示完成消息
        if return_code == 0:
            self.status_label.setText("执行完成")
            self.append_output(f"=== 执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            # 更新文件状态
            self.update_file_status()

            # 更新工作流程状态（检查log文件判断步骤完成）
            self.update_workflow_status()

            # 检查是否需要运行健康检查 (在NPT平衡或生产运行完成后)
            current_step = getattr(self, 'current_step_type', None)
            if current_step in ['npt', 'production']:
                pass

            # 可选：自动切换到下一个步骤
            self.suggest_next_step()
        else:
            self.status_label.setText("执行失败")
            self.append_output(f"=== 执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>命令执行{status}:</b> {message}<br>")

    def check_for_checkpoint_files(self):
        """检查工作目录中的检查点文件并提供续跑选项"""
        working_dir = self.working_dir_edit.text()
        if not working_dir or not os.path.exists(working_dir) or not os.path.isdir(working_dir):
            return
            
        # 查找CPT文件
        cpt_files = [f for f in os.listdir(working_dir) if f.endswith('.cpt')]
        
        if cpt_files:
            # 查找对应的步骤
            for cpt_file in cpt_files:
                step_name = os.path.splitext(cpt_file)[0]  # 移除.cpt扩展名
                
                # 检查是否存在对应的TPR文件
                tpr_file = os.path.join(working_dir, f"{step_name}.tpr")
                if os.path.exists(tpr_file):
                    # 直接设置续跑参数，避免弹窗提示
                    self._setup_resume_run(step_name, os.path.join(working_dir, cpt_file))
                    # 在状态栏显示信息，告知用户已检测到检查点文件并自动设置续跑
                    self.status_label.setText(f"已检测到检查点文件 {cpt_file}，已自动设置续跑参数")
                    break
                        
    def _setup_resume_run(self, step_name, cpt_file):
        """设置续跑参数"""
        # 根据步骤名称设置相应的参数
        if step_name == "em":
            # 能量最小化步骤续跑
            pass
        elif step_name == "nvt":
            # NVT步骤续跑
            pass
        elif step_name == "npt":
            # NPT步骤续跑
            pass
        elif step_name == "md":
            # 生产运行步骤续跑
            pass
            
        # 通过状态栏显示提示信息，避免弹窗
        self.status_label.setText(f"已为{step_name}步骤设置续跑参数，检查点文件: {os.path.basename(cpt_file)}，请检查相关参数并点击'开始执行'按钮继续模拟。")

    def on_center_command_finished(self, return_code, message):
        """结构居中命令执行完成处理"""
        try:
            # 获取输入输出文件信息
            # 使用加强版结构操作功能
            
            # 自动切换到实时输出选项卡，以便用户能看到完成信息
            if hasattr(self, 'output_tab_widget') and hasattr(self, 'realtime_output_tab'):
                self.output_tab_widget.setCurrentWidget(self.realtime_output_tab)
            
            if return_code == 0:
                # 成功完成
                if hasattr(self, 'output_display'):
                    self.output_display.appendPlainText("\n结构居中完成!")
                
                # 检查输出文件是否存在
                if os.path.exists(output_file):
                    if hasattr(self, 'output_display'):
                        self.output_display.appendPlainText(f"输出文件已生成: {output_file}")
                        self.output_display.appendPlainText("\n提示: 您可以使用VMD或其他工具预览结果")
                    
                    # 自动更新文件状态
                    self.update_file_status()
                else:
                    if hasattr(self, 'output_display'):
                        self.output_display.appendPlainText("警告: 未找到输出文件")
            else:
                # 执行失败
                if hasattr(self, 'output_display'):
                    self.output_display.appendPlainText(f"\n结构居中失败，退出代码: {return_code}")
                    if message:
                        self.output_display.appendPlainText(f"错误信息: {message}")
            
            # 添加到执行日志
            if hasattr(self, 'log_output'):
                status = "成功" if return_code == 0 else "失败"
                self.log_output.append(f"<b>结构居中{status}:</b> {input_file} -> {output_file}<br>")
                if message:
                    self.log_output.append(f"<i>消息: {message}</i><br>")
                    
        except Exception as e:
            if hasattr(self, 'output_display'):
                self.output_display.appendPlainText(f"处理完成信号时出错: {str(e)}")


                self.output_display.appendPlainText("正在执行...")
            
            # 执行命令
            working_dir = os.path.dirname(input_file) if os.path.dirname(input_file) else os.getcwd()
            executor = CommandExecutor([command], working_dir)
            return_code, message = executor.execute_sync()
            
            # 添加到执行日志
            if hasattr(self, 'log_output'):
                status = "成功" if return_code == 0 else "失败"
                self.log_output.append(f"<b>设置盒子尺寸{status}:</b> {input_file} -> {output_file}<br>")
                if message:
                    self.log_output.append(f"<i>消息: {message}</i><br>")
                    
        except Exception as e:
            if hasattr(self, 'output_display'):
                self.output_display.appendPlainText(f"处理命令时出错: {str(e)}")

    def preview_structure_with_vmd(self):
        """使用VMD预览结构文件 - 已被加强版结构操作替代"""
        pass

    def on_box_command_finished(self, return_code, message):
        """盒子设置命令执行完成的处理 - 已被加强版结构操作替代"""
        pass

    def append_output(self, text, output_type='stdout'):
        """添加输出文本，支持不同类型的颜色显示"""
        cursor = self.output_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        # 根据输出类型设置颜色
        format = QTextCharFormat()
        if output_type == 'stderr':
            format.setForeground(QColor('red'))
        elif output_type == 'command':
            format.setForeground(QColor('blue'))
            format.setFontWeight(QFont.Bold)
        elif output_type == 'system':
            # 系统提示信息（开始执行、命令执行完成等）用绿色显示
            format.setForeground(QColor('darkGreen'))
            format.setFontWeight(QFont.Bold)
        elif output_type == 'info':
            # 一般信息用深蓝色显示
            format.setForeground(QColor('darkBlue'))
        else:
            format.setForeground(QColor('black'))
        cursor.setCharFormat(format)
        cursor.insertText(text + '\n')
        # 自动滚动到底部
        # 修复：移除对不存在的auto_scroll_cb控件的依赖，总是自动滚动
        self.output_display.setTextCursor(cursor)
        self.output_display.ensureCursorVisible()
    def suggest_next_step(self):
        """建议下一步操作"""
        current_step = getattr(self, 'current_step_type', None)
        if current_step:
            next_steps = {
                'minimization': 'nvt',
                'nvt': 'npt',
                'npt': 'production',
                'production': None
            }
            next_step = next_steps.get(current_step)
            if next_step:
                self.status_label.setText(f"执行完成，建议下一步: {next_step}")
    def _get_output_type(self, text):
        """根据文本内容判断输出类型"""
        if text.startswith("===") or "GROMACS" in text or text.startswith("Setting the LD random seed") or \
           "parameter combinations" in text or text.startswith("Executable:") or \
           text.startswith("Generated") or text.endswith("(-:"):
            return 'system'

        elif text.startswith("work"):
            return 'info'
        else:
            return 'stdout'

    def toggle_mpi_options(self, state):
        """切换MPI选项的可用性"""
        self.mpi_np_spinbox.setEnabled(state == Qt.CheckState.Checked)

    def update_workflow_status(self):
        """根据模拟类型和实际文件状态更新工作流程进度显示"""
        # 获取当前模拟类型
        sim_type = self.sim_type_combo.currentText()
        working_dir = self.working_dir_edit.text() or os.getcwd()
        
        # 根据模拟类型定义步骤和对应的log文件
        step_configs = {
            '气相模拟': [
                ('em', '能量最小化'),
                ('nvt', 'NVT平衡'),
                ('md', '生产运行')  # 气相跳过NPT
            ],
            '溶液模拟': [
                ('em', '能量最小化'),
                ('nvt', 'NVT平衡'),
                ('npt', 'NPT平衡'),
                ('md', '生产运行')
            ],
            '晶体模拟': [
                ('em', '能量最小化'),
                ('nvt', 'NVT平衡'),
                ('npt', 'NPT平衡'),
                ('md', '生产运行')
            ],
            '膜模拟': [
                ('em', '能量最小化'),
                ('nvt', 'NVT平衡'),
                ('npt', 'NPT平衡(半各向同性)'),
                ('md', '生产运行')
            ],
            '真空模拟': [
                ('em', '能量最小化'),
                ('md', '生产运行')
            ],
            '自由能计算': [
                ('em', '能量最小化'),
                ('nvt', 'NVT平衡'),
                ('npt', 'NPT平衡'),
                ('md', '多窗口生产运行')
            ]
        }
        
        # 获取当前模拟类型的步骤配置
        steps = step_configs.get(sim_type, step_configs['溶液模拟'])  # 默认使用溶液模拟
        total_steps = len(steps)
        
        # 检查每个步骤的log文件是否存在
        completed_steps = 0
        completed_step_names = []
        
        for step_code, step_name in steps:
            log_file = os.path.join(working_dir, f"{step_code}.log")
            if os.path.exists(log_file):
                completed_steps += 1
                completed_step_names.append(step_name)
        
        # 更新进度显示
        status_text = f"工作流程进度: {completed_steps}/{total_steps} 已完成"
        
        # 根据完成情况添加提示信息
        if completed_steps == 0:
            status_text += " - 请先运行能量最小化"
        elif completed_steps < total_steps:
            # 显示下一步需要执行的步骤
            next_step = steps[completed_steps][1]  # 获取下一步的名称
            status_text += f" - 可以运行{next_step}"
        else:
            status_text += " - 工作流程完成"
        
        # 更新显示标签
        self.workflow_status_label.setText(status_text)

        # 更新步骤指示器标签颜色
        if hasattr(self, 'workflow_step_labels'):
            # 根据模拟类型决定显示哪些步骤
            visible_codes = [s[0] for s in steps]
            step_codes = ['em', 'nvt', 'npt', 'md']
            for i, lbl in enumerate(self.workflow_step_labels):
                if i < len(step_codes):
                    code = step_codes[i]
                    if code not in visible_codes:
                        lbl.setVisible(False)
                        continue
                    lbl.setVisible(True)
                    step_idx = visible_codes.index(code)
                    if step_idx < completed_steps:
                        # 已完成 → 绿色
                        lbl.setStyleSheet(
                            "QLabel { background-color: #4CAF50; color: white; border-radius: 4px; "
                            "font-size: 10px; font-weight: bold; padding: 2px; }"
                        )
                    elif step_idx == completed_steps:
                        # 当前步骤 → 橙色
                        lbl.setStyleSheet(
                            "QLabel { background-color: #FF9800; color: white; border-radius: 4px; "
                            "font-size: 10px; font-weight: bold; padding: 2px; }"
                        )
                    else:
                        # 未完成 → 灰色
                        lbl.setStyleSheet(
                            "QLabel { background-color: #e0e0e0; color: #888; border-radius: 4px; "
                            "font-size: 10px; font-weight: bold; padding: 2px; }"
                        )

        # 更新进度条
        if hasattr(self, 'workflow_progress_bar'):
            self.workflow_progress_bar.setMaximum(total_steps)
            self.workflow_progress_bar.setValue(completed_steps)
            self.workflow_progress_bar.setFormat(f"{completed_steps}/{total_steps} 步骤完成")

        # 同时更新工作流程管理器的状态（保持兼容性）
        self.workflow_manager.completed_steps = [step[0] for step in steps[:completed_steps]]

    def update_file_manager(self):
        """更新文件管理器"""
        # 获取当前工作目录
        current_dir = self.working_dir_edit.text()
        if current_dir and os.path.exists(current_dir) and os.path.isdir(current_dir):
            # 更新FileManager
            self.file_manager.update_directory(current_dir)

    def auto_detect_files(self):
        """启动时自动检测文件"""
        working_dir = self.working_dir_edit.text()
        if working_dir and os.path.exists(working_dir) and os.path.isdir(working_dir):
            self.auto_fill_input_files(working_dir)
            # 检查检查点文件
            self.check_for_checkpoint_files()

    def closeEvent(self, event):
        """处理窗口关闭事件，确保所有线程安全退出"""
        if hasattr(self, "executors"):
            for executor in self.executors:
                if executor.isRunning():
                    executor.stop()
                    executor.wait()
        event.accept()

    def open_analysis_tools(self):
        """打开分析工具对话框"""
        # 检查分析工具是否可用
        if not ANALYSIS_TOOLS_AVAILABLE or AnalysisToolsDialog is None:
            QMessageBox.warning(self, "功能不可用", "分析工具模块未找到，请确保analysis_tools_dialog.py文件存在。")
            return
            
        # 创建分析工具对话框
        try:
            dialog = AnalysisToolsDialog(self)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开分析工具: {str(e)}")

    def infer_step_type_from_mdp(self, filename):
        """根据MDP文件名推断步骤类型并设置current_step_type"""
        filename_lower = filename.lower()
        
        # 定义文件名与步骤类型的映射
        step_mappings = {
            'em': 'minimization',
            'minim': 'minimization',
            'nvt': 'nvt',
            'npt': 'npt',
            'md': 'production',
            'prod': 'production'
        }
        
        # 查找匹配的步骤类型
        for key, step_type in step_mappings.items():
            if key in filename_lower:
                self.current_step_type = step_type

                # 更新UI以反映当前步骤类型
                self.update_ui_for_step_type(step_type)
                return
        
        # 如果无法推断，询问用户
        step_types = {
            "能量最小化": "minimization",
            "NVT平衡": "nvt", 
            "NPT平衡": "npt",
            "生产运行": "production"
        }
        
        item, ok = QInputDialog.getItem(
            self, 
            "选择步骤类型", 
            "无法从文件名推断步骤类型，请手动选择:", 
            list(step_types.keys()), 
            0, 
            False
        )
        
        if ok and item:
            self.current_step_type = step_types[item]
            self.update_ui_for_step_type(step_types[item])
    
    def update_ui_for_step_type(self, step_type):
        """根据步骤类型更新UI"""
        # 这里可以添加根据步骤类型更新UI的逻辑
        # 例如，可以更新某些标签或启用/禁用某些控件
        pass

    # 原有结构操作方法已被加强版替代

    def preview_edr_file(self, file_path):
        """预览EDR文件"""
        try:
            if EDR_PREVIEW_AVAILABLE:
                dialog = EdrPreviewDialog(file_path, self)
                dialog.exec_()
            else:
                base_name = os.path.splitext(file_path)[0]
                xvg_file = f"{base_name}_energy.xvg"
                
                if os.path.exists(xvg_file):
                    os.unlink(xvg_file)
                
                term_input = "0\n\n"
                
                proc = subprocess.Popen(
                    ['gmx', 'energy', '-f', file_path, '-o', xvg_file, '-xvg', 'none'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = proc.communicate(input=term_input, timeout=300)
                
                if proc.returncode == 0 and os.path.exists(xvg_file):
                    self.show_file_content(xvg_file, "能量数据 (XVG格式)")
                else:
                    QMessageBox.warning(self, "错误", f"导出能量数据失败: {stderr}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理EDR文件时出错: {str(e)}")

    def preview_structure_file(self, file_path):
        """预览结构文件(.gro, .pdb)，提供文本和VMD两种方式"""
        # 创建选择对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("选择预览方式")
        msg_box.setText(f"如何预览文件 {os.path.basename(file_path)}?")
        msg_box.setIcon(QMessageBox.Question)
        
        # 添加按钮
        text_btn = msg_box.addButton("文本查看", QMessageBox.ActionRole)
        vmd_btn = msg_box.addButton("VMD查看", QMessageBox.ActionRole)
        cancel_btn = msg_box.addButton("取消", QMessageBox.RejectRole)
        
        # 显示对话框
        msg_box.exec_()
        
        # 根据用户选择执行相应操作
        if msg_box.clickedButton() == text_btn:
            # 文本方式查看
            self.show_text_file(file_path)
        elif msg_box.clickedButton() == vmd_btn:
            # VMD方式查看
            self.open_with_vmd(file_path)
        # 如果点击取消则不执行任何操作
    #####################################

    def preview_xtc_file(self, file_path):
        """预览XTC轨迹文件并打开分析对话框"""
        working_dir = os.path.dirname(file_path)
        sim_type = self.sim_type_combo.currentText()
        dialog = TrajectoryAnalysisDialog(working_dir, sim_type, self)
        # 自动填入轨迹文件路径
        if hasattr(dialog, 'trajectory_file_edit'):
            dialog.trajectory_file_edit.setText(file_path)
        dialog.exec_()
    
    def preview_cpt_file(self, file_path):
        """预览CPT文件"""
        # 询问用户是否要转换为文本格式查看
        reply = QMessageBox.question(
            self, 
            "检查点文件", 
            "CPT文件是二进制检查点文件，需要转换为文本格式才能查看。\n是否使用gmx convert-tpr进行转换查看？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # 创建转换后的文件名
                base_name = os.path.splitext(file_path)[0]
                txt_file = f"{base_name}_checkpoint.txt"
                
                # 执行转换命令
                command = f"gmx convert-tpr -s '{file_path}' -o '{txt_file}'"
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.path.dirname(file_path)
                )
                stdout, stderr = process.communicate()
                
                if process.returncode == 0 and os.path.exists(txt_file):
                    self.show_file_content(txt_file, "检查点文件内容")
                else:
                    QMessageBox.warning(self, "错误", f"转换检查点文件失败: {stderr.decode()}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"处理CPT文件时出错: {str(e)}")

    def count_residues_in_pdb(self, pdb_file):
        """解析PDB文件并计算残基数"""
        if not pdb_file or not os.path.exists(pdb_file):
            return 0
            
        residues = set()
        try:
            with open(pdb_file, 'r') as f:
                for line in f:
                    if line.startswith('ATOM') or line.startswith('HETATM'):
                        # PDB格式中残基编号在第23-26列（1-based索引22-26）
                        residue_id = line[22:26].strip()
                        residue_name = line[17:20].strip()
                        # 使用残基编号和链ID的组合作为唯一标识（防止不同链有相同编号）
                        chain_id = line[21:22]
                        unique_id = f"{chain_id}_{residue_id}_{residue_name}"
                        residues.add(unique_id)
            return len(residues)
        except Exception as e:
            print(f"解析PDB文件时出错: {e}")
            return 0

    def check_single_residue_warning(self):
        """检查是否为单残基结构并显示警告"""
        pdb_file = self.pdb2gmx_pdb_file.text()
        if not pdb_file or not os.path.exists(pdb_file):
            return
            
        residue_count = self.count_residues_in_pdb(pdb_file)
        forcefield = self.pdb2gmx_forcefield_combo.currentText()
        
        # 如果是单残基结构且使用AMBER力场，显示警告
        if residue_count == 1 and forcefield.startswith('amber'):
            QMessageBox.warning(
                self, 
                "单残基结构检测", 
                "检测到单残基结构。若为小分子，请使用 GAFF 力场；若为氨基酸，请在交互模式中选择正确的 N/C 末端类型。"
            )
        # 如果是单残基且使用AMBER力场，显示额外提示
        elif residue_count == 1 and forcefield.startswith('amber'):
            reply = QMessageBox.question(
                self,
                "AMBER力场提示",
                "注意：AMBER 力场要求蛋白质末端正确命名。建议交互式运行 pdb2gmx 以选择末端类型。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if not self._check_vmd_available():
                return

            config = self._load_config()
            vmd_path = config.get("vmd_path", "vmd")

            vmd_cmd = [vmd_path, gro_file, file_path]
            subprocess.Popen(vmd_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def preview_tpr_file(self, file_path):
        """预览TPR文件"""
        try:
            # 使用gmx dump导出TPR文件信息
            base_name = os.path.splitext(file_path)[0]
            txt_file = f"{base_name}_tpr_info.txt"
            
            command = f"gmx dump -s '{file_path}' > '{txt_file}'"
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(file_path)
            )
            stdout, stderr = process.communicate()
            
            if process.returncode == 0 and os.path.exists(txt_file):
                self.show_file_content(txt_file, "TPR文件信息")
            else:
                QMessageBox.warning(self, "错误", f"导出TPR信息失败: {stderr.decode()}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理TPR文件时出错: {str(e)}")


    def open_with_vmd(self, file_path):
        """使用VMD打开文件"""
        try:
            if not self._check_vmd_available():
                return

            # 获取VMD路径
            config = self._load_config()
            vmd_path = config.get("vmd_path", "vmd")

            vmd_cmd = [vmd_path, file_path]
            subprocess.Popen(vmd_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动VMD时出错: {str(e)}")

    def _get_config_path(self):
        """获取配置文件路径"""
        return os.path.join(os.path.expanduser("~"), ".gromacs_ui_config.json")

    def _load_config(self):
        """加载配置文件"""
        config_path = self._get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_config(self, config):
        """保存配置文件"""
        try:
            with open(self._get_config_path(), 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def _find_vmd(self):
        """自动查找VMD可执行文件，返回路径或None"""
        # 1. 检查已保存的配置
        config = self._load_config()
        saved_path = config.get("vmd_path", "")
        if saved_path and os.path.isfile(saved_path) and os.access(saved_path, os.X_OK):
            return saved_path

        # 2. 检查PATH
        path_result = shutil.which("vmd")
        if path_result:
            return path_result

        # 3. 检查常见安装路径
        common_paths = [
            "/usr/local/bin/vmd",
            "/usr/bin/vmd",
            "/opt/vmd/bin/vmd",
            "/opt/VMD/vmd",
            os.path.expanduser("~/vmd/bin/vmd"),
            os.path.expanduser("~/VMD/vmd"),
            "/usr/local/lib/vmd/vmd",
            "/Applications/VMD.app/Contents/MacOS/VMD",  # macOS
        ]
        for p in common_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p

        return None

    def _check_vmd_available(self):
        """检查VMD是否可用，不可用则提示用户设置路径"""
        vmd_path = self._find_vmd()
        if vmd_path:
            # 保存到配置
            config = self._load_config()
            if config.get("vmd_path") != vmd_path:
                config["vmd_path"] = vmd_path
                self._save_config(config)
            return True

        # 未找到VMD，提示用户设置
        reply = QMessageBox.question(
            self, "VMD 未找到",
            "未在系统中找到 VMD 程序。\n\n"
            "VMD 用于可视化预览轨迹和结构文件。\n"
            "您可以选择：\n"
            "1. 手动指定 VMD 可执行文件路径\n"
            "2. 跳过（稍后可在设置中配置）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择 VMD 可执行文件", "/usr/local/bin",
                "可执行文件 (*);;所有文件 (*)",
                options=QFileDialog.DontUseNativeDialog
            )
            if path and os.path.isfile(path):
                config = self._load_config()
                config["vmd_path"] = path
                self._save_config(config)
                QMessageBox.information(self, "成功", f"VMD 路径已保存:\n{path}")
                return True
        return False

    def show_file_content(self, file_path, title="文件内容"):
        """以文本方式显示文件内容"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                
            # 创建一个新窗口显示文件内容
            preview_window = QMainWindow(self)
            preview_window.setWindowTitle(f"{title} - {os.path.basename(file_path)}")
            preview_window.setGeometry(200, 200, 800, 600)
            
            text_edit = QPlainTextEdit()
            text_edit.setPlainText(content)
            text_edit.setReadOnly(True)
            
            preview_window.setCentralWidget(text_edit)
            preview_window.show()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取文件时出错: {str(e)}")

    def show_text_file(self, file_path):
        """显示文本文件内容"""
        self.show_file_content(file_path, "文本文件预览")

    def check_box_dimensions(self):
        """验证盒子尺寸"""
        file_path = self.check_file_input.text()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "文件错误", "请选择有效的文件")
            return
            
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            if len(lines) >= 3:
                # 盒子信息在最后一行
                box_line = lines[-1].strip()
                box_values = box_line.split()
                
                if len(box_values) >= 3:
                    try:
                        x_size = float(box_values[0])
                        y_size = float(box_values[1])
                        z_size = float(box_values[2])
                        
                        result_text = f"盒子尺寸信息:\n"
                        result_text += f"  X方向: {x_size:.3f} nm\n"
                        result_text += f"  Y方向: {y_size:.3f} nm\n"
                        result_text += f"  Z方向: {z_size:.3f} nm\n"
                        result_text += f"  体积: {x_size*y_size*z_size:.3f} nm³\n"
                        
                        # 检查盒子尺寸是否合理
                        if x_size < 1.0 or y_size < 1.0 or z_size < 1.0:
                            result_text += "\n警告: 盒子尺寸过小，可能影响模拟质量"
                        elif x_size > 20.0 or y_size > 20.0 or z_size > 20.0:
                            result_text += "\n注意: 盒子尺寸较大，计算成本较高"
                            
                        # 将结果写入日志输出面板
                        self.log_output.append(f"<b>盒子尺寸检查结果:</b><br>{result_text.replace(chr(10), '<br>')}")
                    except ValueError:
                        # 将结果写入日志输出面板
                        self.log_output.append("<b>盒子尺寸检查结果:</b><br>无法解析盒子尺寸")
                else:
                    # 将结果写入日志输出面板
                    self.log_output.append("<b>盒子尺寸检查结果:</b><br>盒子信息格式不正确")
            else:
                # 将结果写入日志输出面板
                self.log_output.append("<b>盒子尺寸检查结果:</b><br>文件内容不完整")
                
        except Exception as e:
            # 将结果写入日志输出面板
            self.log_output.append(f"<b>盒子尺寸检查结果:</b><br>检查失败: {str(e)}")

    def generate_box_command(self):
        """生成editconf命令用于定义模拟盒子"""
        # 获取输入参数
        input_file = self.box_input_file.text()
        output_file = self.box_output_file.text()
        box_type_text = self.box_type_combo.currentText()
        distance = self.box_distance_spin.value()
        center_molecule = self.box_center_check.isChecked()
        
        # 验证输入
        if not input_file or not output_file:
            QMessageBox.warning(self, "参数错误", "请输入完整的输入和输出文件路径")
            return None
            
        # 解析盒子类型
        box_type_map = {
            "立方体 (cubic)": "cubic",
            "十二面体 (dodecahedron)": "dodecahedron", 
            "八面体 (octahedron)": "octahedron",
            "三斜晶系 (triclinic)": "triclinic"
        }
        box_type = box_type_map.get(box_type_text, "dodecahedron")
        
        # 构建命令
        command = f"gmx editconf -f \"{input_file}\" -o \"{output_file}\" -bt {box_type} -d {distance:.1f}"
        if center_molecule:
            command += " -c"
            
        # 显示命令预览到右侧面板
        self.cmd_preview_text.setPlainText(command)
        return command

    def execute_box_definition(self):
        """执行盒子定义步骤"""
        command = self.generate_box_command()
        if command:
            self.solvation_status_label.setText("正在执行盒子定义...")
            
            # 使用CommandExecutor异步执行
            working_dir = self.working_dir_edit.text() or os.getcwd()
            executor = CommandExecutor([command], working_dir)
            
            # 将线程对象添加到executors列表中，确保其生命周期得到管理
            self.executors.append(executor)
            
            # 连接信号
            executor.output_ready.connect(lambda text: self.append_output(text, 'stdout'))
            executor.error_ready.connect(lambda text: self.append_output(text, 'stderr'))
            executor.finished_signal.connect(self._on_box_definition_finished)
            executor.progress_update.connect(lambda msg: self.solvation_status_label.setText(msg))
            
            # 启动执行
            executor.start()
            
            # 在输出区域显示开始执行的命令
            self.append_output(f"=== 开始执行盒子定义 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(f"$ {command}", 'command')
            # 添加到日志
            self.log_output.append(f"<b>开始执行盒子定义:</b><br>{command}<br>")

    def generate_solvate_command(self):
        """生成solvate命令用于添加溶剂"""
        # 获取输入参数
        input_file = self.solvate_input_file.text()
        output_file = self.solvate_output_file.text()
        water_model = self.water_model_combo.currentText()
        water_structure = self.water_structure_file.text()
        
        # 验证输入
        if not input_file or not output_file:
            QMessageBox.warning(self, "参数错误", "请输入完整的输入和输出文件路径")
            return None
            
        # 构建命令
        if water_model == "spc216":
            command = f"gmx solvate -cp \"{input_file}\" -cs {water_structure} -o \"{output_file}\" -p topol.top"
        else:
            # 对于其他水模型，使用指定的水结构文件
            command = f"gmx solvate -cp \"{input_file}\" -cs {water_structure} -o \"{output_file}\" -p topol.top"
        return command

    def execute_solvation(self):
        """执行溶剂化步骤"""
        command = self.generate_solvate_command()
        if command:
            self.solvation_status_label.setText("正在执行溶剂化...")
            
            # 使用CommandExecutor异步执行
            working_dir = self.working_dir_edit.text() or os.getcwd()
            executor = CommandExecutor([command], working_dir)
            
            # 将线程对象添加到executors列表中，确保其生命周期得到管理
            self.executors.append(executor)
            
            # 连接信号
            executor.output_ready.connect(lambda text: self.append_output(text, 'stdout'))
            executor.error_ready.connect(lambda text: self.append_output(text, 'stderr'))
            executor.finished_signal.connect(self._on_solvation_finished)
            executor.progress_update.connect(lambda msg: self.solvation_status_label.setText(msg))
            
            # 启动执行
            executor.start()
            
            # 在输出区域显示开始执行的命令
            self.append_output(f"=== 开始执行溶剂化 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(f"$ {command}", 'command')
            # 添加到日志
            self.log_output.append(f"<b>开始执行溶剂化:</b><br>{command}<br>")

    def _on_charge_check_finished(self, return_code, message):
        """电荷检查执行完成处理"""
        if return_code == 0:
            self.solvation_status_label.setText("电荷检查完成")
            self.append_output(f"=== 电荷检查执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
        else:
            self.solvation_status_label.setText("电荷检查失败")
            self.append_output(f"=== 电荷检查执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>电荷检查执行{status}:</b> {message}<br>")

    def generate_genion_command(self):
        """生成genion命令用于添加离子"""
        # 获取输入参数
        input_file = self.ion_input_file.text()
        output_file = self.ion_output_file.text()
        neutralize = self.neutralize_check.isChecked()
        conc = self.ion_concentration_spin.value()
        ion_type = self.positive_ion_combo.currentText()
        
        # 验证输入
        if not input_file or not output_file:
            QMessageBox.warning(self, "参数错误", "请输入完整的输入和输出文件路径")
            return None
            
        # 构建命令
        command = f"gmx genion -s \"{input_file}\" -o \"{output_file}\" -p topol.top -pname {ion_type} -nname CL -conc {conc}"
        if neutralize:
            command += " -neutral"
            
        # 显示命令预览到右侧面板
        self.cmd_preview_text.setPlainText(command)
        return command

    def execute_ion_addition(self):
        """执行离子添加步骤"""
        command = self.generate_genion_command()
        if command:
            self.solvation_status_label.setText("正在执行离子添加...")
            
            # 分割命令并依次执行
            commands = command.split(" && ")
            
            # 使用CommandExecutor异步执行
            working_dir = self.working_dir_edit.text() or os.getcwd()
            executor = CommandExecutor(commands, working_dir)
            
            # 将线程对象添加到executors列表中，确保其生命周期得到管理
            self.executors.append(executor)
            
            # 连接信号
            executor.output_ready.connect(lambda text: self.append_output(text, 'stdout'))
            executor.error_ready.connect(lambda text: self.append_output(text, 'stderr'))
            executor.finished_signal.connect(self._on_ion_addition_finished)
            executor.progress_update.connect(lambda msg: self.solvation_status_label.setText(msg))
            
            # 启动执行
            executor.start()
            
            # 在输出区域显示开始执行的命令
            self.append_output(f"=== 开始执行离子添加 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(f"$ {command}", 'command')
            # 添加到日志
            self.log_output.append(f"<b>开始执行离子添加:</b><br>{command}<br>")

    def create_pdb2gmx_tab(self):
        """创建pdb2gmx预处理选项卡"""
        self.pdb2gmx_tab = QWidget()
        layout = QGridLayout(self.pdb2gmx_tab)
        
        # PDB文件选择
        layout.addWidget(QLabel("PDB文件:"), 0, 0)
        self.pdb2gmx_pdb_file = QLineEdit()
        self.pdb2gmx_pdb_file.setPlaceholderText("protein.pdb")
        btn_pdb_file = QPushButton("浏览")
        btn_pdb_file.clicked.connect(lambda: self.browse_structure_file(self.pdb2gmx_pdb_file, "选择PDB文件", "PDB Files (*.pdb);;All Files (*)"))
        layout.addWidget(self.pdb2gmx_pdb_file, 0, 1)
        layout.addWidget(btn_pdb_file, 0, 2)
        
        # 力场选择
        layout.addWidget(QLabel("力场:"), 1, 0)
        self.pdb2gmx_forcefield_combo = QComboBox()
        self.pdb2gmx_forcefield_combo.addItems([
            "amber99sb-ildn", "amber99sb", "amber03", "amber94", "amber96", "amber99",
            "charmm27", "gromos43a1", "gromos43a2", "gromos45a3", "gromos53a5", "gromos53a6", "gromos54a7",
            "oplsaa"
        ])
        self.pdb2gmx_forcefield_combo.setCurrentText("amber99sb-ildn")
        self.pdb2gmx_forcefield_combo.currentTextChanged.connect(self.update_forcefield_info)
        layout.addWidget(self.pdb2gmx_forcefield_combo, 1, 1, 1, 2)
        
        # 力场适用说明
        self.pdb2gmx_forcefield_info = QLabel("")
        self.pdb2gmx_forcefield_info.setWordWrap(True)
        self.pdb2gmx_forcefield_info.setStyleSheet("QLabel { color: #0066cc; font-size: 11px; padding: 5px; background-color: #f0f8ff; border: 1px solid #cce6ff; border-radius: 3px; }")
        layout.addWidget(self.pdb2gmx_forcefield_info, 2, 0, 1, 3)
        self.update_forcefield_info(self.pdb2gmx_forcefield_combo.currentText())
        
        # 水模型选择
        layout.addWidget(QLabel("水模型:"), 3, 0)
        self.pdb2gmx_water_model_combo = QComboBox()
        self.pdb2gmx_water_model_combo.addItems([
            "tip3p", "tip4p", "tip5p", "spce", "spc", "spc216"
        ])
        self.pdb2gmx_water_model_combo.setCurrentText("tip3p")
        layout.addWidget(self.pdb2gmx_water_model_combo, 3, 1, 1, 2)
        
        # 交互式选项
        self.pdb2gmx_interactive_checkbox = QCheckBox("交互式选择末端和氢原子（推荐新手）")
        self.pdb2gmx_interactive_checkbox.setChecked(True)
        layout.addWidget(self.pdb2gmx_interactive_checkbox, 4, 0, 1, 3)
        
        # 输出文件
        layout.addWidget(QLabel("输出结构文件:"), 5, 0)
        self.pdb2gmx_output_gro = QLineEdit()
        self.pdb2gmx_output_gro.setText("processed.gro")
        layout.addWidget(self.pdb2gmx_output_gro, 5, 1, 1, 2)
        
        # 拓扑文件
        layout.addWidget(QLabel("拓扑文件:"), 6, 0)
        self.pdb2gmx_output_top = QLineEdit()
        self.pdb2gmx_output_top.setText("topol.top")
        layout.addWidget(self.pdb2gmx_output_top, 6, 1, 1, 2)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        self.generate_pdb2gmx_cmd_btn = QPushButton("生成pdb2gmx命令")
        self.execute_pdb2gmx_cmd_btn = QPushButton("执行pdb2gmx命令")
        self.generate_pdb2gmx_cmd_btn.clicked.connect(self.generate_pdb2gmx_command)
        self.execute_pdb2gmx_cmd_btn.clicked.connect(self.execute_pdb2gmx)
        btn_layout.addWidget(self.generate_pdb2gmx_cmd_btn)
        btn_layout.addWidget(self.execute_pdb2gmx_cmd_btn)
        layout.addLayout(btn_layout, 7, 0, 1, 3)
        
        # 命令预览
        layout.addWidget(QLabel("命令预览:"), 8, 0)
        self.pdb2gmx_cmd_preview = QTextEdit()
        self.pdb2gmx_cmd_preview.setMaximumHeight(80)
        self.pdb2gmx_cmd_preview.setReadOnly(True)
        layout.addWidget(self.pdb2gmx_cmd_preview, 9, 0, 1, 3)
        
        self.structure_prep_tabs.addTab(self.pdb2gmx_tab, "pdb2gmx预处理")

    def generate_pdb2gmx_command(self):
        """生成pdb2gmx命令"""
        pdb_file = self.pdb2gmx_pdb_file.text()
        forcefield = self.pdb2gmx_forcefield_combo.currentText()
        water_model = self.pdb2gmx_water_model_combo.currentText()
        output_gro = self.pdb2gmx_output_gro.text()
        output_top = self.pdb2gmx_output_top.text()
        interactive = self.pdb2gmx_interactive_checkbox.isChecked()
        
        if not pdb_file:
            QMessageBox.warning(self, "参数错误", "请选择PDB文件")
            return None
            
        # 基础命令
        command = f"gmx pdb2gmx -f {pdb_file} -o {output_gro} -p {output_top} -ff {forcefield} -water {water_model}"
        
        # 如果不使用交互式模式，添加-ter和-his参数
        if not interactive:
            command += " -ter -his"
            
        self.pdb2gmx_cmd_preview.setPlainText(command)
        return command

    def execute_pdb2gmx(self):
        """执行pdb2gmx命令"""
        # 检查单残基结构警告
        self.check_single_residue_warning()
        
        command = self.generate_pdb2gmx_command()
        if command:
            # 使用CommandExecutor异步执行
            working_dir = self.working_dir_edit.text() or os.getcwd()
            executor = CommandExecutor([command], working_dir)
            
            # 将线程对象添加到executors列表中，确保其生命周期得到管理
            self.executors.append(executor)
            
            # 连接信号
            executor.output_ready.connect(lambda text: self.append_output(text, 'stdout'))
            executor.error_ready.connect(self.handle_pdb2gmx_error)
            executor.finished_signal.connect(self._on_pdb2gmx_finished)
            executor.progress_update.connect(lambda msg: self.status_label.setText(msg))
            
            # 启动执行
            executor.start()
            
            # 在输出区域显示开始执行的命令
            self.append_output(f"=== 开始执行pdb2gmx {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(f"$ {command}", 'command')
            # 添加到日志
            self.log_output.append(f"<b>开始执行pdb2gmx:</b><br>{command}<br>")

    def handle_pdb2gmx_error(self, error_text):
        """处理pdb2gmx错误信息"""
        # 检查是否为"no residue type for 'XXX' as standalone"错误
        import re
        match = re.search(r"no residue type for '(\w+)' as standalone", error_text)
        if match:
            residue_name = match.group(1)
            friendly_error = f"""❌ 错误：力场不支持孤立残基 '{residue_name}'。
✅ 解决方案：
   • 运行时不加 -ter 参数，让 GROMACS 交互式询问末端类型
   • 或将 PDB 中的 '{residue_name}' 改为 'N{residue_name}'（N端）和 'C{residue_name}'（C端）"""
            self.append_output(friendly_error, 'stderr')
        else:
            # 显示原始错误信息
            self.append_output(error_text, 'stderr')

    def _on_pdb2gmx_finished(self, return_code, message):
        """pdb2gmx执行完成处理"""
        if return_code == 0:
            QMessageBox.information(self, "成功", "pdb2gmx预处理步骤执行成功")
            self.append_output(f"=== pdb2gmx执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
        else:
            QMessageBox.critical(self, "错误", f"pdb2gmx执行失败:\n{message}")
            self.append_output(f"=== pdb2gmx执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>pdb2gmx执行{status}:</b> {message}<br>")

    def _on_box_definition_finished(self, return_code, message):
        """盒子定义执行完成处理"""
        if return_code == 0:
            self.solvation_status_label.setText("盒子定义完成")
            QMessageBox.information(self, "成功", "盒子定义步骤执行成功")
            # 自动更新下一步的输入文件
            self.solvate_input_file.setText(self.box_output_file.text())
            self.append_output(f"=== 盒子定义执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
        else:
            self.solvation_status_label.setText("盒子定义失败")
            QMessageBox.critical(self, "错误", f"盒子定义失败:\n{message}")
            self.append_output(f"=== 盒子定义执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>盒子定义执行{status}:</b> {message}<br>")

    def _on_ion_addition_finished(self, return_code, message):
        """离子添加执行完成处理"""
        if return_code == 0:
            self.solvation_status_label.setText("离子添加完成")
            QMessageBox.information(self, "成功", "离子添加步骤执行成功")
            # 更新检查文件输入
            self.check_file_input.setText(self.ion_output_file.text())
            self.append_output(f"=== 离子添加执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
        else:
            self.solvation_status_label.setText("离子添加失败")
            QMessageBox.critical(self, "错误", f"离子添加失败:\n{message}")
            self.append_output(f"=== 离子添加执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>离子添加执行{status}:</b> {message}<br>")

    def _on_solvation_finished(self, return_code, message):
        """溶剂化执行完成处理"""
        if return_code == 0:
            self.solvation_status_label.setText("溶剂化完成")
            QMessageBox.information(self, "成功", "溶剂化步骤执行成功")
            # 自动更新下一步的输入文件
            self.ion_input_file.setText(self.solvate_output_file.text())
            self.append_output(f"=== 溶剂化执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
        else:
            self.solvation_status_label.setText("溶剂化失败")
            QMessageBox.critical(self, "错误", f"溶剂化失败:\n{message}")
            self.append_output(f"=== 溶剂化执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>溶剂化执行{status}:</b> {message}<br>")

    def _on_complete_solvation_finished(self, return_code, message):
        """完整溶剂化流程执行完成处理"""
        if return_code == 0:
            self.solvation_status_label.setText("完整溶剂化流程完成")
            QMessageBox.information(self, "完成", "完整溶剂化流程执行完成")
            self.append_output(f"=== 完整溶剂化流程执行成功 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            # 更新检查文件输入
            self.check_file_input.setText(self.ion_output_file.text())
        else:
            self.solvation_status_label.setText("完整溶剂化流程失败")
            QMessageBox.critical(self, "错误", f"完整溶剂化流程失败:\n{message}")
            self.append_output(f"=== 完整溶剂化流程执行失败 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(message, 'stderr')
        # 添加到日志
        status = "成功" if return_code == 0 else "失败"
        self.log_output.append(f"<b>完整溶剂化流程执行{status}:</b> {message}<br>")

    def run_complete_solvation(self):
        """一键执行完整溶剂化流程"""
        reply = QMessageBox.question(
            self, 
            "确认执行", 
            "将依次执行以下步骤:\n1. 定义盒子\n2. 添加溶剂\n3. 添加离子\n\n是否继续?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.solvation_status_label.setText("正在执行完整溶剂化流程...")
            
            # 构建完整命令链
            commands = []
            
            # 生成盒子定义命令
            box_command = self.generate_box_command()
            if box_command:
                commands.append(box_command)
            
            # 生成溶剂化命令
            solvate_command = self.generate_solvate_command()
            if solvate_command:
                commands.append(solvate_command)
            
            # 生成离子添加命令
            ion_command = self.generate_genion_command()
            if ion_command:
                # 分割离子命令
                ion_commands = ion_command.split(" && ")
                commands.extend([cmd.strip() for cmd in ion_commands])
            
            if commands:
                # 使用CommandExecutor异步执行完整命令链
                working_dir = self.working_dir_edit.text() or os.getcwd()
                executor = CommandExecutor(commands, working_dir)
                
                # 连接信号
                executor.output_ready.connect(lambda text: self.append_output(text, 'stdout'))
                executor.error_ready.connect(lambda text: self.append_output(text, 'stderr'))
                executor.finished_signal.connect(self._on_complete_solvation_finished)
                executor.progress_update.connect(lambda msg: self.solvation_status_label.setText(msg))
                
                # 启动执行
                executor.start()
                
                # 在输出区域显示开始执行的命令
                self.append_output(f"=== 开始执行完整溶剂化流程 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
                for i, cmd in enumerate(commands):
                    self.append_output(f"$ [{i+1}] {cmd}", 'command')
                # 添加到日志
                self.log_output.append(f"<b>开始执行完整溶剂化流程:</b><br>{'<br>'.join(commands)}<br>")

    def check_system_files(self):
        """检查体系文件完整性"""
        file_path = self.check_file_input.text()
        if not file_path:
            QMessageBox.warning(self, "参数错误", "请选择要检查的文件")
            return
            
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "文件不存在", f"文件不存在: {file_path}")
            return
            
        try:
            # 检查文件格式
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            if len(lines) < 2:
                QMessageBox.warning(self, "文件格式错误", "文件内容不完整")
                return
                
            # 检查标题行和原子数行
            title_line = lines[0].strip()
            atom_count_line = lines[1].strip()
            
            try:
                atom_count = int(atom_count_line)
                if atom_count < 0:
                    raise ValueError("原子数不能为负数")
            except ValueError:
                QMessageBox.warning(self, "文件格式错误", "第二行应为原子数")
                return
                
            # 检查坐标行数
            coordinate_lines = lines[2:2+atom_count]

            if len(coordinate_lines) != atom_count:
                QMessageBox.warning(self, "文件格式错误", f"坐标行数({len(coordinate_lines)})与声明的原子数({atom_count})不符")
                return
                
            QMessageBox.information(self, "检查完成", f"文件检查通过!\n文件: {os.path.basename(file_path)}\n原子数: {atom_count}")
            
        except Exception as e:
            QMessageBox.critical(self, "检查失败", f"文件检查失败:\n{str(e)}")

    def count_atoms(self):
        """统计原子数目"""
        file_path = self.check_file_input.text()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "文件错误", "请选择有效的文件")
            return
            
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            if len(lines) >= 2:
                atom_count = int(lines[1].strip())
                result_text = f"文件: {os.path.basename(file_path)}\n总原子数: {atom_count}\n\n"
                
                # 尝试分析原子类型分布
                atom_types = {}
                for i in range(2, min(2+atom_count, len(lines))):
                    parts = lines[i].strip().split()
                    if len(parts) >= 2:
                        atom_type = parts[1]
                        atom_types[atom_type] = atom_types.get(atom_type, 0) + 1
                        
                result_text += "原子类型分布:\n"
                for atom_type, count in sorted(atom_types.items()):
                    result_text += f"  {atom_type}: {count}\n"
                    
                # 将结果写入日志输出面板
                self.log_output.append(f"<b>原子计数结果:</b><br>{result_text.replace(chr(10), '<br>')}")
            else:
                # 将结果写入日志输出面板
                self.log_output.append("<b>原子计数结果:</b><br>无法读取原子数")
                
        except Exception as e:
            # 将结果写入日志输出面板
            self.log_output.append(f"<b>原子计数结果:</b><br>统计失败: {str(e)}")

    def check_total_charge(self):
        """检查体系总电荷"""
        file_path = self.check_file_input.text()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "文件错误", "请选择有效的文件")
            return
            
        try:
            # 使用gmx命令检查电荷
            working_dir = self.working_dir_edit.text() or os.getcwd()
            command = f"gmx check -f \"{file_path}\""
            
            # 使用CommandExecutor异步执行
            executor = CommandExecutor([command], working_dir)
            
            # 将线程对象添加到executors列表中，确保其生命周期得到管理
            self.executors.append(executor)
            
            # 连接信号
            executor.output_ready.connect(lambda text: self.append_output(text, 'stdout'))
            executor.error_ready.connect(lambda text: self.append_output(text, 'stderr'))
            executor.finished_signal.connect(self._on_charge_check_finished)
            executor.progress_update.connect(lambda msg: self.solvation_status_label.setText(msg))
            
            # 启动执行
            executor.start()
            
            # 在输出区域显示开始执行的命令
            self.append_output(f"=== 开始检查体系总电荷 {time.strftime('%Y-%m-%d %H:%M:%S')} ===", 'command')
            self.append_output(f"$ {command}", 'command')
            # 添加到日志
            self.log_output.append(f"<b>开始检查体系总电荷:</b><br>{command}<br>")
            
        except Exception as e:
            # 将结果写入日志输出面板
            self.log_output.append(f"<b>电荷检查结果:</b><br>检查失败: {str(e)}")


# MDP参数注释字典（国际化）
PARAM_COMMENTS = {
    # ========= Common Parameters =========
    "integrator": {
        "en": "Algorithm used for simulation (e.g., steep, md, sd)",
        "zh": "用于模拟的积分算法（如 steep, md, sd）"
    },
    "nsteps": {
        "en": "Number of steps in the simulation",
        "zh": "模拟的步数"
    },
    "dt": {
        "en": "Time step in picoseconds",
        "zh": "时间步长（皮秒）"
    },
    "nstxout": {
        "en": "Frequency to write coordinates to trajectory",
        "zh": "保存坐标到轨迹文件的频率"
    },
    "nstvout": {
        "en": "Frequency to write velocities to trajectory",
        "zh": "保存速度到轨迹文件的频率"
    },
    "nstenergy": {
        "en": "Frequency to write energies to energy file",
        "zh": "保存能量到能量文件的频率"
    },
    "nstlog": {
        "en": "Frequency to write to log file",
        "zh": "写入日志文件的频率"
    },
    "continuation": {
        "en": "Continue from a previous simulation (yes/no)",
        "zh": "是否从之前的模拟继续"
    },
    "constraints": {
        "en": "Type of constraints (e.g., h-bonds, all-bonds)",
        "zh": "约束类型（如氢键，全键）"
    },
    "cutoff-scheme": {
        "en": "Cutoff scheme (Verlet or group)",
        "zh": "截断方案（Verlet 或 group）"
    },
    "coulombtype": {
        "en": "Electrostatics method (e.g., PME, reaction-field)",
        "zh": "静电相互作用方法（如 PME, reaction-field）"
    },
    "rcoulomb": {
        "en": "Coulomb cutoff radius (nm)",
        "zh": "库仑相互作用截断半径 (nm)"
    },
    "vdwtype": {
        "en": "Van der Waals method (Cut-off, PME)",
        "zh": "范德华相互作用方法（截断，PME）"
    },
    "rvdw": {
        "en": "Van der Waals cutoff radius (nm)",
        "zh": "范德华截断半径 (nm)"
    },
    "tcoupl": {
        "en": "Temperature coupling method",
        "zh": "温度耦合方法"
    },
    "tc-grps": {
        "en": "Temperature coupling groups",
        "zh": "温度耦合分组"
    },
    "tau_t": {
        "en": "Time constant for temperature coupling (ps)",
        "zh": "温度耦合时间常数 (ps)"
    },
    "ref_t": {
        "en": "Reference temperature (K)",
        "zh": "参考温度 (K)"
    },
    "pcoupl": {
        "en": "Pressure coupling method",
        "zh": "压力耦合方法"
    },
    "pcoupltype": {
        "en": "Type of pressure coupling (isotropic/semiisotropic)",
        "zh": "压力耦合类型（各向同性/半各向同性）"
    },
    "tau_p": {
        "en": "Time constant for pressure coupling (ps)",
        "zh": "压力耦合时间常数 (ps)"
    },
    "ref_p": {
        "en": "Reference pressure (bar)",
        "zh": "参考压力 (bar)"
    },
    "compressibility": {
        "en": "Compressibility (1/bar)",
        "zh": "可压缩性 (1/bar)"
    },
    "gen_vel": {
        "en": "Generate initial velocities (yes/no)",
        "zh": "是否生成初始速度"
    },
    "gen_temp": {
        "en": "Temperature for velocity generation (K)",
        "zh": "生成速度的温度 (K)"
    },
    "gen_seed": {
        "en": "Random seed for velocity generation",
        "zh": "生成速度的随机种子"
    },

    # ========= Energy Minimization =========
    "emtol": {
        "en": "Convergence criterion (kJ/mol/nm)",
        "zh": "收敛准则 (kJ/mol/nm)"
    },
    "emstep": {
        "en": "Initial step size (nm)",
        "zh": "初始步长 (nm)"
    },

    # ========= Production MD =========
    "pbc": {
        "en": "Periodic boundary conditions (xyz/no)",
        "zh": "周期性边界条件 (xyz/no)"
    },
    "DispCorr": {
        "en": "Dispersion correction for energy/pressure",
        "zh": "能量/压力的色散修正"
    },
    "nstcomm": {
        "en": "Frequency for COM motion removal",
        "zh": "去除质心运动的频率"
    },
    "nstlist": {
        "en": "Neighbor list update frequency",
        "zh": "邻居表更新频率"
    },
    "rlist": {
        "en": "Neighbor list cutoff (nm)",
        "zh": "邻居表截断 (nm)"
    },
    "fourierspacing": {
        "en": "FFT grid spacing for PME (nm)",
        "zh": "PME FFT 网格间距 (nm)"
    },
    "pme_order": {
        "en": "Interpolation order for PME",
        "zh": "PME 插值阶数"
    }
}

# MDP参数知识库
MDP_KNOWLEDGE_BASE = [
  {
    "key": "integrator",
    "title": "Integrator",
    "syntax": "integrator = md | md-vv | sd | bd | ...",
    "description": "选择积分器，控制动力学模拟方式。",
    "values": "md (默认，leap-frog), md-vv (velocity Verlet), sd (Langevin dynamics), bd (Brownian dynamics)",
    "when_to_use": "一般分子动力学使用 md；需要温度耦合精度时用 md-vv；扩散或粗粒化可用 sd/bd。",
    "effects": "影响时间推进方式和数值稳定性。",
    "examples": "integrator = md",
    "notes": "生产模拟推荐 md 或 md-vv；sd/bd 常用于特殊场景。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "nsteps",
    "title": "Number of steps",
    "syntax": "nsteps = 50000",
    "description": "模拟的步数。模拟时间 = nsteps * dt。",
    "values": "整数，默认 -1 表示无限。",
    "when_to_use": "根据所需模拟时间设定。",
    "effects": "决定模拟总时长。",
    "examples": "nsteps = 1000000 ; 2 ns if dt=0.002",
    "notes": "结合 dt 设置合理模拟时长。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "dt",
    "title": "Time step",
    "syntax": "dt = 0.002",
    "description": "积分步长，单位 ps。",
    "values": "典型值 0.001–0.002 ps",
    "when_to_use": "取决于体系和约束。使用约束（如 LINCS）时可取 2 fs；无约束需更小。",
    "effects": "过大 dt 会导致模拟不稳定，过小 dt 会增加计算成本。",
    "examples": "dt = 0.002",
    "notes": "粗粒化体系可用更大 dt。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "continuation",
    "title": "Continuation flag",
    "syntax": "continuation = yes | no",
    "description": "是否续跑。",
    "values": "yes, no",
    "when_to_use": "续跑时使用 yes，初始运行使用 no。",
    "effects": "影响初速度生成与约束参考。",
    "examples": "continuation = yes",
    "notes": "与 gen_vel 配合使用。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "tcoupl",
    "title": "Temperature coupling scheme",
    "syntax": "tcoupl = V-rescale",
    "description": "温度耦合方式。",
    "values": "no, v-rescale, nose-hoover, berendsen",
    "when_to_use": "v-rescale 常用；Nose-Hoover 用于严格正则采样；Berendsen 用于初期平衡。",
    "effects": "影响温度涨落与分布。",
    "examples": "tcoupl = V-rescale\nref_t = 300\ntau_t = 0.1",
    "notes": "Berendsen 不适合生产模拟。",
    "refs": [
      "turn0search0",
      "turn0search4"
    ]
  },
  {
    "key": "tc-grps",
    "title": "Temperature coupling groups",
    "syntax": "tc-grps = Protein Water_and_ions",
    "description": "定义温度耦合的分组。",
    "values": "组名列表",
    "when_to_use": "通常至少分为溶质和溶剂。",
    "effects": "不同组可分别维持不同温度。",
    "examples": "tc-grps = Protein Non-Protein",
    "notes": "过度划分会引起伪动力学效应。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "tau_t",
    "title": "Temperature coupling constant",
    "syntax": "tau_t = 0.1",
    "description": "温度耦合时间常数。",
    "values": "典型值 0.1–1.0 ps",
    "when_to_use": "小值 → 强耦合；大值 → 弱耦合。",
    "effects": "过小可能扰动动力学，过大温控效果差。",
    "examples": "tau_t = 0.1",
    "notes": "推荐与体系时间尺度相符。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "ref_t",
    "title": "Reference temperature",
    "syntax": "ref_t = 300",
    "description": "目标温度 (K)。",
    "values": "正浮点数",
    "when_to_use": "根据体系设置（如 300 K）。",
    "effects": "决定温控目标。",
    "examples": "ref_t = 310",
    "notes": "可为不同组设置不同值。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "pcoupl",
    "title": "Pressure coupling method",
    "syntax": "pcoupl = Parrinello-Rahman",
    "description": "压力耦合方式。",
    "values": "no, berendsen, parrinello-rahman, stochastic",
    "when_to_use": "Berendsen: 初期平衡；PR: 生产；stochastic: 替代方案。",
    "effects": "影响体积涨落。",
    "examples": "pcoupl = Parrinello-Rahman",
    "notes": "Berendsen 不产生正确涨落。",
    "refs": [
      "turn0search0",
      "turn0search4"
    ]
  },
  {
    "key": "pcoupltype",
    "title": "Pressure coupling type",
    "syntax": "pcoupltype = semiisotropic",
    "description": "箱体缩放类型。",
    "values": "isotropic, anisotropic, semiisotropic",
    "when_to_use": "膜系: semiisotropic; 晶体: anisotropic; 溶液: isotropic。",
    "effects": "决定各方向缩放方式。",
    "examples": "pcoupltype = semiisotropic",
    "notes": "膜模拟常用 semiisotropic。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "tau_p",
    "title": "Pressure coupling constant",
    "syntax": "tau_p = 5.0",
    "description": "压力耦合时间常数。",
    "values": "典型值 1–5 ps",
    "when_to_use": "平衡可小，生产宜大。",
    "effects": "过小可能不稳，过大响应慢。",
    "examples": "tau_p = 2.0",
    "notes": "需与体系大小匹配。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "ref_p",
    "title": "Reference pressure",
    "syntax": "ref_p = 1.0",
    "description": "目标压力 (bar)。",
    "values": "浮点数或多个值",
    "when_to_use": "常设 1 bar。",
    "effects": "决定压力目标。",
    "examples": "ref_p = 1.0 1.0",
    "notes": "半各向异性需多个值。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "compressibility",
    "title": "Compressibility",
    "syntax": "compressibility = 4.5e-5",
    "description": "体系压缩率。",
    "values": "如水 4.5e-5",
    "when_to_use": "液体体系用默认；其他体系查物性。",
    "effects": "影响体积响应。",
    "examples": "compressibility = 4.5e-5",
    "notes": "错误值导致不合理缩放。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "constraints",
    "title": "Constraints",
    "syntax": "constraints = h-bonds",
    "description": "约束键长。",
    "values": "none, h-bonds, all-bonds, h-angles",
    "when_to_use": "常用 h-bonds 或 all-bonds 以允许更大 dt。",
    "effects": "允许步长加倍。",
    "examples": "constraints = h-bonds",
    "notes": "需配合 LINCS 算法。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "constraint_algorithm",
    "title": "Constraint algorithm",
    "syntax": "constraint_algorithm = lincs",
    "description": "约束算法。",
    "values": "lincs, shake",
    "when_to_use": "常用 lincs。shake 在小体系也可。",
    "effects": "约束收敛。",
    "examples": "constraint_algorithm = lincs",
    "notes": "Lincs 是默认推荐。",
    "refs": [
      "turn0search0"
    ]
  },
  {
    "key": "simulated-tempering",
    "title": "模拟回火",
    "syntax": "simulated-tempering = no | yes",
    "description": "是否启用模拟回火（Simulated Tempering）。这是一种增强采样技术，模拟的温度会在预先定义的几个温度值之间跳跃。",
    "values": "no, yes",
    "when_to_use": "需要增强跨越能量壁垒的采样，但又觉得副本交换（REMD）计算资源消耗太大时。",
    "effects": "体系温度在模拟过程中动态变化，有助于逃离局部能量最小值。",
    "examples": "simulated-tempering = yes",
    "notes": "需与sim-temp-*系列参数（如sim-temp-npoints, sim-temp-temps）配合使用，配置复杂。"
  },
  {
    "key": "exchange",
    "title": "副本交换",
    "syntax": "exchange = no | yes | try",
    "description": "是否启用副本交换（Replica Exchange），也称为并行回火（Parallel Tempering）。",
    "values": "no, yes, try",
    "when_to_use": "进行副本交换分子动力学（REMD）模拟时，这是最主要的增强采样方法之一。",
    "effects": "多个在不同条件下（通常是温度）运行的模拟副本会定期尝试交换配置，从而加速采样。",
    "examples": "exchange = yes",
    "notes": "这通常用于多副本（multi-replica）模拟，需要通过命令行参数‘-multidir’启动。‘try’模式用于测试交换概率。"
  },
  {
    "key": "nstcalcenergy",
    "title": "能量计算频率",
    "syntax": "nstcalcenergy = <integer>",
    "description": "计算非键相互作用能量的步长间隔。邻居列表在此频率下更新。",
    "values": "通常等于nstlist或为其整数倍（如10, 20）",
    "when_to_use": "所有模拟。需与nstlist和nstenergy协调设置。",
    "effects": "影响能量计算的开销和准确性。频率过低可能导致能量计算不准确。",
    "examples": "nstcalcenergy = 10",
    "notes": "必须设置为nstlist的整数倍，以避免额外的邻居列表更新。"
  },
  {
        "key": "nstcomm",
        "title": "质心运动移除频率",
        "syntax": "nstcomm = <integer>",
        "description": "移除体系整体平移和旋转运动的步长间隔。",
        "values": "通常1-100步",
        "when_to_use": "当comm_mode不为‘no’时。",
        "effects": "频率越高，越能有效防止体系漂移，但计算开销略微增加。",
        "examples": "nstcomm = 10",
        "notes": "对于非常小的体系或真空模拟，建议每步移除（nstcomm=1）。"
    },
    {
        "key": "adress",
        "title": "自适应分辨率",
        "syntax": "adress = no | yes",
        "description": "是否启用自适应分辨率模拟（Adaptive Resolution Simulation）。这是一种多尺度方法，将体系划分为原子分辨率和粗粒度分辨率区域。",
        "values": "no, yes",
        "when_to_use": "需要在一个模拟中同时处理高分辨率的感兴趣区域（如蛋白质活性位点）和低分辨率的环境（如大量溶剂）时，以节省计算资源。",
        "effects": "不同区域采用不同的分子描述和相互作用，计算速度更快。",
        "examples": "adress = yes",
        "notes": "这是一个高级功能，需要专门的拓扑文件和力场参数，配置非常复杂。"
    },
    {
        "key": "implicit-solvent",
        "title": "隐式溶剂",
        "syntax": "implicit-solvent = no | yes",
        "description": "是否启用隐式溶剂模型，即用连续介质模型代替显式的水分子。",
        "values": "no, yes",
        "when_to_use": "需要大幅加快模拟速度，且溶剂化效应的精确细节不是研究重点时；或模拟与显式水模型不兼容的体系时。",
        "effects": "避免了显式溶剂分子的计算，速度极大提升，但失去了溶剂结构的 explicit 描述。",
        "examples": "implicit-solvent = yes",
        "notes": "需与‘gb-algorithm’等参数配合使用。GROMACS中对隐式溶剂的支持不如一些专业软件完善。"
    },
    {
        "key": "gb-algorithm",
        "title": "广义Born算法",
        "syntax": "gb-algorithm = Still | HCT | OBC | ...",
        "description": "选择隐式溶剂模型中计算Born半径的算法。",
        "values": "Still, HCT, OBC",
        "when_to_use": "implicit-solvent = yes时。",
        "effects": "不同算法在精度和速度上有所权衡。",
        "examples": "gb-algorithm = OBC",
        "notes": "OBC（Onufriev-Bashford-Case）模型是较为常用和推荐的一个。"
    },
    {
        "key": "electric-field-x",
        "title": "X方向外电场",
        "syntax": "electric-field-x = <real> (V/nm)",
        "description": "在模拟盒子的X方向上施加一个恒定的外部静电场。",
        "values": "实数，例如 0.0, 0.1, 0.5",
        "when_to_use": "模拟外电场对分子行为的影响，如蛋白质的电极化、分子取向、离子输运等。",
        "effects": "带电粒子会受到额外的力，从而影响其运动和体系的介电性质。",
        "examples": "electric-field-x = 0.2",
        "notes": "场强单位是V/nm。正值和负值代表方向。可以同时在Y、Z方向施加电场（electric-field-y, electric-field-z）。"
    },
    {
        "key": "cos-acceleration",
        "title": "COS加速",
        "syntax": "cos-acceleration = <real> (nm/ps²)",
        "description": "施加一个恒定的加速度，用于模拟在离心机中的沉降或创建浓度梯度。",
        "values": "实数",
        "when_to_use": "模拟沉降、超速离心或需要产生密度梯度时。",
        "effects": "所有粒子受到一个与质量成正比的额外力，类似于重力场。",
        "examples": "cos-acceleration = 0.01",
        "notes": "加速度单位是nm/ps²。方向由矢量定义，需与其他cos-参数配合使用。"
    },
    {
        "key": "userint1",
        "title": "用户自定义整型参数1",
        "syntax": "userint1 = <integer>",
        "description": "提供给用户自定义代码使用的整型参数占位符。",
        "values": "任意整数",
        "when_to_use": "当用户自己修改了GROMACS源代码并需要从.mdp文件传递整数参数时。",
        "effects": "对标准模拟无任何影响。其含义由用户自定义代码决定。",
        "examples": "userint1 = 42",
        "notes": "共有userint1至userint4四个整型参数可用。"
    },
    {
        "key": "userreal1",
        "title": "用户自定义实型参数1",
        "syntax": "userreal1 = <real>",
        "description": "提供给用户自定义代码使用的实型参数占位符。",
        "values": "任意实数",
        "when_to_use": "当用户自己修改了GROMACS源代码并需要从.mdp文件传递实数参数时。",
        "effects": "对标准模拟无任何影响。其含义由用户自定义代码决定。",
        "examples": "userreal1 = 3.14",
        "notes": "共有userreal1至userreal4四个实型参数可用。"
    },
    {
        "key": "checkpoint",
        "title": "检查点",
        "syntax": "checkpoint = yes | no",
        "description": "是否写入检查点文件(.cpt)。检查点文件包含了重启模拟所需的所有状态信息。",
        "values": "yes, no",
        "when_to_use": "所有长时间运行的模拟。强烈建议启用，以便从中断处恢复模拟。",
        "effects": "定期生成.cpt文件，占用少量磁盘空间，但提供了模拟的容错能力。",
        "examples": "checkpoint = yes",
        "notes": "应与‘cpt-options’和‘nstcheckpoint’参数配合使用。"
    },
    {
        "key": "nstcheckpoint",
        "title": "检查点输出频率",
        "syntax": "nstcheckpoint = <integer>",
        "description": "写入检查点文件的步长间隔。",
        "values": "通常1000-15000步（例如15-30分钟计算时间）",
        "when_to_use": "checkpoint = yes时。",
        "effects": "决定了在模拟崩溃时最多会丢失多少计算量。频率越高，丢失的计算越少，但I/O开销略微增加。",
        "examples": "nstcheckpoint = 9000 # 对于dt=0.002ps，即每18ps保存一次",
        "notes": "根据模拟总时间和计算资源合理设置。在超算队列时间限制内至少保存一次。"
    },
    {
        "key": "cpt-options",
        "title": "检查点选项",
        "syntax": "cpt-options = -1 (all) | 0 (no) | 1 (append) | ... (bitmask)",
        "description": "控制检查点文件中包含哪些内容。",
        "values": "位掩码或预定义值：-1（保存所有），0（不保存），1（以追加模式打开输出文件）",
        "when_to_use": "需要精细控制检查点文件大小时，例如排除速度信息。",
        "effects": "影响.cpt文件的大小和重启行为的某些方面。",
        "examples": "cpt-options = -1",
        "notes": "除非有特殊需求，否则使用-1（保存所有）是最安全的选择。"
    },
    {
        "key": "dhdl-print-energy",
        "title": "自由能能量输出",
        "syntax": "dhdl-print-energy = no | yes | total | potential | kinetic",
        "description": "控制自由能计算中在dhdl.xvg文件里输出哪些能量项。",
        "values": "no, yes, total, potential, kinetic",
        "when_to_use": "free_energy = yes时，需要详细监控λ变化过程中的能量分解时。",
        "effects": "使dhdl.xvg文件包含更丰富的能量信息，便于深入分析。",
        "examples": "dhdl-print-energy = total",
        "notes": "会增加输出文件的大小。"
    },
    {
        "key": "dssp",
        "title": "DSSP二级结构分析",
        "syntax": "dssp = no | yes",
        "description": "是否在模拟过程中实时运行DSSP算法计算蛋白质的二级结构。",
        "values": "no, yes",
        "when_to_use": "需要监控模拟过程中蛋白质二级结构（α-螺旋、β-折叠等）的动态变化时。",
        "effects": "会在能量文件(.edr)中记录每个残基的二级结构类型，方便后续分析。",
        "examples": "dssp = yes",
        "notes": "会增加额外的计算开销。需要GROMACS在编译时链接了DSSP库。"
    },
    {
        "key": "sc-power",
        "title": "软核势强度",
        "syntax": "sc-power = <real>",
        "description": "自由能计算中软核势（Soft-Core Potential）的幂指数。用于避免在λ接近0或1时原子完全消失或出现带来的数值不稳定。",
        "values": "通常1.0",
        "when_to_use": "free_energy = yes，且‘sc-alpha’不为0时。",
        "effects": "与sc-alpha共同控制软核势的形状，影响自由能计算的收敛性。",
        "examples": "sc-power = 1.0",
        "notes": "除非有特殊理由，否则使用默认值。"
    },
    {
        "key": "sc-sigma",
        "title": "软核势σ",
        "syntax": "sc-sigma = <real> (nm)",
        "description": "软核势中用于Lennard-Jones相互作用的宽度参数。",
        "values": "通常0.3 (nm)",
        "when_to_use": "free_energy = yes，且使用软核势时。",
        "effects": "影响软核势的作用范围。",
        "examples": "sc-sigma = 0.3",
        "notes": "对于标准原子，0.3是一个较好的值。对于大的原子团，可能需要增加。"
    },
   {
        "key": "constraint_algorithm",
        "title": "Constraint algorithm",
        "syntax": "constraint_algorithm = lincs",
        "description": "约束算法。",
        "values": "lincs, shake",
        "when_to_use": "常用 lincs。shake 在小体系也可。",
        "effects": "约束收敛。",
        "examples": "constraint_algorithm = lincs",
        "notes": "Lincs 是默认推荐。",
        "refs": [
        "turn0search0"
        ]
    },
   {
        "key": "structure_centering",
        "title": "结构居中操作",
        "syntax": "gmx trjconv -f input.gro -s input.tpr -o output.gro -center -pbc mol",
        "description": "分子动力学模拟前处理的重要步骤，确保分子位于模拟盒子的中心位置，避免因分子靠近盒子边缘而导致周期性边界条件处理错误。",
        "values": "无固定值，需通过命令行参数指定",
        "when_to_use": "在能量最小化或平衡模拟之前，对初始结构进行处理；处理轨迹文件时确保分子完整地位于模拟盒子内。",
        "effects": "使分子或特定分子组位于盒子中心，确保周期性边界条件正确应用，提高模拟稳定性。",
        "examples": "gmx trjconv -f input.gro -s input.tpr -o centered.gro -center -pbc mol\n# 选择要居中的组（如Protein），然后选择要输出的组（如System）",
        "notes": "1. 对于PDB文件，推荐使用editconf进行居中操作；2. 对于轨迹文件处理，必须提供TPR文件以保持拓扑一致性；3. 使用gmx trjconv -center时需要两次分组选择：第一次选择要居中的组，第二次选择要输出的组；4. 结合-pbc参数可以同时处理周期性边界条件问题。"
}
]

# 在这里结束GromacsUI类

if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = GromacsUI()
    window.show()
    sys.exit(app.exec_())
