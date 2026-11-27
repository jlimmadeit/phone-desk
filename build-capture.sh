#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p build
swiftc -module-cache-path "$PWD/build/swift-cache" capture/main.swift -o build/phone-capture -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PWD/capture/Info.plist"
