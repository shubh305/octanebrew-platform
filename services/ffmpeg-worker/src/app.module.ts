import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { join } from 'path';
import { ClientsModule, Transport } from '@nestjs/microservices';
import { AppController } from './app.controller';

import { FFmpegService } from './ffmpeg/ffmpeg.service';
import { VodFastLaneService } from './ffmpeg/vod-fast-lane.service';
import { VodSlowLaneService } from './ffmpeg/vod-slow-lane.service';
import { ComplexityAnalyzerService } from './ffmpeg/complexity-analyzer.service';

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
              maxPollInterval: 300000,
              sessionTimeout: 60000,
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
              'localhost:50051',
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
  providers: [
    FFmpegService,
    VodFastLaneService,
    VodSlowLaneService,
    ComplexityAnalyzerService,
  ],
})
export class AppModule {}
