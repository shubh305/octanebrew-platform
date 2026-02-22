import { Injectable, Logger, Inject, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';
import { ConfigService } from '@nestjs/config';
import * as microservices from '@nestjs/microservices';
import { Observable, firstValueFrom } from 'rxjs';
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
 * VOD Fast Lane Service
 */
@Injectable()
export class VodFastLaneService implements OnModuleInit {
  private readonly logger = new Logger(VodFastLaneService.name);
  private readonly workDir: string;
  private readonly bucket = 'openstream-uploads';
  private storageService: StorageServiceProxy;

  constructor(
    @Inject('API_SERVICE')
    private readonly apiClient: microservices.ClientKafka,
    @Inject('STORAGE_SERVICE')
    private readonly storageClient: microservices.ClientGrpc,
    private configService: ConfigService,
  ) {
    this.workDir =
      this.configService.get<string>('VOD_WORK_DIR') || '/tmp/vod-work';
  }

  async onModuleInit() {
    this.storageService =
      this.storageClient.getService<StorageServiceProxy>('StorageService');
    await this.apiClient.connect();

    // Ensure work directory exists
    if (!fs.existsSync(this.workDir)) {
      fs.mkdirSync(this.workDir, { recursive: true });
    }
  }

  async processFastLane(
    payload: VodTranscodePayload,
    onHeartbeat?: () => Promise<void> | void,
  ) {
    const { videoId, storagePath, originalFilename } = payload;
    const jobDir = path.join(this.workDir, videoId);

    this.logger.log(`[FAST] Starting fast-lane for ${videoId}`);

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

      // 2. Get Duration
      const duration = await FfmpegUtils.getVideoDuration(this.configService)(
        sourcePath,
      );
      this.logger.log(`[FAST] Duration: ${duration}s`);

      // 3. Generate Thumbnail
      const thumbPath = path.join(jobDir, 'thumbnail.jpg');
      let thumbnailUrl = '';
      try {
        await this.generateThumbnail(sourcePath, thumbPath, onHeartbeat);
        if (fs.existsSync(thumbPath)) {
          const thumbKey = `vod/${videoId}/thumbnail.jpg`;
          const thumbBuffer = fs.readFileSync(thumbPath);
          const { url } = await firstValueFrom<{ url: string }>(
            this.storageService.upload({
              filename: thumbKey,
              data: thumbBuffer,
              bucket: this.bucket,
              mimeType: 'image/jpeg',
            }),
          );
          thumbnailUrl = url;
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        this.logger.warn(`[FAST] Thumbnail generation failed: ${errorMessage}`);
      }

      // 4. Transcode to 480p HLS
      const hlsDir = path.join(jobDir, 'hls');
      if (!fs.existsSync(hlsDir)) {
        fs.mkdirSync(hlsDir, { recursive: true });
      }

      const playlistPath = path.join(hlsDir, 'playlist.m3u8');
      await this.transcodeTo480pHLS(
        sourcePath,
        hlsDir,
        playlistPath,
        onHeartbeat,
      );

      // 5. Upload outputs
      await this.uploadHLSOutput(videoId, hlsDir);

      const masterManifest = this.buildInitialMasterPlaylist();
      const masterKey = `vod/${videoId}/master.m3u8`;
      const { url: masterUrl } = await firstValueFrom<{ url: string }>(
        this.storageService.upload({
          filename: masterKey,
          data: Buffer.from(masterManifest, 'utf-8'),
          bucket: this.bucket,
          mimeType: 'application/vnd.apple.mpegurl',
        }),
      );

      // Extract audio for Subtitle Pipeline
      let audioPath = '';
      try {
        const audioOutputPath = path.join(jobDir, 'audio.wav');
        await this.extractAudio(sourcePath, audioOutputPath, onHeartbeat);

        if (fs.existsSync(audioOutputPath)) {
          const audioKey = `vod/${videoId}/audio.wav`;
          const audioBuffer = fs.readFileSync(audioOutputPath);
          const { url: audioUrl } = await firstValueFrom<{ url: string }>(
            this.storageService.upload({
              filename: audioKey,
              data: audioBuffer,
              bucket: this.bucket,
              mimeType: 'audio/wav',
            }),
          );
          audioPath = audioUrl;
          this.logger.log(`[FAST] Audio extracted and uploaded: ${audioKey}`);
        }
      } catch (audioErr) {
        const msg =
          audioErr instanceof Error ? audioErr.message : String(audioErr);
        this.logger.warn(`[FAST] Audio extraction failed (non-fatal): ${msg}`);
      }

      // 6. Emit playable event
      const playablePayload = {
        videoId,
        hlsManifest480p: masterUrl,
        duration,
        thumbnailUrl,
        resolutions: ['480p'],
        ts: Date.now(),
      };

      this.logger.log(`[FAST] Emitting video.playable for ${videoId}`);
      await firstValueFrom(
        this.apiClient.emit('video.playable', playablePayload),
      );

      // Emit subtitle request if audio was extracted
      if (audioPath) {
        this.logger.log(
          `[FAST] Emitting video.subtitle.requests for ${videoId}`,
        );
        await firstValueFrom(
          this.apiClient.emit('video.subtitle.requests', {
            videoId,
            audioPath,
            ts: Date.now(),
          }),
        );
      }

      FfmpegUtils.cleanupDir(jobDir, 'FAST');
    } catch (err) {
      const error = err as Error;
      this.logger.error(
        `[FAST] Processing failed for ${videoId}: ${error.message}`,
        error.stack,
      );
      this.apiClient.emit('video.playable', {
        videoId,
        hlsManifest480p: '',
        duration: 0,
        thumbnailUrl: '',
        error: error.message,
        ts: Date.now(),
      });
    }
  }

  private async transcodeTo480pHLS(
    input: string,
    hlsDir: string,
    playlistPath: string,
    onHeartbeat?: () => Promise<void> | void,
  ): Promise<void> {
    const preset = this.configService.get<string>('FAST_LANE_PRESET') || 'fast';
    const hlsTime = this.configService.get<string>('HLS_SEGMENT_TIME') || '4';

    await FfmpegUtils.runFFmpeg(
      this.configService,
      [
        '-y',
        '-i',
        input,
        '-threads',
        '1',
        '-vf',
        'scale=-2:480,format=yuv420p',
        '-c:v',
        'libx264',
        '-preset',
        preset,
        '-crf',
        '23',
        '-color_range',
        '1',
        '-profile:v',
        'baseline',
        '-tune',
        'zerolatency',
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
        path.join(hlsDir, 'seg_%03d.ts'),
        playlistPath,
      ],
      'FAST',
      onHeartbeat,
    );
  }

  private buildInitialMasterPlaylist(): string {
    return [
      '#EXTM3U',
      '#EXT-X-VERSION:3',
      '',
      '# 480p (fast-lane initial)',
      '#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=854x480',
      '480p/playlist.m3u8',
      '',
    ].join('\n');
  }

  private async uploadHLSOutput(
    videoId: string,
    hlsDir: string,
  ): Promise<void> {
    const files = fs.readdirSync(hlsDir);

    for (const file of files) {
      const filePath = path.join(hlsDir, file);
      const s3Key = `vod/${videoId}/480p/${file}`;
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

  private async generateThumbnail(
    input: string,
    output: string,
    onHeartbeat?: () => Promise<void> | void,
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
      'FAST',
      onHeartbeat,
    );
  }

  /**
   * Extract audio track as 16kHz mono WAV for Whisper transcription.
   */
  private async extractAudio(
    input: string,
    output: string,
    onHeartbeat?: () => Promise<void> | void,
  ): Promise<void> {
    await FfmpegUtils.runFFmpeg(
      this.configService,
      [
        '-y',
        '-i',
        input,
        '-vn',
        '-acodec',
        'pcm_s16le',
        '-ar',
        '16000',
        '-ac',
        '1',
        output,
      ],
      'FAST',
      onHeartbeat,
    );
  }
}
