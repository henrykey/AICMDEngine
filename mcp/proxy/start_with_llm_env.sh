#!/bin/bash
# MCP Proxy启动脚本 - 从MongoDB读取LLM配置并注入环境变量

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 默认MongoDB连接配置
MONGO_HOST=${MONGO_HOST:-"localhost"}
MONGO_PORT=${MONGO_PORT:-"27017"}
MONGO_DB=${MONGO_DB:-"aicmdengine"}
MONGO_COLLECTION=${MONGO_COLLECTION:-"llm_providers"}

echo "→ 从MongoDB读取LLM配置..."
echo "  MongoDB: $MONGO_HOST:$MONGO_PORT/$MONGO_DB.$MONGO_COLLECTION"

# 使用mongosh查询当前选中的LLM provider
LLM_CONFIG=$(mongosh --quiet \
  --host "$MONGO_HOST" \
  --port "$MONGO_PORT" \
  "$MONGO_DB" \
  --eval "db.$MONGO_COLLECTION.findOne({is_current: true})" 2>/dev/null || echo "")

if [ -z "$LLM_CONFIG" ]; then
  echo "⚠️  警告: 无法从MongoDB读取LLM配置，将使用默认环境变量"
  # 尝试从系统环境变量读取
  if [ -f "../servers/PDF2MD/.env" ]; then
    echo "→ 从PDF2MD/.env加载配置..."
    set -a
    source ../servers/PDF2MD/.env
    set +a
  fi
else
  echo "✓ 从MongoDB读取到LLM配置"

  # 解析LLM配置并设置环境变量
  # 提取provider type
  PROVIDER_TYPE=$(echo "$LLM_CONFIG" | grep -o '"type"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
  echo "  Provider: $PROVIDER_TYPE"

  # 根据provider类型设置相应的环境变量
  case "$PROVIDER_TYPE" in
    "qwen")
      export VLM_MODEL_PROVIDER="qwen"
      export QWEN_API_KEY=$(echo "$LLM_CONFIG" | grep -o '"api_key_ref"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      export QWEN_BASE_URL=$(echo "$LLM_CONFIG" | grep -o '"base_url"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      export QWEN_MODEL_NAME=$(echo "$LLM_CONFIG" | grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      ;;
    "openai"|"gpt-4o")
      export VLM_MODEL_PROVIDER="gpt-4o"
      export OPENAI_API_KEY=$(echo "$LLM_CONFIG" | grep -o '"api_key_ref"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      export OPENAI_BASE_URL=$(echo "$LLM_CONFIG" | grep -o '"base_url"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      export OPENAI_MODEL_NAME=$(echo "$LLM_CONFIG" | grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      ;;
    "zhipu"|"glm-4v")
      export VLM_MODEL_PROVIDER="glm-4v"
      export ZHIPU_API_KEY=$(echo "$LLM_CONFIG" | grep -o '"api_key_ref"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      export ZHIPU_BASE_URL=$(echo "$LLM_CONFIG" | grep -o '"base_url"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      export ZHIPU_MODEL_NAME=$(echo "$LLM_CONFIG" | grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
      ;;
    *)
      echo "⚠️  未知的provider类型: $PROVIDER_TYPE"
      ;;
  esac

  echo "✓ LLM环境变量已设置"
fi

# 启动proxy
echo ""
echo "→ 启动MCP Proxy..."
exec python -m src
