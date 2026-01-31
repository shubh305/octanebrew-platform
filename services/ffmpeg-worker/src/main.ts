import { NestFactory } from '@nestjs/core';
import { MicroserviceOptions, Transport } from '@nestjs/microservices';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.createMicroservice<MicroserviceOptions>(
    AppModule,
    {
      transport: Transport.KAFKA,
      options: {
        client: {
          brokers: [process.env.KAFKA_BROKER || 'broker.octanebrew.dev:8084'],
        },
        consumer: {
          groupId: 'ffmpeg-worker-consumer',
        },
      },
    },
  );
  await app.listen();
}
void bootstrap();
