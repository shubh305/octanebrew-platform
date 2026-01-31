FROM node:22-alpine

# Install FFmpeg
RUN apk add --no-cache ffmpeg

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm install

COPY . .

RUN npm run build

CMD ["node", "dist/main"]
