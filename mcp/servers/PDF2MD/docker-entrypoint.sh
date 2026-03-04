#!/bin/bash
# PDF2MD Docker Entrypoint
# 设置 PYTHONPATH 使相对导入正常工作

# 将 /app 的父目录添加到 PYTHONPATH
# 这样 PDF2MD 就可以作为包被导入
export PYTHONPATH=/app:$PYTHONPATH

# 执行传入的命令
exec "$@"
