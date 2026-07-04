#!/bin/bash
# 版本检查脚本
# 检查项目中各安全工具的当前版本和可用更新

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 工具版本配置 (格式: "工具名:当前版本")
TOOLS=(
  "nmap:7.94+dfsg1-1"
  "nuclei:2.9.5"
  "testssl.sh:3.2"
  "hydra:9.5"
  "sqlmap:1.8.2"
  "nikto:2.5.0"
  "gobuster:3.5.0"
  "ffuf:2.0.0"
  "redis-tools:5:0.14"
  "masscan:1.3.2"
  "fping:5.0"
)

echo "=========================================="
echo "  工具版本检查"
echo "=========================================="
echo ""

# 收集当前版本信息
echo "检查容器内当前版本..."
echo ""

CURRENT_VERSIONS=()
for tool in "${TOOLS[@]}"; do
  tool_name="${tool%%:*}"
  
  # 尝试从不同容器获取版本
  case $tool_name in
    "nmap"|"hydra"|"redis-tools"|"masscan"|"fping")
      version=$(docker-compose exec -T security-tools dpkg -l 2>/dev/null | grep "ii  $tool_name " | awk '{print $3}' | head -1)
      version=${version:-"未安装"}
      ;;
    "nuclei")
      version=$(docker-compose exec -T security-tools nuclei -version 2>/dev/null | grep -o "v[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1)
      version=${version:-"未安装"}
      ;;
    "testssl.sh")
      version=$([ -f /testssl/testssl.sh ] && echo "3.2" || echo "未安装")
      ;;
    "sqlmap")
      version=$(docker-compose exec -T web-tools sqlmap --version 2>&1 | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1)
      version=${version:-"未安装"}
      ;;
    "nikto")
      version=$(docker-compose exec -T web-tools nikto -Version 2>&1 | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1)
      version=${version:-"未安装"}
      ;;
    "gobuster")
      version=$(docker-compose exec -T web-tools gobuster version 2>&1 | grep -o "v[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1)
      version=${version:-"未安装"}
      ;;
    "ffuf")
      version=$(docker-compose exec -T web-tools ffuf -V 2>&1 | grep -o "[0-9]\+\.[0-9]\+\.[0-9]\+" | head -1)
      version=${version:-"未安装"}
      ;;
    *)
      version="未知"
      ;;
  esac
  
  CURRENT_VERSIONS+=("$tool_name:$version")
done

# 显示当前版本
echo -e "${GREEN}当前版本:${NC}"
for item in "${CURRENT_VERSIONS[@]}"; do
  name="${item%%:*}"
  ver="${item##*:}"
  printf "  %-15s %s\n" "$name" "$ver"
done

echo ""
echo "=========================================="
echo "  版本配置检查"
echo "=========================================="
echo ""

# 检查 Dockerfile 中的版本配置
DOCKERFILES=(
  "mcp-servers/security-tools/Dockerfile"
  "mcp-servers/fast-scanner/Dockerfile"
  "mcp-servers/web-tools/Dockerfile"
  "mcp-servers/db-tools/Dockerfile"
  "mcp-servers/network-tools/Dockerfile"
  "mcp-servers/windows-tools/Dockerfile"
)

echo "Dockerfile 中的版本配置:"
for df in "${DOCKERFILES[@]}"; do
  if [ -f "$df" ]; then
    echo ""
    echo "📄 $df:"
    grep -E "apt-get install|git clone" "$df" | head -5
  fi
done

echo ""
echo "=========================================="
echo "  更新建议"
echo "=========================================="
echo ""
echo "1. 定期（建议每月）运行此脚本检查更新"
echo "2. 更新 Dockerfile 中的版本号"
echo "3. 重新构建镜像: docker-compose build <service>"
echo "4. 测试新版本: ./tools/test_all_35_tools.py"
echo "5. 提交并合并"

# 创建更新建议文件
cat > tools/update_suggestions.md << 'EOF'
# 工具更新建议

## 定期检查
建议每月运行一次版本检查脚本，确保工具版本是最新的安全版本。

## 更新流程
1. 运行 `./tools/check_versions.sh` 检查当前版本
2. 访问各工具官网查看最新版本
3. 更新 `Dockerfile` 中的版本号
4. 本地测试: `docker-compose build <service>`
5. 运行测试: `./tools/test_all_35_tools.py`
6. 提交 PR 并合并

## 当前工具列表
| 工具 | 当前版本 | 用途 |
|------|----------|------|
| nmap | 7.94+dfsg1-1 | 端口扫描 |
| nuclei | 2.9.5 | 漏洞扫描 |
| testssl.sh | 3.2 | SSL/TLS 检测 |
| hydra | 9.5 | 弱口令检测 |
| sqlmap | 1.8.2 | SQL 注入检测 |
| nikto | 2.5.0 | Web 漏洞扫描 |
| gobuster | 3.5.0 | 目录爆破 |
| ffuf | 2.0.0 | Web 模糊测试 |
| redis-tools | 5:0.14 | Redis 工具 |
| masscan | 1.3.2 | 高速端口扫描 |
| fping | 5.0 | 存活检测 |

## 安全建议
- 定期更新以获取最新的漏洞库
- 测试新版本确保兼容性
- 保留旧版本以便回滚
EOF

echo "更新建议已保存到: tools/update_suggestions.md"
