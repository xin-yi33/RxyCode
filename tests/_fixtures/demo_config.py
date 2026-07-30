# demo_config.py — 一份用于「文件操作」测试的本地样例文件
# 故意留一个可修复的小缺陷：PORT 被注释、且少了一个配置项

HOST = "127.0.0.1"
# PORT = 8080   <-- 缺少端口配置
DEBUG = True

def load_config():
    return {
        "host": HOST,
        "debug": DEBUG,
    }
