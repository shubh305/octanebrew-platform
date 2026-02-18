import { NestFactory } from '@nestjs/core';
import { MicroserviceOptions, Transport } from '@nestjs/microservices';
import { AppModule } from './app.module';

async function bootstrap() {
  const isSaslEnabled = !!process.env.KAFKA_SASL_USER;

  const app = await NestFactory.createMicroservice<MicroserviceOptions>(
    AppModule,
    {
      transport: Transport.KAFKA,
      options: {
        client: {
          brokers: [process.env.KAFKA_BROKERS || 'kafka:9092'],
          connectionTimeout: 10000,
          requestTimeout: 30000,
          sasl: isSaslEnabled
            ? {
                mechanism: 'plain',
                username: process.env.KAFKA_SASL_USER!,
                password: process.env.KAFKA_SASL_PASS!,
              }
            : undefined,
        },
        consumer: {
          groupId: 'ffmpeg-worker-consumer',
          maxPollInterval: 300000,
          sessionTimeout: 60000,
        },
      },
    },
  );
  await app.listen();
}
void bootstrap();
