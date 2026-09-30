# Montserrat - шрифт artline.ua. На сайті його підвантажує сам магазин, а в
# прев'ю студії й на публічних лендінгах (/p/...) - ні, тож оператор бачив би
# Segoe/Arial з іншими переносами рядків. Беремо файли з Debian (fonts-montserrat,
# OFL 1.1) і роздаємо з /fonts/. Складання падає, якщо якоїсь ваги немає:
# тихе відкочування на Arial зробило б прев'ю неправдивим непомітно.
FROM debian:bookworm-slim AS fonts
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-montserrat \
 && mkdir -p /fonts \
 && for weight in Regular Medium SemiBold Bold ExtraBold Black; do \
      src=$(find /usr/share/fonts -type f \( -name "Montserrat-$weight.otf" -o -name "Montserrat-$weight.ttf" \) | sort | head -n 1); \
      if [ -z "$src" ]; then echo "Montserrat-$weight not found in fonts-montserrat" >&2; exit 1; fi; \
      cp "$src" "/fonts/Montserrat-$weight.${src##*.}"; \
    done \
 && ls -la /fonts

FROM nginx:1.27-alpine
COPY index.html /usr/share/nginx/html/index.html
COPY app.js /usr/share/nginx/html/app.js
COPY styles.css /usr/share/nginx/html/styles.css
COPY favicon-32.png /usr/share/nginx/html/favicon-32.png
COPY icon-512.png /usr/share/nginx/html/icon-512.png
COPY apple-touch-icon.png /usr/share/nginx/html/apple-touch-icon.png
COPY --from=fonts /fonts /usr/share/nginx/html/fonts
COPY montserrat.css /usr/share/nginx/html/fonts/montserrat.css
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
