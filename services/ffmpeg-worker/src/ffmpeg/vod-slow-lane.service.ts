import { Injectable, Logger, Inject, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';
import * as microservices from '@nestjs/microservices';
import { Observable, firstValueFrom } from 'rxjs';
import { ComplexityAnalyzerService } from './complexity-analyzer.service';
import { FfmpegUtils, VodTranscodePayload, SlowLaneStep } from './ffmpeg-utils';

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
    const step = payload.step || '720p';
    this.logger.log(
      `[SLOW] Routing to step: ${String(step)} for video ${payload.videoId}`,
    );

    try {
      if (step === '720p' || step === '1080p') {
        await this.runTranscodeStep(payload, step, onHeartbeat);
      } else if (step === 'sprites') {
        await this.runSpritesStep(payload, onHeartbeat);
      } else {
        this.logger.error(`Unknown slow-lane step: ${String(step)}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.logger.error(
        `[SLOW] Step ${String(step)} failed for ${payload.videoId}: ${msg}`,
      );
      throw err;
    }
  }

  /**
   * Universal transcode step for 720p and 1080p
   */
  private async runTranscodeStep(
    payload: VodTranscodePayload,
    res: '720p' | '1080p',
    onHeartbeat?: () => Promise<void> | void,
  ) {
    const { videoId } = payload;
    const { jobDir, sourcePath } = await this.prepareWorkDir(payload, res);

    const complexity = await this.complexityAnalyzer.analyze(sourcePath);
    const slowPreset =
      this.configService.get<string>('SLOW_LANE_PRESET') || 'superfast';

    // CRF logic: 720p gets +1 penalty for speed/size balance in slow lane
    const crfValue = res === '720p' ? complexity.crf + 1 : complexity.crf;
    const resDir = path.join(jobDir, res);

    if (!fs.existsSync(resDir)) {
      fs.mkdirSync(resDir, { recursive: true });
    }

    await FfmpegUtils.transcodeSingleResolution(
      this.configService,
      sourcePath,
      resDir,
      res,
      crfValue,
      slowPreset,
      onHeartbeat,
      `SLOW-${res.toUpperCase()}`,
    );

    await this.uploadHLSDir(videoId, res, resDir);
    const masterUrl = await this.uploadMasterPlaylist(videoId);

    // Progression logic
    const nextStep: SlowLaneStep | null = res === '720p' ? '1080p' : 'sprites';
    const resolutions =
      res === '720p' ? ['480p', '720p'] : ['480p', '720p', '1080p'];

    if (res === '1080p') {
      this.logger.log(`[SLOW-${res}] Step complete. Emitting video.complete.`);
      await firstValueFrom(
        this.apiClient.emit('video.complete', {
          videoId,
          crfUsed: crfValue,
          complexityScore: complexity.score,
          resolutions,
          hlsManifest: masterUrl,
          ts: Date.now(),
        }),
      );
    } else {
      this.logger.log(
        `[SLOW-${res}] Step complete. Transitioning to next step (${nextStep}).`,
      );
    }

    if (nextStep) {
      await firstValueFrom(
        this.apiClient.emit('vod.transcode.slow', {
          ...payload,
          step: nextStep,
        }),
      );
    }

    FfmpegUtils.cleanupDir(jobDir, `SLOW-${res}`);
  }

  private async runSpritesStep(
    payload: VodTranscodePayload,
    onHeartbeat?: () => Promise<void> | void,
  ) {
    const { videoId } = payload;
    const { jobDir, sourcePath } = await this.prepareWorkDir(
      payload,
      'sprites',
    );

    const durationSeconds = await FfmpegUtils.getVideoDuration(
      this.configService,
    )(sourcePath);
    if (durationSeconds > 0) {
      const params = computeSpriteParams(durationSeconds);
      const spriteLocalPath = path.join(jobDir, 'sprites.jpg');

      await FfmpegUtils.runFFmpeg(
        this.configService,
        [
          '-y',
          '-i',
          sourcePath,
          '-vf',
          `fps=1/${params.interval},scale=160:90,tile=${params.cols}x${params.rows}`,
          '-frames:v',
          '1',
          '-q:v',
          '5',
          spriteLocalPath,
        ],
        'SPRITES',
        onHeartbeat,
      );

      const spriteKey = `vod/${videoId}/sprites/sprites.jpg`;
      const vttKey = `vod/${videoId}/sprites/thumbnails.vtt`;

      await firstValueFrom(
        this.storageService.upload({
          filename: spriteKey,
          data: fs.readFileSync(spriteLocalPath),
          bucket: this.bucket,
          mimeType: 'image/jpeg',
        }),
      );

      await firstValueFrom(
        this.storageService.upload({
          filename: vttKey,
          data: Buffer.from(
            generateVTT('sprites.jpg', durationSeconds, params),
            'utf-8',
          ),
          bucket: this.bucket,
          mimeType: 'text/vtt',
        }),
      );

      this.logger.log(
        `[SLOW-SPRITES] Sprites complete. Emitting video.sprites.complete.`,
      );
      await firstValueFrom(
        this.apiClient.emit('video.sprites.complete', {
          videoId,
          spritePath: spriteKey,
          vttPath: vttKey,
          frameCount: params.frameCount,
          interval: params.interval,
          cols: params.cols,
          rows: params.rows,
          ts: Date.now(),
        }),
      );
    }

    FfmpegUtils.cleanupDir(jobDir, 'SLOW-SPRITES');
  }

  private async prepareWorkDir(payload: VodTranscodePayload, step: string) {
    const jobDir = path.join(this.workDir, `${payload.videoId}-${step}`);
    if (!fs.existsSync(jobDir)) {
      fs.mkdirSync(jobDir, { recursive: true });
    }

    const sourceExt = path.extname(payload.originalFilename) || '.mp4';
    const sourcePath = path.join(jobDir, `source${sourceExt}`);

    await FfmpegUtils.downloadFromStorage(
      this.configService,
      payload.bucket || this.bucket,
      payload.storagePath,
      sourcePath,
    );

    return { jobDir, sourcePath };
  }

  private async uploadMasterPlaylist(videoId: string): Promise<string> {
    const masterManifest = this.buildMasterPlaylist();
    const masterKey = `vod/${videoId}/master.m3u8`;
    const { url } = await firstValueFrom(
      this.storageService.upload({
        filename: masterKey,
        data: Buffer.from(masterManifest, 'utf-8'),
        bucket: this.bucket,
        mimeType: 'application/vnd.apple.mpegurl',
      }),
    );
    return url;
  }

  private async uploadHLSDir(
    videoId: string,
    resLabel: string,
    hlsDir: string,
  ) {
    for (const file of fs.readdirSync(hlsDir)) {
      const filePath = path.join(hlsDir, file);
      const s3Key = `vod/${videoId}/${resLabel}/${file}`;
      const mimeType = file.endsWith('.m3u8')
        ? 'application/vnd.apple.mpegurl'
        : 'video/MP2T';
      await firstValueFrom(
        this.storageService.upload({
          filename: s3Key,
          data: fs.readFileSync(filePath),
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
