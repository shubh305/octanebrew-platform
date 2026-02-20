import { Injectable, Logger, Inject, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';
import * as microservices from '@nestjs/microservices';
import { Observable, firstValueFrom } from 'rxjs';
import { ComplexityAnalyzerService } from './complexity-analyzer.service';
import { FfmpegUtils, VodTranscodePayload } from './ffmpeg-utils';

// Sprite helpers

function computeSpriteParams(durationSeconds: number): {
  interval: number;
  cols: number;
  rows: number;
  frameCount: number;
} {
  const interval = durationSeconds < 600 ? 5 : durationSeconds < 3600 ? 10 : 20;
  const frameCount = Math.ceil(durationSeconds / interval);
  const cols = Math.ceil(Math.sqrt(frameCount));
  const rows = Math.ceil(frameCount / cols);
  return { interval, cols, rows, frameCount };
}

function toVttTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = (s % 60).toFixed(3).padStart(6, '0');
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${sec}`;
}

function generateVTT(
  cdnSpriteUrl: string,
  durationSeconds: number,
  params: { interval: number; cols: number; frameCount: number },
): string {
  const { interval, cols, frameCount } = params;
  const W = 160,
    H = 90;
  const lines = ['WEBVTT', ''];

  for (let i = 0; i < frameCount; i++) {
    const start = i * interval;
    const end = Math.min((i + 1) * interval, durationSeconds);
    const x = (i % cols) * W;
    const y = Math.floor(i / cols) * H;

    lines.push(toVttTime(start) + ' --> ' + toVttTime(end));
    lines.push(`${cdnSpriteUrl}#xywh=${x},${y},${W},${H}`);
    lines.push('');
  }
  return lines.join('\n');
}

interface StorageServiceProxy {
  upload(data: {
    filename: string;
    data: Uint8Array;
    bucket: string;
    mimeType: string;
  }): Observable<{ url: string }>;
}

/**
 * VOD Slow Lane Service
 */
@Injectable()
export class VodSlowLaneService implements OnModuleInit {
  private readonly logger = new Logger(VodSlowLaneService.name);
  private readonly workDir: string;
  private readonly bucket = 'openstream-uploads';
  private storageService: StorageServiceProxy;

  constructor(
    @Inject('API_SERVICE')
    private readonly apiClient: microservices.ClientKafka,
    @Inject('STORAGE_SERVICE')
    private readonly storageClient: microservices.ClientGrpc,
    private configService: ConfigService,
    private readonly complexityAnalyzer: ComplexityAnalyzerService,
  ) {
    this.workDir =
      this.configService.get<string>('VOD_WORK_DIR') || '/tmp/vod-work';
  }

  async onModuleInit() {
    this.storageService =
      this.storageClient.getService<StorageServiceProxy>('StorageService');
    await this.apiClient.connect();
  }

  async processSlowLane(
    payload: VodTranscodePayload,
    onHeartbeat?: () => Promise<void> | void,
  ) {
    const { videoId, storagePath, originalFilename } = payload;
    const jobDir = path.join(this.workDir, `${videoId}-slow`);

    this.logger.log(`[SLOW] Starting slow-lane for ${videoId}`);

    try {
      if (!fs.existsSync(jobDir)) {
        fs.mkdirSync(jobDir, { recursive: true });
      }

      // 1. Download source
      const sourceExt = path.extname(originalFilename) || '.mp4';
      const sourcePath = path.join(jobDir, `source${sourceExt}`);
      await FfmpegUtils.downloadFromStorage(
        this.configService,
        payload.bucket || this.bucket,
        storagePath,
        sourcePath,
      );

      // 2. Run complexity analysis
      const complexity = await this.complexityAnalyzer.analyze(sourcePath);
      this.logger.log(
        `[SLOW] Complexity: score=${complexity.score}, CRF=${complexity.crf}`,
      );

      // 3. Transcode 720p + 1080p in a single FFmpeg pass
      const hls720Dir = path.join(jobDir, '720p');
      const hls1080Dir = path.join(jobDir, '1080p');
      fs.mkdirSync(hls720Dir, { recursive: true });
      fs.mkdirSync(hls1080Dir, { recursive: true });
      await this.transcodeBothResolutions(
        sourcePath,
        hls720Dir,
        hls1080Dir,
        complexity.crf,
        onHeartbeat,
      );

      // 5. Upload segments
      await this.uploadHLSDir(videoId, '720p', hls720Dir);
      await this.uploadHLSDir(videoId, '1080p', hls1080Dir);

      // 6. Master playlist
      const masterManifest = this.buildMasterPlaylist();
      const masterKey = `vod/${videoId}/master.m3u8`;
      const { url: masterUrl } = await firstValueFrom<{ url: string }>(
        this.storageService.upload({
          filename: masterKey,
          data: Buffer.from(masterManifest, 'utf-8'),
          bucket: this.bucket,
          mimeType: 'application/vnd.apple.mpegurl',
        }),
      );

      // 7. Emit complete
      const completePayload = {
        videoId,
        crfUsed: complexity.crf,
        complexityScore: complexity.score,
        resolutions: ['480p', '720p', '1080p'],
        hlsManifest: masterUrl,
        ts: Date.now(),
      };

      this.logger.log(`[SLOW] Emitting video.complete for ${videoId}`);
      await firstValueFrom(
        this.apiClient.emit('video.complete', completePayload),
      );

      // Sprite generation
      try {
        this.logger.log(
          `[SLOW][SPRITES] Starting sprite generation for ${videoId}`,
        );

        const durationSeconds = await FfmpegUtils.getVideoDuration(
          this.configService,
        )(sourcePath);

        if (durationSeconds > 0) {
          const params = computeSpriteParams(durationSeconds);
          const { interval, cols, rows, frameCount } = params;
          const spriteLocalPath = path.join(jobDir, 'sprites.jpg');

          // Generate sprite sheet using the local source file
          await FfmpegUtils.runFFmpeg(
            this.configService,
            [
              '-y',
              '-i',
              sourcePath,
              '-vf',
              `fps=1/${interval},scale=160:90,tile=${cols}x${rows}`,
              '-frames:v',
              '1',
              '-q:v',
              '5',
              spriteLocalPath,
            ],
            'SPRITES',
          );

          const cdnSpriteUrl = 'sprites.jpg';

          const vttContent = generateVTT(cdnSpriteUrl, durationSeconds, params);

          // Upload sprite JPG
          const spriteKey = `vod/${videoId}/sprites/sprites.jpg`;
          await firstValueFrom<{ url: string }>(
            this.storageService.upload({
              filename: spriteKey,
              data: fs.readFileSync(spriteLocalPath),
              bucket: this.bucket,
              mimeType: 'image/jpeg',
            }),
          );

          // Upload VTT
          const vttKey = `vod/${videoId}/sprites/thumbnails.vtt`;
          await firstValueFrom<{ url: string }>(
            this.storageService.upload({
              filename: vttKey,
              data: Buffer.from(vttContent, 'utf-8'),
              bucket: this.bucket,
              mimeType: 'text/vtt',
            }),
          );

          this.logger.log(
            `[SLOW][SPRITES] Sprite sheet uploaded for ${videoId} (${frameCount} frames, ${interval}s interval)`,
          );

          // Emit completion
          await firstValueFrom(
            this.apiClient.emit('video.sprites.complete', {
              videoId,
              spritePath: spriteKey,
              vttPath: vttKey,
              frameCount,
              interval,
              cols,
              rows,
              ts: Date.now(),
            }),
          );
        } else {
          this.logger.warn(
            `[SLOW][SPRITES] Duration 0 for ${videoId} — skipping sprite generation`,
          );
          await firstValueFrom(
            this.apiClient.emit('video.sprites.complete', {
              videoId,
              failed: true,
              reason: 'Could not determine video duration',
              ts: Date.now(),
            }),
          );
        }
      } catch (spriteErr) {
        const msg =
          spriteErr instanceof Error ? spriteErr.message : String(spriteErr);
        this.logger.warn(
          `[SLOW][SPRITES] Sprite generation failed for ${videoId}: ${msg}`,
        );
        // Best-effort emit of failure
        try {
          await firstValueFrom(
            this.apiClient.emit('video.sprites.complete', {
              videoId,
              failed: true,
              reason: msg,
              ts: Date.now(),
            }),
          );
        } catch {
          // ignore
        }
      }

      // Delete the original source recording from the local MinIO mount
      // TODO : Re-enable this after testing
      // FfmpegUtils.deleteFromStorage(
      //   this.configService,
      //   payload.bucket || this.bucket,
      //   storagePath,
      //   'SLOW',
      // );

      FfmpegUtils.cleanupDir(jobDir, 'SLOW');
    } catch (err) {
      const error = err as Error;
      this.logger.error(
        `[SLOW] Processing failed for ${videoId}: ${error.message}`,
        error.stack,
      );
    }
  }

  /**
   * Single-pass dual-resolution encode using -filter_complex split.
   */
  private async transcodeBothResolutions(
    input: string,
    hls720Dir: string,
    hls1080Dir: string,
    crf: number,
    onHeartbeat?: () => Promise<void> | void,
  ): Promise<void> {
    await FfmpegUtils.transcodeDualResolution(
      this.configService,
      input,
      hls720Dir,
      hls1080Dir,
      crf,
      onHeartbeat,
      'SLOW',
    );
  }

  private async uploadHLSDir(
    videoId: string,
    resLabel: string,
    hlsDir: string,
  ): Promise<void> {
    const files = fs.readdirSync(hlsDir);

    for (const file of files) {
      const filePath = path.join(hlsDir, file);
      const s3Key = `vod/${videoId}/${resLabel}/${file}`;
      const buffer = fs.readFileSync(filePath);

      const mimeType = file.endsWith('.m3u8')
        ? 'application/vnd.apple.mpegurl'
        : 'video/MP2T';

      await firstValueFrom<{ url: string }>(
        this.storageService.upload({
          filename: s3Key,
          data: buffer,
          bucket: this.bucket,
          mimeType,
        }),
      );
    }
  }

  private buildMasterPlaylist(): string {
    const lines = [
      '#EXTM3U',
      '#EXT-X-VERSION:3',
      '',
      '# 480p (fast-lane)',
      '#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=854x480',
      '480p/playlist.m3u8',
      '',
      '# 720p',
      '#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720',
      '720p/playlist.m3u8',
      '',
      '# 1080p',
      '#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080',
      '1080p/playlist.m3u8',
    ];

    return lines.join('\n') + '\n';
  }
}
