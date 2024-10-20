version=${1:-18}
echo "Installing LLVM version $version"
wget https://apt.llvm.org/llvm.sh -o ~/.local/bin/llvm.sh
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
                    --slave /usr/bin/clang-rename clang-rename /usr/bin/clang-rename-$version \




