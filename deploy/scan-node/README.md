# CertiProof 远端扫描节点

远端节点部署在目标 VPC 内，主动通过 HTTPS 连接 CertiProof 控制平面。节点不开放管理端口，不运行数据库、前端、LLM、OCR 或向量模型，只运行任务领取器和安全工具容器。

## 在线部署

1. 在控制平面的“扫描节点”页创建节点，配置绑定项目或负责网段，复制一次性注册令牌。
2. 在目标 VPC 的 Linux 主机安装 Docker Engine 与 Docker Compose plugin，确保它能访问控制平面 443 端口和被测资产。
3. 解压在线节点包；包内 `.env.example` 已固定发布版本。由目标 VPC Linux 主机的操作者执行下列命令，这台主机负责下载和启动节点镜像：

```bash
cp .env.example .env
CONTROL_PLANE_URL=https://certiproof.example.com \
ENROLL_TOKEN=<控制平面一次性令牌> \
NODE_LOCAL_SECRET=$(openssl rand -hex 32) \
./start-node.sh
docker compose -f docker-compose.remote-node.yml ps
```

私有 GHCR 需先执行 `docker login ghcr.io`。也可以把前三个变量写入 `.env` 后只执行 `./start-node.sh`。

注册成功后令牌立即失效，长期节点凭证仅保存在 Docker 卷 `node_identity` 中。后续启动不再需要 `ENROLL_TOKEN`，可从 `.env` 删除该值。

## 离线部署

在一台能访问镜像仓库、且与目标服务器 CPU 架构相同的机器执行：

```bash
CERTIPROOF_VERSION=<version> ./scripts/package-remote-node.sh offline
```

将生成的离线包复制到目标主机，解压后运行 `./start-node.sh`。脚本会先加载包内 `images.tar`，目标主机无需访问镜像仓库；它仍需通过 HTTPS 访问 CertiProof 控制平面。

## 安全边界

- 控制平面只派发内置 `NETWORK_CAPABILITIES` 中的结构化任务，节点不接受任意 Shell 命令。
- 目标必须命中绑定项目或 CIDR；节点收到任务后会再次校验。
- 节点令牌只存 SHA-256 哈希于控制平面，数据库中的任务参数使用加密信封保存。
- 生产环境必须使用可信 HTTPS 证书。`ALLOW_INSECURE_CONTROL_PLANE=true` 仅用于本机隔离验收。
- SSH 私钥不会从控制平面复制到节点。确需使用时，将密钥只读挂载到节点包的 `keys/`，参数路径使用 `/app/uploads/<文件名>`；优先使用短期专用账号或密码凭证。
- 配置命中但节点离线时任务明确失败，不会回退到其他网络位置执行。

## 更新与注销

更新 `.env` 中不可变版本后执行 `./start-node.sh`。节点被删除或轮换凭证后，旧凭证立即不可用。重新注册需在控制平面生成新令牌，并执行：

```bash
docker compose -f docker-compose.remote-node.yml down -v
./start-node.sh
```
