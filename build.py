import os
import shutil
import subprocess
import sys

def build():
    # 切换到脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)

    print("--- 开始打包流程 v2 (修正 apscheduler 遗漏) ---")

    # 1. 清理旧的构建文件
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            print(f"尝试清理旧的 {folder} 文件夹...")
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"无法自动清理 {folder}: {e}")
                print(f"请确保已关闭所有正在运行的程序实例和打开的文件夹，然后手动删除 {folder} 文件夹再重试。")
                return

    # 2. 检查图标文件
    icon_path = os.path.join("icons", "main.ico")
    if not os.path.exists(icon_path):
        print(f"警告: 未找到图标文件 {icon_path}，将不使用图标。")
        icon_cmd = []
    else:
        icon_cmd = ["--icon", icon_path]

    # 3. 准备 PyInstaller 命令 (使用 python -m PyInstaller 确保使用当前环境的库)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir", # 推荐使用目录模式
        "--windowed", # 不显示控制台
        "--name", "微信群聊总结助手",
        *icon_cmd,
        # 显式指定隐藏导入
        "--hidden-import", "apscheduler",
        "--hidden-import", "apscheduler.schedulers.background",
        "--hidden-import", "apscheduler.triggers.cron",
        "--collect-all", "apscheduler",
        "--collect-all", "pytz",
        "--collect-all", "tzlocal",
        "--collect-all", "tzdata",
        # 添加数据文件
        "--add-data", f"V1/config{os.pathsep}V1/config",
        "--add-data", f"icons{os.pathsep}icons",
        # 入口文件
        "V1/main_gui.py"
    ]

    print(f"执行命令: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print("\n--- 打包成功! ---")
        print(f"生成的程序位于: {os.path.join(current_dir, 'dist', '微信群聊总结助手')}")
        print("提示：如果仍然报错，请尝试在命令行输入 'pip install pytz' 确保基础库完整。")
    except subprocess.CalledProcessError as e:
        print(f"\n--- 打包失败! ---")
    except Exception as e:
        print(f"\n--- 打包异常: {e} ---")

if __name__ == "__main__":
    build()
