#!/bin/zsh

set_proxy() {
  local proxy_host=$http_proxy
  local proxy_port=$https_proxy

  # Set the Git proxy configuration
  git config --global http.proxy $http_proxy
  git config --global https.proxy $http_proxy

  echo "Git proxy set to $http_proxy"
}

unset_proxy() {
  # Unset the Git proxy configuration
  git config --global --unset http.proxy
  git config --global --unset https.proxy

  echo "Git proxy unset"
}

# Check the subcommand and execute the corresponding function
case "$1" in
  set)
    if [[ $# -ne 3 ]]; then
      echo "Usage: $0 set <proxy_host> <proxy_port>"
      exit 1
    fi
    set_proxy "$2" "$3"
    ;;
  unset)
    unset_proxy
    ;;
  *)
    echo "Usage: $0 <set|unset>"
    exit 1
    ;;
esac