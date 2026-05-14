# agent/utils/logger.py
import logging
import sys
import os

class LogColor:
    PLAN = "\033[94m"       # 蓝色
    TOOL = "\033[96m"       # 青色
    ANALYZER = "\033[93m"   # 黄色
    ROUTER = "\033[95m"     # 紫色
    SYNTH = "\033[92m"      # 绿色
    RESET = "\033[0m"       # 重置颜色

# 1. 确保日志存储目录存在
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 2. 创建一个全局的 Logger 实例
logger = logging.getLogger("CoachAgent")
logger.setLevel(logging.INFO)

# 3. 拦截重复添加 Handler（防止在 FastAPI 多次实例化时导致日志重复打印）
if not logger.handlers:
    # 处理器 1：输出到终端（带彩色，方便肉眼开发调试）
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 处理器 2：输出到本地文件（不带彩色代码，防止文本污染，方便后续用 grep 查看）
    file_handler = logging.FileHandler(os.path.join(log_dir, "coach_agent.log"), encoding="utf-8")
    
    # 编写一个过滤器，自动洗掉写入文件的彩色转义字符（如 \033[94m），确保日志文件干净可读
    class StrippedColorFormatter(logging.Formatter):
        def format(self, record):
            message = super().format(record)
            # 用正则剔除 ANSI 终端颜色代码
            import re
            return re.sub(r'\033\[\d+m', '', message)

    file_formatter = StrippedColorFormatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
