"""
GoldenVestPet 安装器 v108
- 双击运行 → 自动解压到exe所在目录/GoldenVestPet/ → 自动启动
- 纯Python zipfile解压，无需7z
- PyInstaller打包时将宠物目录作为datas内嵌
"""
import sys, os, subprocess, shutil, zipfile, time

def resource_path(name):
    """PyInstaller打包后资源路径"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist', name)

def main():
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    target = os.path.join(exe_dir, "GoldenVestPet")
    src = resource_path("GoldenVestPet")

    print("=" * 46)
    print("  金背心宠物 (GoldenVestPet) 安装器")
    print("=" * 46)
    print(f"\n  安装目录: {target}")

    if not os.path.exists(src):
        print(f"\n  错误: 安装数据未找到 ({src})")
        input("  按回车退出...")
        return 1

    if os.path.exists(target):
        # 保留crash.log等用户文件，覆盖其余
        print("  检测到已有安装，覆盖更新中...")

    print("\n  正在安装文件，请稍候...\n")
    count = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dst_root = os.path.join(target, rel) if rel != '.' else target
        os.makedirs(dst_root, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.join(dst_root, f)
            shutil.copy2(s, d)
            count += 1
            if count % 200 == 0:
                print(f"  已安装 {count} 个文件...")

    print(f"\n  ✓ 已安装 {count} 个文件到: {target}")

    # 启动宠物
    pet = os.path.join(target, "GoldenVestPet.exe")
    if os.path.exists(pet):
        print("  正在启动金背心宠物...")
        subprocess.Popen([pet], cwd=target, close_fds=True)
        print("  ✓ 已启动！")
    else:
        print(f"  错误: 未找到 {pet}")
        return 1

    # 自动退出（无input等待）
    time.sleep(1)
    return 0

if __name__ == '__main__':
    sys.exit(main())
