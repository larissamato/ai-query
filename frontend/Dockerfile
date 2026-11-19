FROM node:24-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

FROM dependencies AS test
CMD ["npm", "test"]

FROM dependencies AS build
ARG VITE_LANGFUSE_URL
ARG VITE_LANGFUSE_PROJECT_ID
RUN npm run build

FROM nginx:alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
