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
   * Run FFmpeg command with progress logging and heartbeat.
   */
  static async runFFmpeg(
    config: ConfigService,
    args: string[],
    serviceName: string,
    onHeartbeat?: () => Promise<void> | void,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const ffmpegPath = config.get<string>('FFMPEG_PATH') || 'ffmpeg';

      const isUnix = process.platform !== 'win32';
      const finalCommand = isUnix ? 'nice' : ffmpegPath;
      const finalArgs = isUnix ? ['-n', '15', ffmpegPath, ...args] : args;

      const proc = spawn(finalCommand, finalArgs);

      let heartbeatInterval: NodeJS.Timeout | null = null;
      if (onHeartbeat) {
        heartbeatInterval = setInterval(() => {
          Promise.resolve(onHeartbeat()).catch((err) => {
            this.logger.warn(
              `[${serviceName}] Heartbeat failed during FFmpeg run: ${err}`,
            );
          });
        }, 15000);
      }

      let lastLogTime = Date.now();
      let accumulatedOutput = '';

      proc.stderr.on('data', (data: Buffer) => {
        accumulatedOutput += data.toString();
        if (accumulatedOutput.length > 5000) {
          accumulatedOutput = accumulatedOutput.substring(
            accumulatedOutput.length - 2000,
          );
        }

        if (Date.now() - lastLogTime > 30000) {
          const match = accumulatedOutput.match(
            /frame=\s*(\d+).*fps=\s*([\d.]+).*time=([\d:.]+)/,
          );
          if (match) {
            this.logger.log(
              `[${serviceName}] Progress: Frame=${match[1]}, FPS=${match[2]}, Time=${match[3]}`,
            );
            lastLogTime = Date.now();
            accumulatedOutput = '';
          }
        }
      });

      proc.on('close', (code) => {
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        if (code === 0) resolve();
        else {
          const errorDetail = accumulatedOutput.substring(
            accumulatedOutput.length - 500,
          );
          reject(
            new Error(
              `${serviceName} FFmpeg exited with code ${code}. Detail: ${errorDetail}`,
            ),
          );
        }
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
      if (fs.existsSync(dir)) {
        fs.rmSync(dir, { recursive: true, force: true });
      }
    } catch {
      this.logger.warn(`[${serviceName}] Failed to clean up ${dir}`);
    }
  }

  /**
   * Delete the original source recording from the local MinIO mount.
   */
  static deleteFromStorage(
    config: ConfigService,
    bucket: string,
    storagePath: string,
    serviceName: string,
  ): void {
    const minioPath = config.get<string>('MINIO_DATA_DIR') || '/minio_data';
    const directPath = path.join(minioPath, bucket, storagePath);

    try {
      if (fs.existsSync(directPath)) {
        fs.unlinkSync(directPath);
        this.logger.log(
          `[${serviceName}] Deleted source recording: ${storagePath}`,
        );
      } else {
        this.logger.warn(
          `[${serviceName}] Source not found on mount, skipping delete: ${directPath}`,
        );
      }
    } catch (err) {
      this.logger.warn(
        `[${serviceName}] Failed to delete source recording: ${(err as Error).message}`,
      );
    }
  }

  /**
   * Dedicated single-pass encoder for a single resolution
   */
  static async transcodeSingleResolution(
    config: ConfigService,
    input: string,
    hlsDir: string,
    resolution: '720p' | '1080p',
    crf: number,
    preset = 'fast',
    onHeartbeat?: () => Promise<void> | void,
    serviceName = 'FFMPEG-SEQ',
  ): Promise<void> {
    const hlsTime = config.get<string>('HLS_SEGMENT_TIME') || '4';

    const playlist = path.join(hlsDir, 'playlist.m3u8');
    const seg = path.join(hlsDir, 'seg_%03d.ts');

    const scaleFilter =
      resolution === '720p'
        ? 'scale=-2:720,format=yuv420p'
        : 'scale=-2:1080,format=yuv420p';
    const bitrate = resolution === '720p' ? '128k' : '192k';

    await this.runFFmpeg(
      config,
      [
        '-y',
        '-i',
        input,
        '-threads',
        '2',
        '-vf',
        scaleFilter,
        '-c:v',
        'libx264',
        '-preset',
        preset,
        '-crf',
        String(crf),
        '-profile:v',
        'main',
        '-color_range',
        '1',
        '-colorspace',
        'bt709',
        '-color_primaries',
        'bt709',
        '-color_trc',
        'bt709',
        '-c:a',
        'aac',
        '-b:a',
        bitrate,
        '-ac',
        '2',
        '-g',
        '60',
        '-keyint_min',
        '60',
        '-sc_threshold',
        '0',
        '-hls_time',
        hlsTime,
        '-hls_playlist_type',
        'vod',
        '-hls_flags',
        'independent_segments',
        '-hls_segment_filename',
        seg,
        playlist,
      ],
      `${serviceName}-${resolution}`,
      onHeartbeat,
    );
  }
}
