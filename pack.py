# pack.py
import subprocess
import os
import sys


def package_app():
    # 检查PyInstaller是否安装
    try:
        import PyInstaller
    except ImportError:
        print("正在安装PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 确保图标文件存在
    icon_path = "favicon.ico"
    if not os.path.exists(icon_path):
        print(f"错误: 图标文件 {icon_path} 不存在")
        return

    # 打包命令
    cmd = [
        "pyinstaller",
        "--onefile",  # 打包成单个exe
        "--windowed",  # 不显示控制台窗口
        f"--icon={icon_path}",  # 设置图标
        "--name=EasyDanTag",  # 输出文件名
        "main.py"  # 入口文件
    ]

    print("开始打包应用...")
    subprocess.check_call(cmd)
    print("打包完成！输出文件: dist/EasyDanTag.exe")


if __name__ == "__main__":
    package_app()
