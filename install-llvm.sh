#!/bin/bash
set -e
# sample usage:
# ./install-llvm.sh 12 all
version=$1
# recommended ./install-llvm.sh 18 all
echo "Installing LLVM version $version"
wget https://apt.llvm.org/llvm.sh -O ~/.local/bin/llvm.sh
chmod +x ~/.local/bin/llvm.sh
sudo ~/.local/bin/llvm.sh $@

sudo update-alternatives --install /usr/bin/clang clang /usr/bin/clang-$version 100 \
                    --slave /usr/bin/clang++ clang++ /usr/bin/clang++-$version \
                    --slave /usr/bin/clang-cpp clang-cpp /usr/bin/clang-cpp-$version \
                    --slave /usr/bin/clangd clangd /usr/bin/clangd-$version \
                    --slave /usr/bin/clang-format clang-format /usr/bin/clang-format-$version \
                    --slave /usr/bin/clang-tidy clang-tidy /usr/bin/clang-tidy-$version \
                    --slave /usr/bin/clang-cl clang-cl /usr/bin/clang-cl-$version \
                    --slave /usr/bin/clang-query clang-query /usr/bin/clang-query-$version \
                    --slave /usr/bin/clang-rename clang-rename /usr/bin/clang-rename-$version
for file in /usr/bin/*-"$version"; do
    if [ -f "$file" ]; then
        base_name=$(basename "$file" -"$version")
        if [ ! -f "/usr/bin/$base_name" ]; then
            sudo update-alternatives --install /usr/bin/"$base_name" "$base_name" /usr/bin/"${base_name}"-"$version" 1
        fi
    fi
done