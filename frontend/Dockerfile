FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_GRAPHQL_URL=/graphql
ENV VITE_GRAPHQL_URL=$VITE_GRAPHQL_URL

ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY

# #1677: the commit this bundle is built from, for the report bubble. Railway passes its own
# RAILWAY_GIT_COMMIT_SHA to a build that declares it; a local build has none and reports "dev".
ARG RAILWAY_GIT_COMMIT_SHA
ENV VITE_BUILD_SHA=$RAILWAY_GIT_COMMIT_SHA

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf.template

EXPOSE 80

CMD ["/bin/sh", "-c", "envsubst '${PORT}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
