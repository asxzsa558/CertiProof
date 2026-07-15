# CertiProof

面向被测企业的等保合规自查平台。系统以五阶段流程组织文档合规检查、自动化技术检测、整改闭环、复测验证和 HTML 报告。

## 主要能力

- 五阶段自查：差距分析、现场测评、整改加固、复测验证、生成报告
- 文档合规：批量文件/文件夹/ZIP/RAR/7z 上传，原生解析、OCR/视觉补充、混合归类、向量检索、Apache AGE 图谱和 LLM 判证
- 技术检测：端口、漏洞、SSL/TLS、Web、弱口令、数据库、SNMP、Windows/AD/SMB 和 SSH 基线
- 资产治理：多项目资产矩阵、暴露面拓扑、资产与端口变化检测
- 闭环治理：Finding、证据、整改工单、复测比较和 HTML 报告
- 组织治理：多组织、成员、角色和细粒度权限

完整产品、流程、模块和数据流设计见 [产品设计文档](docs/certiproof-product-design.html)。

## 容器组成

- React 前端
- FastAPI API 与持久化 Worker
- PostgreSQL 15 + pgvector + Apache AGE
- Redis
- MCP Gateway 与 8 个安全工具服务
- RapidOCR/PaddleOCR-VL 文档识别服务
- FastEmbed + ONNX Runtime 多语言向量服务

## 全新部署

### 前置要求

- Docker Engine 20.10+ 或 Docker Desktop/Colima
- Docker Compose v2
- 建议至少 8GB 可用内存和 20GB 磁盘空间
- 首次构建及首次加载 OCR/向量模型时需要访问软件源和模型源

### 1. 获取代码

```bash
git clone https://github.com/asxzsa558/CertiProof.git
cd CertiProof
```

### 2. 创建环境配置

```bash
cp .env.example .env
```

至少修改以下两项，不能继续使用模板值：

```env
POSTGRES_PASSWORD=替换为强数据库密码
SECRET_KEY=替换为至少32位的随机字符串
```

生成 `SECRET_KEY` 的一种方式：

```bash
openssl rand -hex 32
```

`OPENAI_API_KEY` 可以留空。系统启动后可在“系统设置 → 模型配置”中配置实际使用的 LLM；未配置可用判证模型时，文档检查会明确返回“无法判定”，不会误判为通过。

### 3. 构建并启动

```bash
docker compose up -d --build
```

数据库迁移、pgvector/Apache AGE 初始化和标准图谱装载由 `migrate` 容器自动完成，不需要手工执行 Alembic。

### 4. 检查状态

```bash
docker compose ps
docker compose logs --tail=100 migrate backend worker
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3000/health
```

访问地址：

- Web：<http://127.0.0.1:3000>
- API：<http://127.0.0.1:8000>
- Swagger：<http://127.0.0.1:8000/docs>

## 首次模型加载

- 多语言向量模型默认使用 `intfloat/multilingual-e5-large`，首次文档分析时下载到 Docker 卷 `embedding_models`。
- RapidOCR/PaddleOCR-VL 模型按需加载并缓存到 `ocr_models`。
- 模型不提交到 GitHub，删除对应 Docker 卷后会在下次使用时重新下载。
- CPU 环境可以运行；GPU 仅作为可选加速。低配置机器处理深度模式、大型 DOCX、扫描 PDF 或大量图片时耗时会明显增加。

## 常用运维命令

```bash
# 查看服务
docker compose ps

# 查看后台分析与扫描日志
docker compose logs -f worker ocr-server embedding-server

# 重启应用服务
docker compose restart backend worker frontend

# 停止服务但保留数据
docker compose down

# 更新代码并重建
git pull
docker compose up -d --build
```

业务数据存储在 `postgres_data`、`redis_data`、`uploads_data`、`ocr_models` 和 `embedding_models` Docker 卷中。不要使用 `docker compose down -v`，除非明确需要删除全部业务数据和模型缓存。

## 本地验证

```bash
# 后端测试
docker run --rm -v "$PWD":/workspace -w /workspace \
  -e PYTHONPATH=/workspace/backend certiproof-backend pytest -q

# 前端构建
cd frontend && npm ci && npm run build
```

## 目录结构

```text
backend/                 FastAPI、Worker、迁移、业务服务
frontend/                React 管理界面
mcp-servers/             Gateway、安全工具、OCR 与向量服务
docker/postgres/         PostgreSQL + pgvector + Apache AGE 镜像
reference/compliance/    版本化文档检查标准库
tests/                   自动化回归测试
docs/                    离线产品设计文档
.opencode/plans/         现行架构记忆
```

## 当前状态

项目仍处于 MVP 演进阶段。生产部署前应进一步配置 TLS、备份、日志留存、模型服务容量、漏洞扫描授权边界和外部访问控制。
