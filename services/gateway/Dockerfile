FROM node:20-alpine
WORKDIR /srv
COPY package.json .
RUN npm install --omit=dev
COPY src src
CMD ["node", "src/index.js"]
