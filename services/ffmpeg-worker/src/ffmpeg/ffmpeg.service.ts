import { Injectable, Logger, Inject } from '@nestjs/common';
import { ClientKafka } from '@nestjs/microservices';
import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class FFmpegService {
  private readonly logger = new Logger(FFmpegService.name);
  // Shared volume path where Nginx dumps recordings
  private readonly minioPath: string;
  private readonly vodOutputPath: string;

  constructor(
    @Inject('API_SERVICE') private readonly apiClient: ClientKafka,
    private configService: ConfigService,
  ) {
    this.minioPath =
      this.configService.get<string>('OPENSTREAM_VOL_PATH') || '/minio_data';
    this.vodOutputPath = path.join(this.minioPath, 'vods');
    this.ensureDirectory(this.vodOutputPath);
  }

  async onModuleInit() {
    this.apiClient.subscribeToResponseOf('video.processed');
    await this.apiClient.connect();
  }

  private ensureDirectory(dir: string) {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }

  async processVideo(payload: { streamKey: string; filename: string }) {
    const { streamKey, filename } = payload;
    this.logger.log(`Starting processing for ${streamKey} -> ${filename}`);

    const inputPath = path.join(this.minioPath, 'recordings', filename);

    if (!fs.existsSync(inputPath)) {
      this.logger.error(`Input file not found: ${inputPath}`);
      return;
    }

    const timestamp = Date.now();
    const outputFilename = `${streamKey}-${timestamp}.mp4`;
    const outputThumbnail = `${streamKey}-${timestamp}.jpg`;

    const mp4Path = path.join(this.vodOutputPath, outputFilename);
    const thumbPath = path.join(this.vodOutputPath, outputThumbnail);

    try {
      // 1. Convert FLV to MP4
      this.logger.log(`Transcoding ${inputPath} to ${mp4Path}`);
      await this.runFFmpeg([
        '-i',
        inputPath,
        '-c',
        'copy',
        '-movflags',
        '+faststart',
        mp4Path,
      ]);

      // 2. Generate Thumbnail
      this.logger.log(`Generating thumbnail`);
      let thumbnailGenerated = false;
      try {
        await this.runFFmpeg([
          '-i',
          mp4Path,
          '-ss',
          '00:00:05',
          '-vframes',
          '1',
          '-pix_fmt',
          'yuvj420p',
          '-strict',
          'unofficial',
          thumbPath,
        ]);
        thumbnailGenerated = true;
      } catch (thumbErr) {
        this.logger.warn(
          `Thumbnail generation produced a warning or error, but continuing flow: ${(thumbErr as Error).message}`,
        );
      }

      // 3. Emit Result to Backend (Kafka)
      const publicMp4Url = `/vods/${outputFilename}`;
      const publicThumbUrl = thumbnailGenerated
        ? `/vods/${outputThumbnail}`
        : '';

      const completionPayload = {
        streamKey,
        filename: outputFilename,
        path: publicMp4Url,
        thumbnail: publicThumbUrl,
        duration: 0, // TODO: Parse duration
      };

      this.logger.log(`Emitting video.processed event for ${streamKey}`);
      this.apiClient.emit('video.processed', completionPayload);

      // TODO: Cleanup raw recording
      // fs.unlinkSync(inputPath);
    } catch (err) {
      const error = err as Error;
      this.logger.error(`Processing failed: ${error.message}`, error.stack);
    }
  }

  private runFFmpeg(args: string[]): Promise<void> {
    return new Promise((resolve, reject) => {
      const ffmpegPath =
        this.configService.get<string>('FFMPEG_PATH') || 'ffmpeg';
      const proc = spawn(ffmpegPath, args);

      proc.stdout.on('data', (data) => this.logger.debug(`[FFmpeg] ${data}`));
      proc.stderr.on('data', (data) => this.logger.debug(`[FFmpeg] ${data}`));

      proc.on('close', (code) => {
        if (code === 0) resolve();
        else reject(new Error(`FFmpeg exited with code ${code}`));
      });

      proc.on('error', (err) => reject(err));
    });
  }
}
