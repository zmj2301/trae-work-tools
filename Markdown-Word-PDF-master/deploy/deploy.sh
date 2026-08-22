#!/bin/bash
# Markdown-Word-PDF 部署脚本
# 在 ECS 服务器 (39.107.96.165) 上执行
set -e

APP_NAME="md-converter"
APP_DIR="/opt/${APP_NAME}"
VENV_DIR="${APP_DIR}/venv"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
NGINX_CONF="/etc/nginx/conf.d/${APP_NAME}.conf"

echo "=== 1. 创建项目目录 ==="
mkdir -p ${APP_DIR}
cd ${APP_DIR}

echo "=== 2. 安装系统依赖 ==="
apt-get update
apt-get install -y python3 python3-venv python3-pip libreoffice-core libreoffice-writer nginx curl ca-certificates

echo "=== 3. 创建 Python 虚拟环境 ==="
python3 -m venv ${VENV_DIR}
source ${VENV_DIR}/bin/activate

echo "=== 4. 安装 Python 依赖 ==="
pip install --upgrade pip
pip install -r ${APP_DIR}/requirements.txt || pip install flask python-docx lxml latex2mathml requests markdown-it-py gunicorn xhtml2pdf reportlab playwright

echo "=== 5. 部署项目文件 ==="
# 从 GitHub 拉取（如有）
if [ -d "${APP_DIR}/.git" ]; then
    git -C ${APP_DIR} pull origin main
else
    echo "请将项目文件上传到 ${APP_DIR}/"
    echo "或使用: git clone https://github.com/zmj2301/Markdown-Word-PDF.git ${APP_DIR}"
fi

echo "=== 6. 安装 systemd 服务 ==="
cat > ${SERVICE_FILE} << 'SVCEOF'
[Unit]
Description=Markdown to Word/PDF Converter
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/md-converter
Environment=PATH=/opt/md-converter/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/md-converter/venv/bin/gunicorn app:app --bind 127.0.0.1:10000 --workers 4 --timeout 120 --chdir /opt/md-converter
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable ${APP_NAME}
systemctl restart ${APP_NAME}

echo "=== 7. 配置 nginx ==="
cat > ${NGINX_CONF} << 'NGINXEOF'
server {
    listen 80;
    server_name md.codingzhou.top;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:10000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }

    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        proxy_pass http://127.0.0.1:10000;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }
}
NGINXEOF

# 如果 codingzhou.top 已有 nginx 配置（80/443 端口），需要在现有 server block 中添加 subdomain 配置
# 或者使用 separate server block（注意端口冲突）
echo "⚠️  注意：如果 codingzhou.top 已有 nginx 配置，需要将 md.codingzhou.top 的配置合并到现有文件中"
echo "   或检查 /etc/nginx/nginx.conf 中的 include 规则"

nginx -t && systemctl reload nginx || echo "⚠️  nginx test failed, check for port 80 conflicts"

echo ""
echo "=== 部署完成 ==="
echo "检查服务状态: systemctl status ${APP_NAME}"
echo "查看日志: journalctl -u ${APP_NAME} -f"
echo "测试: curl http://127.0.0.1:10000/"
echo "外网访问: https://md.codingzhou.top"