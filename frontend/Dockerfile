# Serves an already-built SPA.
#
# The build happens outside this image on purpose: Vite bakes VITE_* values in
# at build time, and gcloud's --set-build-env-vars does not reach Dockerfile
# ARGs, so a build inside the image silently produces a bundle pointing at
# localhost. Run `npm run build` first (see infrastructure/deploy-web.sh).
FROM nginx:alpine
COPY dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
