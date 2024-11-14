set -e

export DOWNLOAD_URL="https://mirrors.tuna.tsinghua.edu.cn/docker-ce"

curl -fsSL https://get.docker.com/ | sh


sudo groupadd docker             #添加docker用户组
sudo gpasswd -a $USER docker     #将特定用户加入到docker用户组中，$USER为目标用户名
newgrp docker                    #更新用户组
docker ps                        #测试docker命令不加sudo是否可以正常使用


sudo add-apt-repository ppa:graphics-drivers/ppa
sudo apt-get install dkms build-essential

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

sudo nvidia-ctk runtime configure --runtime=docker

sudo systemctl restart docker

sudo docker run --rm --gpus all nvidia/cuda:11.7.1-base-ubuntu20.04 nvidia-smi