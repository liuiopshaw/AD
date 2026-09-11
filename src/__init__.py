# src/__init__.py
# 此文件的存在使得 src 目录成为一个 Python 包（package）
# 没有此文件，Python 不会将 src 目录识别为可导入的包，
# 从而导致 import src.xxx 的语句失败

# __init__.py 是 Python 包的初始化文件，在包被首次 import 时自动执行

# This file makes the src directory a Python package
# 此行翻译：此文件使得 src 目录成为一个 Python 包

# __all__ 变量定义了当使用 "from src import *" 时会被导入的符号列表
# 当前为空列表，意味着 "from src import *" 不会导入任何内容
# 这是一种保守的做法，鼓励调用方显式导入需要的子模块
__all__ = []

# You can also add other important imports here if needed
# 如果将来需要在导入 src 包时自动加载某些子模块，可以在此处添加 import 语句
# 例如取消下面的注释后，import src 时将自动加载 agents、tasks、tools 模块

# from .agents import *
# from .tasks import *
# from .tools import *
