import { Controller, Logger } from '@nestjs/common';
import { EventPattern, Payload } from '@nestjs/microservices';
import { FFmpegService } from './ffmpeg/ffmpeg.service';

interface TranscodePayload {
  streamKey: string;
  filename: string;
}

@Controller()
export class AppController {
  private readonly logger = new Logger(AppController.name);

  constructor(private readonly ffmpegService: FFmpegService) {}

  @EventPattern('video.transcode')
  async handleVideoTranscode(@Payload() message: any) {
    this.logger.log(`Received transcoding job: ${JSON.stringify(message)}`);

    // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access
    const payload: TranscodePayload = message.value ? message.value : message;

    await this.ffmpegService.processVideo(payload);
  }
}
