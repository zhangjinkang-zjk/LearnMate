FROM python:3.11-slim

# 目录结构必须和本地一致：backend/src/main.py → 从 backend/ 父目录启动
WORKDIR /app/backend

# 安装系统依赖（MySQL 客户端库是 aiomysql 需要的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（不改代码时利用 Docker 缓存，不用每次重新 pip install）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再复制代码
COPY . .

# 提前下载嵌入模型（放到构建阶段，避免启动时慢）
# 模型 id 与代码里的默认值保持一致；要换模型改这里 + 跑一次 reembed 脚本。
# 注意：权重有 GB 量级，compose 里给它挂了卷，重建镜像时不会重复下载。
ARG EMBEDDING_MODEL_ID=BAAI/bge-m3
ENV EMBEDDING_MODEL_ID=${EMBEDDING_MODEL_ID}
ENV EMBEDDING_MODEL_DIR=/app/backend/embedding_models
RUN python -c "\
import os; \
from sentence_transformers import SentenceTransformer; \
target = os.path.join(os.environ['EMBEDDING_MODEL_DIR'], os.environ['EMBEDDING_MODEL_ID'].replace('/', '__')); \
os.makedirs(target, exist_ok=True); \
SentenceTransformer(os.environ['EMBEDDING_MODEL_ID']).save(target)"

# 容器内结构：/app/backend/src/main.py
# 所以 PYTHONPATH 需要指向 /app，这样 backend.src.main 才能解析
ENV PYTHONPATH=/app

EXPOSE 2221

CMD ["uvicorn", "backend.src.main:app", "--host", "0.0.0.0", "--port", "2221"]
