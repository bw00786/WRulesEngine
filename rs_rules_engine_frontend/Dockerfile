FROM node:20-alpine as build

WORKDIR /app

COPY package.json package-lock.json* ./

RUN yarn install

COPY . .

RUN yarn run build

FROM nginx:alpine

COPY --from=build /app/build /usr/share/nginx/html

RUN echo 'server { \
    listen 31243; \
    location / { \
        root /usr/share/nginx/html; \
        index index.html index.htm; \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 31243

CMD ["nginx", "-g", "daemon off;"]
