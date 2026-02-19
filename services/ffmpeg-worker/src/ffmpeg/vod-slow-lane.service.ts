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

      // Delete the original source recording from the local MinIO mount
      FfmpegUtils.deleteFromStorage(
        this.configService,
        payload.bucket || this.bucket,
        storagePath,
        'SLOW',
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
    const preset =
      this.configService.get<string>('SLOW_LANE_PRESET') || 'veryfast';
    const hlsTime = this.configService.get<string>('HLS_SEGMENT_TIME') || '4';

    const crf720 = crf + 1;
    const crf1080 = crf;

    const playlist720 = path.join(hls720Dir, 'playlist.m3u8');
    const playlist1080 = path.join(hls1080Dir, 'playlist.m3u8');
    const seg720 = path.join(hls720Dir, 'seg_%03d.ts');
    const seg1080 = path.join(hls1080Dir, 'seg_%03d.ts');

    const filterGraph = [
      '[0:v]split=2[v720][v1080]',
      '[v720]scale=-2:720,format=yuv420p[out720]',
      '[v1080]scale=-2:1080,format=yuv420p[out1080]',
    ].join(';');

    await FfmpegUtils.runFFmpeg(
      this.configService,
      [
        '-y',
        '-i',
        input,
        '-filter_complex',
        filterGraph,

        // ── 720p output ──
        '-map',
        '[out720]',
        '-map',
        '0:a?',
        '-c:v',
        'libx264',
        '-preset',
        preset,
        '-crf',
        String(crf720),
        '-threads',
        '2',
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
        '96k',
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
        seg720,
        playlist720,

        // ── 1080p output ──
        '-map',
        '[out1080]',
        '-map',
        '0:a?',
        '-c:v',
        'libx264',
        '-preset',
        preset,
        '-crf',
        String(crf1080),
        '-threads',
        '2',
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
        '128k',
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
        seg1080,
        playlist1080,
      ],
      'SLOW',
      onHeartbeat,
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
