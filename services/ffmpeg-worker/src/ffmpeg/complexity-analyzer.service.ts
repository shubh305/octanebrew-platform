import { Injectable, Logger } from '@nestjs/common';
import { spawn } from 'child_process';
import { ConfigService } from '@nestjs/config';

export interface ComplexityResult {
  score: number;
  crf: number;
  iFrames: number;
  totalFrames: number;
}

/**
 * Complexity Analyzer Service
 *
 * Uses ffprobe to analyze the first 30 seconds of a video,
 * counting I-frames vs P/B-frames to produce a motion complexity
 * score. This score maps to an adaptive CRF value:
 */
@Injectable()
export class ComplexityAnalyzerService {
  private readonly logger = new Logger(ComplexityAnalyzerService.name);

  constructor(private readonly configService: ConfigService) {}

  /**
   * Analyze video complexity by sampling the first 30 seconds.
   */
  async analyze(inputPath: string): Promise<ComplexityResult> {
    try {
      const { iFrames, totalFrames } = await this.countFrameTypes(inputPath);

      if (totalFrames === 0) {
        this.logger.warn('No frames detected, defaulting to CRF 25');
        return { score: 0.5, crf: 25, iFrames: 0, totalFrames: 0 };
      }

      const iFrameRatio = iFrames / totalFrames;
      const score = parseFloat((1 - iFrameRatio).toFixed(4));

      const crf = this.scoreToCrf(score);

      this.logger.log(
        `Complexity: score=${score} (I=${iFrames}/${totalFrames}), CRF=${crf}`,
      );

      return { score, crf, iFrames, totalFrames };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      this.logger.warn(
        `Complexity analysis failed: ${errorMessage}. Defaulting to CRF 25`,
      );
      return { score: 0.5, crf: 25, iFrames: 0, totalFrames: 0 };
    }
  }

  /**
   * Map complexity score to CRF value.
   * Lower CRF = higher quality = more bits allocated.
   */
  private scoreToCrf(score: number): number {
    if (score <= 0.4) return 28;
    if (score <= 0.75) return 25;
    return 22;
  }

  /**
   * Use ffprobe to count I-frames vs total frames
   * in the first 30 seconds of the video.
   */
  private countFrameTypes(
    inputPath: string,
  ): Promise<{ iFrames: number; totalFrames: number }> {
    return new Promise((resolve, reject) => {
      const ffmpegPath =
        this.configService.get<string>('FFMPEG_PATH') || 'ffmpeg';
      const ffprobePath = ffmpegPath.replace('ffmpeg', 'ffprobe');

      const args = [
        '-v',
        'error',
        '-select_streams',
        'v:0',
        '-read_intervals',
        '%+30',
        '-show_entries',
        'frame=pict_type',
        '-of',
        'csv=print_section=0',
        inputPath,
      ];

      const proc = spawn(ffprobePath, args);
      let output = '';
      let stderr = '';

      proc.stdout.on('data', (data: Buffer) => {
        output += data.toString();
      });

      proc.stderr.on('data', (data: Buffer) => {
        stderr += data.toString();
      });

      proc.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(`ffprobe exited with code ${code}: ${stderr}`));
          return;
        }

        const lines = output
          .trim()
          .split('\n')
          .filter((l) => l.length > 0);

        const totalFrames = lines.length;
        const iFrames = lines.filter((l) => l.trim() === 'I').length;

        resolve({ iFrames, totalFrames });
      });

      proc.on('error', (err) => reject(err));
    });
  }
}
