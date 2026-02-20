import { Injectable, Logger, Inject, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';
import * as microservices from '@nestjs/microservices';
import { Observable, firstValueFrom } from 'rxjs';
import { FfmpegUtils } from './ffmpeg-utils';

interface StorageServiceProxy {
  upload(data: {
    filename: string;
    data: Uint8Array;
    bucket: string;
    mimeType: string;
  }): Observable<{ url: string }>;
}

@Injectable()
export class FFmpegService implements OnModuleInit {
  private readonly logger = new Logger(FFmpegService.name);
  private readonly minioPath: string;
  private readonly bucket = 'vods';
  private storageService: StorageServiceProxy;

  constructor(
    @Inject('API_SERVICE')
    private readonly apiClient: microservices.ClientKafka,
    @Inject('STORAGE_SERVICE')
    private readonly storageClient: microservices.ClientGrpc,
    private configService: ConfigService,
  ) {
    this.minioPath =
      this.configService.get<string>('MINIO_DATA_DIR') || '/minio_data';
  }

  async onModuleInit() {
    this.storageService =
      this.storageClient.getService<StorageServiceProxy>('StorageService');
    await this.apiClient.connect();
  }

  async processVideo(payload: { streamKey: string; filename: string }) {
    const { streamKey, filename } = payload;
    this.logger.log(`Starting processing for ${streamKey} -> ${filename}`);

    const inputPath = path.join(this.minioPath, 'recordings', filename);

    if (!fs.existsSync(inputPath)) {
      this.logger.error(`Input file not found: ${inputPath}`);
      return;
    }

    try {
      // 1. Get Duration
      const duration = await FfmpegUtils.getVideoDuration(this.configService)(
        inputPath,
      );
      this.logger.log(`Video Duration: ${duration}s`);

      // 2. Generate Thumbnail
      const thumbnailFilename = filename.replace(/\.\w+$/, '.jpg');
      const thumbnailPath = path.join(this.minioPath, thumbnailFilename);

      let thumbnailUploaded = false;
      let thumbnailUrl = '';

      try {
        await this.generateThumbnail(inputPath, thumbnailPath);

        if (fs.existsSync(thumbnailPath)) {
          const s3ThumbnailKey = `thumbnails/${thumbnailFilename}`;
          const thumbBuffer = fs.readFileSync(thumbnailPath);
          const { url } = await firstValueFrom<{ url: string }>(
            this.storageService.upload({
              filename: s3ThumbnailKey,
              data: thumbBuffer,
              bucket: this.bucket,
              mimeType: 'image/jpeg',
            }),
          );
          thumbnailUrl = url;
          thumbnailUploaded = true;
          fs.unlinkSync(thumbnailPath);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        this.logger.warn(
          `Failed to generate/upload thumbnail: ${errorMessage}`,
        );
      }

      // 3. Transcode to MP4
      const mp4Filename = filename.replace(/\.flv$/, '.mp4');
      const mp4Path = path.join(this.minioPath, mp4Filename);

      this.logger.log(`Transcoding ${filename} to ${mp4Filename}...`);
      await this.transcodeVideo(inputPath, mp4Path);

      // 4. Upload MP4
      const s3VideoKey = `videos/${mp4Filename}`;
      const videoBuffer = fs.readFileSync(mp4Path);
      const { url: videoUrl } = await firstValueFrom<{ url: string }>(
        this.storageService.upload({
          filename: s3VideoKey,
          data: videoBuffer,
          bucket: this.bucket,
          mimeType: 'video/mp4',
        }),
      );

      if (fs.existsSync(mp4Path)) fs.unlinkSync(mp4Path);

      // 5. Emit Result
      const completionPayload = {
        streamKey,
        filename: s3VideoKey,
        path: videoUrl,
        thumbnail: thumbnailUploaded ? thumbnailUrl : '',
        duration: duration,
      };

      this.logger.log(`Emitting video.processed event for ${streamKey}`);
      this.apiClient.emit('video.processed', completionPayload);
    } catch (err) {
      const error = err as Error;
      this.logger.error(`Processing failed: ${error.message}`, error.stack);
    }
  }

  private async generateThumbnail(
    input: string,
    output: string,
  ): Promise<void> {
    await FfmpegUtils.runFFmpeg(
      this.configService,
      [
        '-y',
        '-i',
        input,
        '-ss',
        '00:00:01',
        '-frames:v',
        '1',
        '-q:v',
        '2',
        '-update',
        '1',
        output,
      ],
      'FFMPEG',
    );
  }

  private async transcodeVideo(input: string, output: string): Promise<void> {
    await FfmpegUtils.runFFmpeg(
      this.configService,
      [
        '-y',
        '-i',
        input,
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '23',
        '-c:a',
        'aac',
        '-b:a',
        '128k',
        '-movflags',
        '+faststart',
        output,
      ],
      'FFMPEG',
    );
  }
}
