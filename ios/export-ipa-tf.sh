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

# build 55：TestFlight 包不带本机的服务器地址和设备密钥（别人装了靠扫码配对连自己的电脑）。
# 归档时把 PivisHealth/LocalConfig.swift 临时换成空白的 LocalConfig.swift.example，不管成功失败都换回来（trap）；
# 开发包（export-ipa.sh）、模拟器照旧用本机的那份。
LC=PivisHealth/LocalConfig.swift
LC_BAK="$B/LocalConfig.swift.dev-backup"
HAD_LC=0
restore_lc() {
  if [ "$HAD_LC" = 1 ] && [ -f "$LC_BAK" ]; then
    mv -f "$LC_BAK" "$LC" && touch "$LC"      # touch：下次开发构建一定重新编译它
  elif [ "$HAD_LC" = 0 ]; then
    rm -f "$LC"
  fi
}
if [ -f "$LC" ]; then cp -p "$LC" "$LC_BAK"; HAD_LC=1; fi
trap restore_lc EXIT
trap 'exit 130' INT TERM
cp LocalConfig.swift.example "$LC"
for k in serverHost installHost appKey; do
  grep -Eq "static let $k *= *\"\"" "$LC" || { echo "LocalConfig.swift.example 里的 $k 不是空的，不出 TestFlight 包"; exit 1; }
done

echo "==> 归档（Release / generic iOS，空白 LocalConfig）"
xcodebuild -project PivisHealth.xcodeproj -scheme PivisHealth \
  -configuration Release -destination 'generic/platform=iOS' \
  archive -archivePath "$B/PivisHealth-tf.xcarchive" -allowProvisioningUpdates

# 兜底：归档出来的 App 里不能有本机的设备密钥 / 服务器地址（15 字节以内的短串可能被编进指令里，查不到也不算保证）
APPBIN="$B/PivisHealth-tf.xcarchive/Products/Applications/PivisHealth.app/PivisHealth"
if [ "$HAD_LC" = 1 ] && [ -f "$APPBIN" ]; then
  for k in appKey serverHost installHost; do
    v=$(sed -n "s/.*static let $k *= *\"\(.*\)\".*/\1/p" "$LC_BAK")
    if [ -n "$v" ] && grep -aqF "$v" "$APPBIN"; then echo "归档里还有本机的 $k，不上传"; exit 1; fi
  done
fi

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
