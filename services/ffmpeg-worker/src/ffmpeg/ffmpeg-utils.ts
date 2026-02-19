import { Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';
import { Readable } from 'stream';
import { pipeline } from 'stream/promises';

export interface VodTranscodePayload {
  videoId: string;
  ownerId: string;
  sessionId: string;
  storagePath: string;
  sizeBytes: number;
  originalFilename: string;
  bucket?: string;
  ts: number;
}

export class FfmpegUtils {
  private static readonly logger = new Logger(FfmpegUtils.name);

  /**
   * Download a file from MinIO via local mount or S3 API.
   */
  static async downloadFromStorage(
    config: ConfigService,
    bucket: string,
    storagePath: string,
    localPath: string,
  ): Promise<void> {
    const minioPath = config.get<string>('MINIO_DATA_DIR') || '/minio_data';
    const directPath = path.join(minioPath, bucket, storagePath);

    if (fs.existsSync(directPath) && fs.lstatSync(directPath).isFile()) {
      fs.copyFileSync(directPath, localPath);
      this.logger.log(`Downloaded via direct mount: ${storagePath}`);
      return;
    }

    this.logger.log(
      `File not found at ${directPath} (FS). Attempting S3 download...`,
    );

    try {
      let minioEndpoint =
        config.get<string>('MINIO_ENDPOINT') || 'http://minio:9000';

      if (!minioEndpoint.startsWith('http')) {
        const port = config.get<string>('MINIO_PORT') || '9000';
        minioEndpoint = `http://${minioEndpoint}:${port}`;
      }

      const accessKeyId =
        config.get<string>('MINIO_ACCESS_KEY') ||
        config.get<string>('MINIO_ROOT_USER') ||
        'minioadmin';
      const secretAccessKey =
        config.get<string>('MINIO_SECRET_KEY') ||
        config.get<string>('MINIO_ROOT_PASSWORD') ||
        'minioadmin';

      const s3Client = new S3Client({
        endpoint: minioEndpoint,
        region: 'us-east-1',
        forcePathStyle: true,
        credentials: {
          accessKeyId,
          secretAccessKey,
        },
      });

      const command = new GetObjectCommand({
        Bucket: bucket,
        Key: storagePath,
      });

      const response = await s3Client.send(command);

      if (response.Body instanceof Readable) {
        await pipeline(response.Body, fs.createWriteStream(localPath));
        this.logger.log(`Downloaded via S3 API: ${storagePath}`);
      } else {
        throw new Error('S3 response body is not a readable stream');
      }
    } catch (err) {
      const error = err as Error;
      throw new Error(`Failed to download from S3: ${error.message}`);
    }
  }

  /**
   * Run FFmpeg command.
   */
  static async runFFmpeg(
    config: ConfigService,
    args: string[],
    serviceName: string,
    onHeartbeat?: () => Promise<void> | void,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const ffmpegPath = config.get<string>('FFMPEG_PATH') || 'ffmpeg';
      const proc = spawn(ffmpegPath, args);

      // Periodic heartbeat to signal liveness to Kafka broker
      let heartbeatInterval: NodeJS.Timeout | null = null;
      if (onHeartbeat) {
        heartbeatInterval = setInterval(() => {
          Promise.resolve(onHeartbeat()).catch((err) => {
            this.logger.warn(
              `[${serviceName}] Heartbeat failed during FFmpeg run: ${err}`,
            );
          });
        }, 30000);
      }

      proc.on('close', (code) => {
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        if (code === 0) resolve();
        else
          reject(new Error(`${serviceName} FFmpeg exited with code ${code}`));
      });

      proc.on('error', (err) => {
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        reject(err);
      });
    });
  }

  /**
   * Get video duration using ffprobe.
   */
  static getVideoDuration(
    config: ConfigService,
  ): (input: string) => Promise<number> {
    return (input: string) =>
      new Promise((resolve) => {
        const ffmpegPath = config.get<string>('FFMPEG_PATH') || 'ffmpeg';
        const ffprobePath = ffmpegPath.replace('ffmpeg', 'ffprobe');

        const proc = spawn(ffprobePath, [
          '-v',
          'error',
          '-show_entries',
          'format=duration',
          '-of',
          'default=noprint_wrappers=1:nokey=1',
          input,
        ]);
        let output = '';

        proc.stdout.on('data', (data: Buffer) => {
          output += data.toString();
        });

        proc.on('close', (code) => {
          if (code === 0) {
            const duration = parseFloat(output.trim());
            resolve(isNaN(duration) ? 0 : duration);
          } else {
            resolve(0);
          }
        });

        proc.on('error', () => resolve(0));
      });
  }

  /**
   * Clean up directory.
   */
  static cleanupDir(dir: string, serviceName: string) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      this.logger.warn(`[${serviceName}] Failed to clean up ${dir}`);
    }
  }
}
