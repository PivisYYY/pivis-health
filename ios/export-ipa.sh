#!/bin/bash
# P-Health iOS 一键出包（开发签名，安装到已登记的设备）
# 前置：Xcode 已登录你的 Apple 开发者账号且会话有效；Signing.xcconfig 里填好团队 ID
set -e
cd "$(dirname "$0")"
# 产物目录：默认 build/；项目放在 iCloud 同步的「文稿」里时，签名会被同步加的扩展属性卡住，
# 这时用 PIVIS_BUILD_DIR 指到同步区以外的目录
B="${PIVIS_BUILD_DIR:-build}"
mkdir -p "$B"

echo "==> 归档（Release / generic iOS）"
xcodebuild -project PivisHealth.xcodeproj -scheme PivisHealth \
  -configuration Release -destination 'generic/platform=iOS' \
  archive -archivePath "$B/PivisHealth.xcarchive" -allowProvisioningUpdates

cat > "$B/export.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>development</string>
  <key>destination</key><string>export</string>
  <key>signingStyle</key><string>automatic</string>
  <key>teamID</key><string>__TEAM_ID__</string>
</dict>
</plist>
EOF
TEAM_ID=$(sed -n 's/^DEVELOPMENT_TEAM *= *//p' Signing.xcconfig 2>/dev/null | tr -d ' ')
[ -n "$TEAM_ID" ] || { echo "Signing.xcconfig 里没有 DEVELOPMENT_TEAM（从 Signing.xcconfig.example 复制）"; exit 1; }
sed -i '' "s/__TEAM_ID__/$TEAM_ID/" "$B/export.plist"

echo "==> 导出 ipa"
rm -rf "$B/ipa"
xcodebuild -exportArchive -archivePath "$B/PivisHealth.xcarchive" \
  -exportPath "$B/ipa" -exportOptionsPlist "$B/export.plist" \
  -allowProvisioningUpdates

echo "==> 完成："
ls -lh "$B"/ipa/*.ipa
