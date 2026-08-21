FROM nginx:1.27-alpine
COPY index.html /usr/share/nginx/html/index.html
COPY app.js /usr/share/nginx/html/app.js
COPY styles.css /usr/share/nginx/html/styles.css
COPY favicon-32.png /usr/share/nginx/html/favicon-32.png
COPY icon-512.png /usr/share/nginx/html/icon-512.png
COPY apple-touch-icon.png /usr/share/nginx/html/apple-touch-icon.png
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
