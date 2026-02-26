#!/bin/bash
# PaddleOCR MCP Server 安装脚本
# 用于快速安装和配置PaddleOCR MCP到AICMDEngine

set -e  # 遇到错误立即退出

echo "=========================================="
echo "PaddleOCR MCP Server 安装脚本"
echo "版本: v1.0"
echo "日期: 2026-02-20"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="/Users/kehongwei/workspace/AICMDEngine"
MCP_DIR="${PROJECT_ROOT}/external_mcp"
PYTHON_BIN="/Users/kehongwei/.pyenv/versions/3.12.11/bin/python"

# 检查Python
echo -e "${YELLOW}[1/6] 检查Python环境...${NC}"
if [ ! -f "$PYTHON_BIN" ]; then
    echo -e "${RED}错误: Python未找到: $PYTHON_BIN${NC}"
    echo "请修改脚本中的PYTHON_BIN变量指向正确的Python路径"
    exit 1
fi
echo -e "${GREEN}✓ Python找到: $PYTHON_BIN${NC}"
echo ""

# 创建MCP目录
echo -e "${YELLOW}[2/6] 创建external_mcp目录...${NC}"
mkdir -p "${MCP_DIR}"
echo -e "${GREEN}✓ 目录创建完成: ${MCP_DIR}${NC}"
echo ""

# 克隆PaddleOCR仓库
echo -e "${YELLOW}[3/6] 克隆PaddleOCR仓库（使用Gitee镜像）...${NC}"
if [ -d "${MCP_DIR}/PaddleOCR" ]; then
    echo -e "${YELLOW}PaddleOCR已存在，跳过克隆${NC}"
else
    # 使用Gitee镜像（国内更快）
    git clone https://gitee.com/PaddlePaddle/PaddleOCR.git "${MCP_DIR}/PaddleOCR"
    if [ $? -ne 0 ]; then
        echo -e "${YELLOW}Gitee镜像失败，尝试GitHub...${NC}"
        git clone https://github.com/PaddlePaddle/PaddleOCR.git "${MCP_DIR}/PaddleOCR"
    fi
    echo -e "${GREEN}✓ PaddleOCR克隆完成${NC}"
fi
echo ""

# 安装PaddleOCR MCP Server
echo -e "${YELLOW}[4/6] 安装PaddleOCR MCP Server...${NC}"
cd "${MCP_DIR}/PaddleOCR"

# 安装MCP Server模块
echo "安装MCP Server模块..."
"$PYTHON_BIN" -m pip install -e mcp_server --quiet

# 安装PaddleOCR及依赖
echo "安装PaddleOCR及依赖..."
"$PYTHON_BIN" -m pip install paddleocr[doc-parser] opencv-python-headless --quiet

echo -e "${GREEN}✓ PaddleOCR安装完成${NC}"
echo ""

# 验证安装
echo -e "${YELLOW}[5/6] 验证安装...${NC}"
"$PYTHON_BIN" -c "from paddleocr import PaddleOCR; print('PaddleOCR导入成功')"
echo -e "${GREEN}✓ PaddleOCR验证通过${NC}"
echo ""

# 生成配置示例
echo -e "${YELLOW}[6/6] 生成配置文件...${NC}"

ENV_FILE="${PROJECT_ROOT}/.env"
BACKUP_FILE="${PROJECT_ROOT}/.env.backup.$(date +%Y%m%d_%H%M%S)"

# 备份现有.env文件
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓ 已备份现有.env文件到: $BACKUP_FILE${NC}"
fi

# 检查是否已配置paddleocr
if grep -q '"paddleocr"' "$ENV_FILE" 2>/dev/null; then
    echo -e "${YELLOW}PaddleOCR配置已存在于.env文件中${NC}"
    echo "如需重新配置，请手动编辑: $ENV_FILE"
else
    echo ""
    echo -e "${GREEN}请将以下配置添加到 $ENV_FILE 文件的 EXTERNAL_MCPS 字段中:${NC}"
    echo ""
    cat << 'EOF'
  "paddleocr": {
    "command": "/Users/kehongwei/.pyenv/versions/3.12.11/bin/python",
    "args": ["-m", "paddleocr_mcp", "--pipeline", "OCR", "--ppocr_source", "local"],
    "transport": "stdio",
    "timeout": 120,
    "env": {
      "PYTHONPATH": "/Users/kehongwei/workspace/AICMDEngine/external_mcp/PaddleOCR"
    }
  }
EOF
    echo ""
    echo -e "${YELLOW}提示: 可以运行以下命令自动添加到.env:${NC}"
    echo "  ./scripts/update_env_with_paddleocr.sh"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}安装完成！${NC}"
echo "=========================================="
echo ""
echo "下一步操作:"
echo "1. 编辑 .env 文件，添加paddleocr配置"
echo "2. 重启AICMDEngine服务:"
echo "   cd $PROJECT_ROOT"
echo "   pkill -f 'uvicorn src.main:app'"
echo "   python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"
echo "3. 验证MCP注册:"
echo "   curl http://localhost:8000/api/mcp/health"
echo ""
echo "详细文档: $PROJECT_ROOT/docs/PADDELEOCR_MCP_INTEGRATION.md"
echo ""
