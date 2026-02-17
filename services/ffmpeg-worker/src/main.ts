import { NestFactory } from '@nestjs/core';
import { MicroserviceOptions, Transport } from '@nestjs/microservices';
import { AppModule } from './app.module';

async function bootstrap() {
  const isSaslEnabled = !!process.env.KAFKA_BROKER_USER;

  const app = await NestFactory.createMicroservice<MicroserviceOptions>(
    AppModule,
    {
      transport: Transport.KAFKA,
      options: {
        client: {
          brokers: [process.env.KAFKA_BOOTSTRAP_SERVERS || ''],
          connectionTimeout: 10000,
          requestTimeout: 30000,
          sasl: isSaslEnabled
            ? {
                mechanism: 'plain',
                username: process.env.KAFKA_BROKER_USER!,
                password: process.env.KAFKA_BROKER_PASS!,
              }
            : undefined,
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
