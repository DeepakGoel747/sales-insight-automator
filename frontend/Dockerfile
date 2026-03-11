# ─────────────────────────────────────────────────────────────
# Frontend — lightweight nginx static server
# ─────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="Sales Insight Automator — Frontend"
LABEL org.opencontainers.image.vendor="Rabbitt AI"
LABEL org.opencontainers.image.version="1.0.0"

# Remove default nginx page
RUN rm -rf /usr/share/nginx/html/*

# Copy SPA
COPY index.html /usr/share/nginx/html/index.html

# nginx config — SPA routing + security headers
RUN cat > /etc/nginx/conf.d/default.conf << 'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src *;" always;

    # Gzip
    gzip on;
    gzip_types text/html text/css application/javascript;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /health {
        access_log off;
        return 200 'ok';
        add_header Content-Type text/plain;
    }
}
EOF

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1
