#!/bin/bash
# merge_universal.sh — 双架构 .app → Universal2 合并（lipo）【无宠物相关硬编码，通用】
# 用法: bash merge_universal.sh <arm64.app路径> <x86_64.app路径> <输出.app路径>
# 原理: 以 arm64 版 .app 为骨架，遍历所有 Mach-O 二进制（主程序/Qt dylib/插件.so），
#       用 lipo -create 把两架构切片合并成 fat binary；非 Mach-O 资源校验一致性。
#       符号链接（Qt framework 结构）由 find -type f 天然跳过、cp -R 原样保留。
set -euo pipefail

ARM_APP="${1:?用法: merge_universal.sh <arm_app> <x86_app> <out_app>}"
X86_APP="${2:?缺少 x86_64 .app 路径}"
OUT_APP="${3:?缺少输出 .app 路径}"

[ -d "$ARM_APP" ] || { echo "FAIL: 找不到 $ARM_APP"; exit 1; }
[ -d "$X86_APP" ] || { echo "FAIL: 找不到 $X86_APP"; exit 1; }

# 以 arm64 版为骨架（含 Info.plist/icon/资源/符号链接结构）
rm -rf "$OUT_APP"
cp -R "$ARM_APP" "$OUT_APP"

merged=0; skipped=0; warn=0
while IFS= read -r -d '' f; do
  rel="${f#"$ARM_APP"/}"
  xf="$X86_APP/$rel"
  of="$OUT_APP/$rel"
  if [ ! -f "$xf" ]; then
    echo "WARN: 仅arm64存在(保留): $rel"; warn=$((warn+1)); continue
  fi
  case "$(file -b "$f")" in
    *"Mach-O"*)
      arm_arch="$(lipo -archs "$f" 2>/dev/null || echo '?')"
      x86_arch="$(lipo -archs "$xf" 2>/dev/null || echo '?')"
      if [ "$arm_arch" = "$x86_arch" ]; then
        # 两边同架构（罕见）：内容一致则跳过，不一致报警
        if cmp -s "$f" "$xf"; then skipped=$((skipped+1));
        else echo "WARN: 同架构但内容不同: $rel"; warn=$((warn+1)); fi
        continue
      fi
      tmp="$of.universal.$$"
      lipo -create "$f" "$xf" -output "$tmp"
      mv "$tmp" "$of"
      chmod 755 "$of"
      merged=$((merged+1))
      ;;
    *)
      # 非 Mach-O 资源（pyc/png/plist）：两架构构建应完全一致
      if ! cmp -s "$f" "$xf"; then
        echo "WARN: 非Mach-O两架构不一致(保留arm64版): $rel"; warn=$((warn+1))
      fi
      ;;
  esac
done < <(find "$ARM_APP" -type f -print0)

echo "=== 合并结果: Mach-O合并=$merged 同架构跳过=$skipped 警告=$warn ==="

# 验证主可执行文件（Contents/MacOS 下非 dylib 的文件即主程序）
MAIN="$(find "$OUT_APP/Contents/MacOS" -type f ! -name '*.dylib' | head -1)"
[ -n "$MAIN" ] || { echo "FAIL: 找不到主可执行文件"; exit 1; }
ARCHS="$(lipo -archs "$MAIN")"
echo "主程序: $MAIN"
echo "主程序架构: $ARCHS"
echo "$ARCHS" | grep -q "arm64" && echo "$ARCHS" | grep -q "x86_64" \
  || { echo "FAIL: 主程序不是 Universal2"; exit 1; }

# 抽查一个 Qt dylib 也必须是双架构
QTLIB="$(find "$OUT_APP" -name 'libQt5Core*.dylib' -type f | head -1)"
if [ -n "$QTLIB" ]; then
  QARCHS="$(lipo -archs "$QTLIB")"
  echo "Qt5Core架构: $QARCHS"
  echo "$QARCHS" | grep -q "arm64" && echo "$QARCHS" | grep -q "x86_64" \
    || { echo "FAIL: Qt dylib 不是 Universal2"; exit 1; }
fi

echo "OK: Universal2 合并成功"
