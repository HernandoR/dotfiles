#!/usr/bin/env bash

# https://downloads.1password.com/linux/debian/amd64/stable/1password-latest.deb

# use axel if available
if command -v axel &>/dev/null; then
    axel -n 10 -a https://downloads.1password.com/linux/debian/amd64/stable/1password-latest.deb -o /tmp/1password-latest.deb
else
    wget https://downloads.1password.com/linux/debian/amd64/stable/1password-latest.deb -O /tmp/1password-latest.deb
fi

# install the 1password deb package
sudo apt install -f /tmp/1password-latest.deb -y

# remove the 1password deb package
rm /tmp/1password-latest.deb
