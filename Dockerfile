# YiDesk — IT 桌面运维工单系统（命名含义见 README）：后端 + 已构建前端一体镜像
# 构建前端：cd frontend && npm install && npm run build
# 构建：docker build -t itops-helpdesk .
# 运行：见 docker-compose.yml
FROM python:3.12-slim

WORKDIR /opt/itops-helpdesk

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY backend backend
COPY frontend/dist frontend/dist
COPY config.example.yaml config.example.yaml

ENV ITOPS_CONFIG=/opt/itops-helpdesk/config.yaml
ENV TZ=Asia/Shanghai
EXPOSE 8300

# 务必单 worker：渠道长连接与定时任务都在进程内
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300", "--app-dir", "backend"]
