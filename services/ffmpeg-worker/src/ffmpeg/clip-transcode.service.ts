import { Injectable, Logger, Inject } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ClientKafka } from '@nestjs/microservices';
import * as path from 'path';
import * as fs from 'fs';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { FfmpegUtils } from './ffmpeg-utils';

export interface ClipTranscodePayload {
  clipId: string;
  parentVideoId: string;
  rawPath: string;
  crfValue: number;
  ts: number;
}

@Injectable()
export class ClipTranscodeService {
  private readonly logger = new Logger(ClipTranscodeService.name);
  private readonly s3Client: S3Client;

  constructor(
    private readonly configService: ConfigService,
    @Inject('API_SERVICE') private readonly kafkaClient: ClientKafka,
  ) {
    const minioEndpoint =
      this.configService.get<string>('MINIO_ENDPOINT') || 'http://minio:9000';
    const accessKeyId =
      this.configService.get<string>('MINIO_ACCESS_KEY') ||
      this.configService.get<string>('MINIO_ROOT_USER') ||
      'minioadmin';
    const secretAccessKey =
      this.configService.get<string>('MINIO_SECRET_KEY') ||
      this.configService.get<string>('MINIO_ROOT_PASSWORD') ||
      'minioadmin';

    let endpoint = minioEndpoint;
    if (!endpoint.startsWith('http')) {
      const port = this.configService.get<string>('MINIO_PORT') || '9000';
      endpoint = `http://${endpoint}:${port}`;
    }

    this.s3Client = new S3Client({
      endpoint,
      region: 'us-east-1',
      forcePathStyle: true,
      credentials: {
        accessKeyId,
        secretAccessKey,
      },
    });
  }

  async processClipTranscode(
    payload: ClipTranscodePayload,
    onHeartbeat: () => Promise<void> | void,
  ): Promise<void> {
    const { clipId, parentVideoId, rawPath, crfValue } = payload;
    this.logger.log(
      `Starting clip transcode for clip ${clipId} (parent: ${parentVideoId})`,
    );

    const bucket =
      this.configService.get<string>('MINIO_BUCKET') || 'openstream-uploads';
    const tempDir = path.join('/tmp', `clip_${clipId}_${Date.now()}`);
    fs.mkdirSync(tempDir, { recursive: true });

    const localInputPath = path.join(tempDir, 'input.mp4');
    const hlsDir = path.join(tempDir, 'hls');
    const hls720Dir = path.join(hlsDir, '720p');
    const hls1080Dir = path.join(hlsDir, '1080p');

    fs.mkdirSync(hls720Dir, { recursive: true });
    fs.mkdirSync(hls1080Dir, { recursive: true });

    try {
      // 1. Download stream-copy MP4
      await FfmpegUtils.downloadFromStorage(
        this.configService,
        bucket,
        rawPath,
        localInputPath,
      );

      // 2. Transcode to 720p + 1080p HLS
      const crf = crfValue || 23;
      await FfmpegUtils.transcodeDualResolution(
        this.configService,
        localInputPath,
        hls720Dir,
        hls1080Dir,
        crf,
        onHeartbeat,
        'ClipTranscode',
      );

      // 3. Create Master Manifest
      const masterManifest = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        '#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,NAME="1080p"',
        '1080p/playlist.m3u8',
        '#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,NAME="720p"',
        '720p/playlist.m3u8',
      ].join('\n');
      fs.writeFileSync(path.join(hlsDir, 'master.m3u8'), masterManifest);

      // 4. Upload HLS to MinIO
      const s3Prefix = `highlights/${parentVideoId}/hls/clips/${clipId}`;

      const uploadRecursive = async (localDir: string, remoteDir: string) => {
        const items = fs.readdirSync(localDir);
        for (const item of items) {
          const localPath = path.join(localDir, item);
          const remotePath = `${remoteDir}/${item}`;
          if (fs.statSync(localPath).isDirectory()) {
            await uploadRecursive(localPath, remotePath);
          } else {
            const contentType = item.endsWith('.m3u8')
              ? 'application/vnd.apple.mpegurl'
              : 'video/MP2T';

            const fileStream = fs.createReadStream(localPath);
            await this.s3Client.send(
              new PutObjectCommand({
                Bucket: bucket,
                Key: remotePath,
                Body: fileStream,
                ContentType: contentType,
              }),
            );
          }
        }
      };

      await uploadRecursive(hlsDir, s3Prefix);

      // 5. Emit clip.ready
      const hlsManifest = `${s3Prefix}/master.m3u8`;
      this.kafkaClient.emit('clip.ready', {
        clipId,
        hlsManifest,
        ts: Date.now(),
      });

      this.logger.log(
        `Clip transcode successful for ${clipId}, emitted clip.ready`,
      );
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      this.logger.error(`Clip transcode failed for ${clipId}: ${errorMsg}`);

      // 5. Emit clip.failed
      this.kafkaClient.emit('clip.failed', {
        clipId,
        reason: errorMsg,
        ts: Date.now(),
      });
      throw err;
    } finally {
      FfmpegUtils.cleanupDir(tempDir, 'ClipTranscode');
    }
  }
}
