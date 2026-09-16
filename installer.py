"""
GoldenVestPet Installer v109
- Double-click → auto-install to exe_dir/GoldenVestPet/ → auto-launch
- Embeds the entire onedir dist as datas via PyInstaller
- User gets a single Setup.exe, no zip/7z needed
"""
import sys, os, subprocess, shutil, time

def resource_path(name):
    """PyInstaller bundled resource path"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist', name)

def main():
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    target = os.path.join(exe_dir, "GoldenVestPet")
    src = resource_path("GoldenVestPet")

    print("=" * 46)
    print("  GoldenVestPet Installer")
    print("=" * 46)
    print(f"\n  Install to: {target}")

    if not os.path.exists(src):
        print(f"\n  Error: Install data not found ({src})")
        input("  Press Enter to exit...")
        return 1

    if os.path.exists(target):
        print("  Existing installation found, updating...")

    print("\n  Installing files, please wait...\n")
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
                print(f"  Installed {count} files...")

    print(f"\n  ✓ Installed {count} files to: {target}")

    # Launch pet
    pet = os.path.join(target, "GoldenVestPet.exe")
    if os.path.exists(pet):
        print("  Launching GoldenVestPet...")
        subprocess.Popen([pet], cwd=target, close_fds=True)
        print("  ✓ Launched!")
    else:
        print(f"  Error: Pet exe not found at {pet}")
        return 1

    time.sleep(1)
    return 0

if __name__ == '__main__':
    sys.exit(main())
