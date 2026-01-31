import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
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
    ]),
  ],
  controllers: [AppController],
  providers: [FFmpegService],
})
export class AppModule {}
