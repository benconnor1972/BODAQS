FROM node:20-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci
# Source is mounted at runtime — not copied here

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
