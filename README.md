# VeriSure - 等保合规智能平台

基于 AI Agent + MCP 架构的实战化等保合规自检平台。

## 核心特性

- **AI 驱动**：自然语言驱动，AI 自动调度安全工具
- **实战验证**：白盒配置 + 黑盒渗透交叉验证，打出"纸上合规"原形
- **双版本支持**：轻量版（黑盒扫描）+ 高级版（白盒+渗透）
- **持续合规**：事件驱动自动重评 + 趋势看板
- **整改闭环**：AI 生成整改方案 → 工单派发 → 一键复测

## 技术栈

### 后端
- **框架**：FastAPI (Python 3.11+)
- **数据库**：PostgreSQL 15 + SQLAlchemy 2.0
- **缓存/队列**：Redis 7
- **认证**：JWT (python-jose)
- **AI/LLM**：OpenAI API

### 前端
- **框架**：React 18
- **UI 组件**：Ant Design 5
- **状态管理**：Zustand
- **构建工具**：Vite 5

### 基础设施
- **容器化**：Docker + Docker Compose
- **数据库迁移**：Alembic

## 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+

### 启动服务

```bash
# 克隆项目
git clone <repository-url>
cd VeriSure

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

服务启动后：
- **后端 API**：http://localhost:8000
- **API 文档**：http://localhost:8000/docs
- **前端界面**：http://localhost:3000

### 数据库初始化

```bash
# 进入后端容器
docker-compose exec backend bash

# 运行数据库迁移
alembic upgrade head

# 退出
exit
```

## 项目结构

```
VeriSure/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── core/           # 核心配置
│   │   ├── models/         # 数据库模型
│   │   ├── schemas/        # Pydantic 模型
│   │   ├── services/       # 业务逻辑
│   │   ├── mcp/            # MCP 客户端
│   │   └── agent/          # AI Agent
│   ├── migrations/         # Alembic 迁移
│   └── tests/              # 测试
├── frontend/               # React 前端
│   ├── src/
│   │   ├── components/     # 组件
│   │   ├── pages/          # 页面
│   │   ├── services/       # API 调用
│   │   └── store/          # 状态管理
│   └── ...
├── mcp-servers/            # MCP Server
├── docker-compose.yml      # Docker 编排
└── README.md
```

## 开发指南

### 后端开发

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 运行开发服务器
uvicorn app.main:app --reload --port 8000
```

### 前端开发

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 运行开发服务器
npm run dev
```

## API 文档

启动后端服务后，访问：
- **Swagger UI**：http://localhost:8000/docs
- **ReDoc**：http://localhost:8000/redoc

## 环境变量

复制 `backend/.env.example` 为 `backend/.env` 并配置：

```env
DATABASE_URL=postgresql+asyncpg://certiproof:certiproof@db:5432/certiproof
REDIS_URL=redis://redis:6379/0
SECRET_KEY=your-secret-key
OPENAI_API_KEY=your-openai-api-key
TASK_EXECUTION_MODE=worker  # docker-compose 默认：API 入库，worker 执行
TASK_WORKER_POLL_SECONDS=3
TASK_LEASE_MINUTES=120
MONITORING_WORKER_BATCH_SIZE=5
```

## 版本

- **当前版本**：0.1.0 (MVP)
- **目标版本**：1.0.0

## 许可证

MIT License
