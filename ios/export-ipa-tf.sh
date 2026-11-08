#!/bin/bash
# P-Health 传 TestFlight（App Store 分发签名，直接上传到 App Store Connect）
# 前置：
#   1. Xcode 已登录 Apple 开发者账号且会话有效；Signing.xcconfig 里填好团队 ID
#   2. App Store Connect 里已经建好这个 App（套装 ID com.pivis.health）
#   3. 每次上传 build 号都要比上次大（工程里的 CURRENT_PROJECT_VERSION）
# 上传后 App Store Connect 处理 10–30 分钟，TestFlight 里的内部测试员会自动收到更新。
set -e
cd "$(dirname "$0")"
# 项目在 iCloud 同步的「文稿」里时签名会被扩展属性卡住：用 PIVIS_BUILD_DIR 指到同步区以外
B="${PIVIS_BUILD_DIR:-build}"
mkdir -p "$B"

TEAM_ID=$(sed -n 's/^DEVELOPMENT_TEAM *= *//p' Signing.xcconfig 2>/dev/null | tr -d ' ')
[ -n "$TEAM_ID" ] || { echo "Signing.xcconfig 里没有 DEVELOPMENT_TEAM（从 Signing.xcconfig.example 复制）"; exit 1; }

echo "==> 归档（Release / generic iOS）"
xcodebuild -project PivisHealth.xcodeproj -scheme PivisHealth \
  -configuration Release -destination 'generic/platform=iOS' \
  archive -archivePath "$B/PivisHealth-tf.xcarchive" -allowProvisioningUpdates

cat > "$B/export-tf.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>upload</string>
  <key>signingStyle</key><string>automatic</string>
  <key>teamID</key><string>$TEAM_ID</string>
  <key>uploadSymbols</key><true/>
  <key>manageAppVersionAndBuildNumber</key><false/>
  <key>testFlightInternalTestingOnly</key><true/>
</dict>
</plist>
PLIST

echo "==> 签名并上传到 App Store Connect"
rm -rf "$B/ipa-tf"
xcodebuild -exportArchive -archivePath "$B/PivisHealth-tf.xcarchive" \
  -exportPath "$B/ipa-tf" -exportOptionsPlist "$B/export-tf.plist" \
  -allowProvisioningUpdates

echo "==> 已上传：build $(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:CFBundleVersion' "$B/PivisHealth-tf.xcarchive/Info.plist")"
