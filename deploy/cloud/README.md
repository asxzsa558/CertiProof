# CertiProof 云部署包

CPU 与 GPU 包使用同一组 CertiProof 业务镜像。CPU 包调用云端 LLM；GPU 包额外启动官方 vLLM 镜像和 Qwen3-14B，避免复制两套相同的前后端与安全工具镜像。

## 云主机准备

- CPU：Ubuntu 22.04/24.04 x86_64，测试起点 8 vCPU / 32 GB / 200 GB SSD。
- GPU：同一系统，建议 16 vCPU / 64 GB / NVIDIA 48 GB 显存 / 300-500 GB SSD，并安装 NVIDIA 驱动和 `nvidia-container-toolkit`。
- 两者都安装 Docker Engine、Docker Compose plugin，开放 80/443，并配置到被测资产的授权网络路径。
- 私有 GHCR 镜像先执行 `docker login ghcr.io`；公开镜像无需登录。

## 启动

```bash
tar -xzf certiproof-cloud-cpu-<version>.tar.gz   # GPU 主机改用 gpu 包
cd certiproof-cloud-cpu-<version>
cp .env.example .env
# 修改全部 replace-with-*、域名、CORS 和模型配置
# 可用 openssl rand -hex 24 生成数据库密码，openssl rand -hex 32 生成 SECRET_KEY
./scripts/cloud-preflight.sh
./scripts/start-production.sh
```

CPU 包会拉取业务镜像并调用 `.env` 中的云模型。GPU 包会额外拉取 `VLLM_IMAGE`，首次启动下载 `VLLM_MODEL` 到持久卷，时间取决于带宽。发布包不包含大体积镜像层和模型权重；对应版本必须已经由 `Publish cloud images` 工作流发布到 GHCR。

## 验证

```bash
docker compose ps
curl -fsS https://你的域名/health
```

随后登录模型设置页执行“测试模型”，它会验证真实结构化输出，不只检查端口存活。

## 更新与停止

```bash
./scripts/start-production.sh
docker compose --profile production down
```

普通 `down` 保留数据库、上传文件和模型卷；不要在生产环境使用 `down -v`，除非明确永久清空全部数据。
