import { Injectable, Logger, Inject, OnModuleInit } from '@nestjs/common';
import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';
import * as microservices from '@nestjs/microservices';
import { Observable, firstValueFrom } from 'rxjs';

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
    this.apiClient.subscribeToResponseOf('video.processed');
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
      const duration = await this.getVideoDuration(inputPath);
      this.logger.log(`Video Duration: ${duration}s`);

      // 2. Generate Thumbnail
      const thumbnailFilename = filename.replace(/\.\w+$/, '.jpg');

      const thumbnailPath = path.join(this.minioPath, thumbnailFilename);

      let thumbnailUploaded = false;
      let thumbnailUrl = '';

      try {
        await this.generateThumbnail(inputPath, thumbnailPath);

        if (fs.existsSync(thumbnailPath)) {
          this.logger.log(
            `Uploading thumbnail to gRPC Storage: ${thumbnailFilename}`,
          );
          const thumbBuffer = fs.readFileSync(thumbnailPath);
          const { url } = await firstValueFrom<{ url: string }>(
            this.storageService.upload({
              filename: thumbnailFilename,
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
        this.logger.warn(
          `Failed to generate/upload thumbnail: ${(err as Error).message}`,
        );
      }

      // 3. Transcode to MP4
      const mp4Filename = filename.replace(/\.flv$/, '.mp4');
      const mp4Path = path.join(this.minioPath, mp4Filename);

      this.logger.log(`Transcoding ${filename} to ${mp4Filename}...`);
      await this.transcodeVideo(inputPath, mp4Path);

      // 4. Upload MP4 via gRPC
      this.logger.log(
        `Uploading MP4 to gRPC Storage bucket '${this.bucket}': ${mp4Filename}`,
      );
      const videoBuffer = fs.readFileSync(mp4Path);
      const { url: videoUrl } = await firstValueFrom<{ url: string }>(
        this.storageService.upload({
          filename: mp4Filename,
          data: videoBuffer,
          bucket: this.bucket,
          mimeType: 'video/mp4',
        }),
      );
      this.logger.log(`Upload complete for ${mp4Filename}: ${videoUrl}`);

      // Clean up MP4
      if (fs.existsSync(mp4Path)) fs.unlinkSync(mp4Path);

      // 5. Emit Result
      const completionPayload = {
        streamKey,
        filename: mp4Filename,
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
    await this.runFFmpeg([
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
    ]);
  }

  private async transcodeVideo(input: string, output: string): Promise<void> {
    await this.runFFmpeg([
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
    ]);
  }

  private async runFFmpeg(args: string[]): Promise<void> {
    return new Promise((resolve, reject) => {
      const ffmpegPath =
        this.configService.get<string>('FFMPEG_PATH') || 'ffmpeg';

      const cleanArgs = args.filter((a) => a !== 'thumbnail');

      const proc = spawn(ffmpegPath, cleanArgs);

      proc.stdout.on('data', (data) => this.logger.debug(`[FFmpeg] ${data}`));
      proc.stderr.on('data', (data) => this.logger.debug(`[FFmpeg] ${data}`));

      proc.on('close', (code) => {
        if (code === 0) resolve();
        else reject(new Error(`FFmpeg exited with code ${code}`));
      });

      proc.on('error', (err) => reject(err));
    });
  }

  private getVideoDuration(input: string): Promise<number> {
    return new Promise((resolve) => {
      const ffmpegPath =
        this.configService.get<string>('FFMPEG_PATH') || 'ffmpeg';
      const ffprobePath = ffmpegPath.replace('ffmpeg', 'ffprobe');

      const args = [
        '-v',
        'error',
        '-show_entries',
        'format=duration',
        '-of',
        'default=noprint_wrappers=1:nokey=1',
        input,
      ];

      const proc = spawn(ffprobePath, args);
      let output = '';

      proc.stdout.on('data', (data: Buffer) => {
        output += data.toString();
      });

      proc.on('close', (code) => {
        if (code === 0) {
          const duration = parseFloat(output.trim());
          resolve(isNaN(duration) ? 0 : duration);
        } else {
          this.logger.warn(`ffprobe exited with code ${code}`);
          resolve(0);
        }
      });

      proc.on('error', (err) => {
        this.logger.warn(`ffprobe error: ${err.message}`);
        resolve(0);
      });
    });
  }
}
