import { NestFactory } from '@nestjs/core';
import { MicroserviceOptions, Transport } from '@nestjs/microservices';
import { AppModule } from './app.module';

async function bootstrap() {
  const isSaslEnabled = !!process.env.KAFKA_SASL_USER;

  // PROCESS_LANE controls which topic partition
  const lane = (process.env.PROCESS_LANE || 'all').toLowerCase();
  const baseGroupId =
    process.env.KAFKA_FFMPEG_CONSUMER_GROUP_ID || 'ffmpeg-worker-consumer';

  const groupId =
    lane === 'all'
      ? baseGroupId
      : `${baseGroupId.replace(/-consumer$/, '')}-${lane}`;

  const concurrency = lane === 'fast' ? 2 : lane === 'slow' ? 1 : 3;

  const app = await NestFactory.createMicroservice<MicroserviceOptions>(
    AppModule,
    {
      transport: Transport.KAFKA,
      options: {
        client: {
          brokers: (process.env.KAFKA_BROKERS || 'kafka:9092').split(','),
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
          groupId,
          maxPollInterval: 3600000,
          sessionTimeout: 300000,
          rebalanceTimeout: 3600000,
        },
        subscribe: {
          fromBeginning: false,
        },
        run: {
          concurrency,
          autoCommit: true,
        },
      },
    },
  );

  await app.listen();
}
void bootstrap();
