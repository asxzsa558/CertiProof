# CertiProof 云上生产部署

## 推荐形态

首期使用一台 Linux 云服务器和现有 Docker Compose。API、Worker、MCP 工具、PostgreSQL、Redis、OCR、向量与图谱服务仍是独立容器，但不需要拆成多台服务器。只有 Caddy 暴露公网 80/443；前端 3000 和后端 8000 只绑定 `127.0.0.1`，数据库与工具服务不映射宿主机端口。

建议至少 8 核 CPU、16GB 内存、100GB SSD。大量扫描 PDF 或同时运行深度检测时应提高到 16 核、32GB；模型缓存和业务文件使用独立数据盘更稳妥。

## 启动

1. 将域名 A/AAAA 记录指向云服务器。
2. 在 `.env` 设置强随机 `POSTGRES_PASSWORD`、`SECRET_KEY`、真实 `CERTIPROOF_DOMAIN` 和对应的 `CORS_ORIGINS`。
3. 云安全组仅向用户来源开放 80/443；SSH 管理端口只向运维来源开放。
4. 启动并检查：

```bash
docker-compose --profile production up -d --build
docker-compose ps
docker-compose logs --tail=100 edge migrate backend
curl -fsS "https://${CERTIPROOF_DOMAIN}/health"
```

不要向公网开放 3000、8000、5432、6379、9000 或 8010-8017。

## 多 VPC 检测

同一部署可以检测多个互通 VPC。扫描容器经 Docker bridge 出站，目标看到的来源通常是云服务器的私网 IP。上线前逐个 VPC 验证：

- 云服务器路由表能到达目标网段，目标网段有返回路由。
- 对等连接、云企业网或 VPN 已转发对应 CIDR，且 CIDR 不与 `172.23.0.0/16` 容器网段冲突。
- 双向安全组、网络 ACL、主机防火墙允许云服务器私网 IP 发起授权检测。
- DNS、ICMP、TCP 和 UDP 按工具需要放行；22 端口“扫描可见”不等于 SSH 登录和命令执行一定可用。
- 将扫描源私网 IP 加入目标白名单，并在项目中保留资产授权范围。

若未来存在不互通 VPC，再增加分布式扫描 Agent；当前版本不需要为此提前拆分控制平面。

## 备份与恢复演练

```bash
./scripts/backup-production.sh
```

脚本保存 PostgreSQL 自包含 dump、上传材料压缩包和 SHA-256。OCR 与向量模型缓存可重新下载，不进入业务备份。备份必须复制到异机或对象存储，并定期在隔离环境执行 `pg_restore` 与材料解压演练。

升级前先备份，再执行：

```bash
git pull --ff-only
docker-compose --profile production up -d --build
```

生产日志应由云日志服务采集，磁盘和 Docker 日志应设置告警；TLS 到期、数据库备份、Worker 队列积压和 `/api/v1/diagnostics` 健康状态需要持续监控。
