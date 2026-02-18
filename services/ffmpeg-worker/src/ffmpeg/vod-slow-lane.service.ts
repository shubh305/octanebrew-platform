import { Injectable, Logger, Inject, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';
import * as microservices from '@nestjs/microservices';
import { Observable, firstValueFrom } from 'rxjs';
import { ComplexityAnalyzerService } from './complexity-analyzer.service';
import { FfmpegUtils, VodTranscodePayload } from './ffmpeg-utils';

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
    this.apiClient.subscribeToResponseOf('video.complete');
    await this.apiClient.connect();
  }

  async processSlowLane(payload: VodTranscodePayload) {
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

      // 3. Transcode 720p
      const hls720Dir = path.join(jobDir, '720p');
      fs.mkdirSync(hls720Dir, { recursive: true });
      await this.transcodeResolution(
        sourcePath,
        hls720Dir,
        720,
        complexity.crf,
      );

      // 4. Transcode 1080p
      const hls1080Dir = path.join(jobDir, '1080p');
      fs.mkdirSync(hls1080Dir, { recursive: true });
      await this.transcodeResolution(
        sourcePath,
        hls1080Dir,
        1080,
        complexity.crf,
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

      FfmpegUtils.cleanupDir(jobDir, 'SLOW');
    } catch (err) {
      const error = err as Error;
      this.logger.error(
        `[SLOW] Processing failed for ${videoId}: ${error.message}`,
        error.stack,
      );
    }
  }

  private async transcodeResolution(
    input: string,
    hlsDir: string,
    height: number,
    crf: number,
  ): Promise<void> {
    const playlistPath = path.join(hlsDir, 'playlist.m3u8');
    const adjustedCrf = height <= 720 ? crf + 1 : crf;

    await FfmpegUtils.runFFmpeg(
      this.configService,
      [
        '-y',
        '-i',
        input,
        '-vf',
        `scale=-2:${height}`,
        '-c:v',
        'libx264',
        '-preset',
        'medium',
        '-crf',
        String(adjustedCrf),
        '-c:a',
        'aac',
        '-b:a',
        height >= 1080 ? '128k' : '96k',
        '-ac',
        '2',
        '-g',
        '60',
        '-keyint_min',
        '60',
        '-sc_threshold',
        '0',
        '-hls_time',
        '6',
        '-hls_playlist_type',
        'vod',
        '-hls_flags',
        'independent_segments',
        '-hls_segment_filename',
        path.join(hlsDir, `seg_%03d.ts`),
        playlistPath,
      ],
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
