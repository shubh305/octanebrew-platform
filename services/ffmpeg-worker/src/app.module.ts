import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { join } from 'path';
import { ClientsModule, Transport } from '@nestjs/microservices';
import { AppController } from './app.controller';

import { FFmpegService } from './ffmpeg/ffmpeg.service';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
    }),
    ClientsModule.registerAsync([
      {
        name: 'API_SERVICE',
        imports: [ConfigModule],
        useFactory: (configService: ConfigService) => ({
          transport: Transport.KAFKA,
          options: {
            client: {
              brokers: [
                configService.get(
                  'KAFKA_BROKERS',
                  'broker.octanebrew.dev:8084',
                ),
              ],
              sasl: configService.get('KAFKA_SASL_USER')
                ? {
                    mechanism: 'plain',
                    username: configService.get<string>('KAFKA_SASL_USER')!,
                    password: configService.get<string>('KAFKA_SASL_PASS')!,
                  }
                : undefined,
              connectionTimeout: 10000,
              requestTimeout: 30000,
            },
            consumer: {
              groupId: 'worker-producer',
            },
          },
        }),
        inject: [ConfigService],
      },
      {
        name: 'STORAGE_SERVICE',
        imports: [ConfigModule],
        useFactory: (configService: ConfigService) => ({
          transport: Transport.GRPC,
          options: {
            package: 'storage',
            protoPath: join(__dirname, 'storage.proto'),
            url: configService.get<string>(
              'STORAGE_SERVICE_URL',
              'storage-service:50051',
            ),
            loader: {
              keepCase: true,
            },
            maxSendMessageLength: 1024 * 1024 * 1024,
            maxReceiveMessageLength: 1024 * 1024 * 1024,
          },
        }),
        inject: [ConfigService],
      },
    ]),
  ],
  controllers: [AppController],
  providers: [FFmpegService],
})
export class AppModule {}
