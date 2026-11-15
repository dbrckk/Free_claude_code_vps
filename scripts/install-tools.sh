#!/bin/sh
set -eu

arch=$1
out=$2
temp=$(mktemp -d)
trap 'rm -rf "$temp"' EXIT
mkdir -p "$out"

download() {
    curl -fsSL --retry 3 "$1" -o "$temp/$3"
    echo "$2  $temp/$3" | sha256sum -c -
}

case "$arch" in
    amd64)
        machine=x86_64
        uv_checksum=c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83
        rojo_checksum=00feb4fa0829a1dd72b49df2639da519a352bfe13cadcd83969e2ba2bb5693c4
        godot_arch=x86_64
        godot46_checksum=6bcc59dfd1d670e918c77eae06e82b9dc5699de13d353dc3a4b3b6b307b6dc06
        godot45_checksum=02ec53d1cc7dbb9cc6355393c61b9ab43d1244751a124f10248a4802830788cd
        ;;
    arm64)
        machine=aarch64
        uv_checksum=71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc
        rojo_checksum=7190d4bcfd95b4d6d37d8c0837f4a52acaec096cdf10417918559d26535dcf77
        godot_arch=arm64
        godot46_checksum=6c4bcb78a760f4b3bd958d0ca92496b0d5929540a0d29b0f315087a96226714a
        godot45_checksum=4a2c6bd5066aca9d207c75f540645e29272b129f2cf321d8ba30d922af11b00f
        ;;
    *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
esac

case "${3:-core}" in
    core)
        download "https://github.com/astral-sh/uv/releases/download/0.13.7/uv-$machine-unknown-linux-gnu.tar.gz" "$uv_checksum" uv.tgz
        tar -xzf "$temp/uv.tgz" -C "$out" --strip-components=1 "uv-$machine-unknown-linux-gnu/uv" "uv-$machine-unknown-linux-gnu/uvx"
        download "https://github.com/rojo-rbx/rojo/releases/download/v7.7.1/rojo-7.7.1-linux-$machine.zip" "$rojo_checksum" rojo.zip
        unzip -jo "$temp/rojo.zip" rojo -d "$out"
        if [ "$arch" = amd64 ]; then
            download "https://github.com/luau-lang/luau/releases/download/0.744/luau-ubuntu.zip" 6506f0852c623aaffcb28494aac16c26dc04a269ea0e16cc0aafc8c8ac79f3ec luau.zip
            unzip -jo "$temp/luau.zip" luau luau-compile luau-analyze -d "$out"
        else
            download "https://codeload.github.com/luau-lang/luau/tar.gz/refs/tags/0.744" 08b960d377e1c3d6727c15a5ae9d415f9236efcda3aad05bfd82498ab9c20f6d luau.tgz
            mkdir "$temp/luau"
            tar -xzf "$temp/luau.tgz" -C "$temp/luau" --strip-components=1
            cmake -S "$temp/luau" -B "$temp/build" -DCMAKE_BUILD_TYPE=Release -DLUAU_BUILD_TESTS=OFF
            cmake --build "$temp/build" --parallel 2 --target Luau.Repl.CLI Luau.Compile.CLI Luau.Analyze.CLI
            install -m 0755 "$temp/build/luau" "$temp/build/luau-compile" "$temp/build/luau-analyze" "$out/"
        fi
        chmod 0755 "$out"/uv "$out"/uvx "$out"/rojo "$out"/luau "$out"/luau-compile "$out"/luau-analyze
        ;;
    godot)
        godot() {
            version=$1
            archive="Godot_v$version-stable_linux.$godot_arch"
            download "https://github.com/godotengine/godot/releases/download/$version-stable/$archive.zip" "$2" godot.zip
            unzip -p "$temp/godot.zip" "$archive" > "$out/godot-$version"
            chmod 0755 "$out/godot-$version"
        }
        godot 4.5.1 "$godot45_checksum"
        godot 4.6 "$godot46_checksum"
        ln -s godot-4.6 "$out/godot"
        ;;
    *) exit 1 ;;
esac
