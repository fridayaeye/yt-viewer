FROM node:18-slim
WORKDIR /app
COPY package.json .
RUN npm install --production
COPY dashboard.js .
EXPOSE 3000
CMD ["node", "dashboard.js"]
