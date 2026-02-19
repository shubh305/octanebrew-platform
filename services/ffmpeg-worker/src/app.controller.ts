import { Controller, Logger } from '@nestjs/common';
import {
  EventPattern,
  Payload,
  Ctx,
  KafkaContext,
} from '@nestjs/microservices';
import { VodFastLaneService } from './ffmpeg/vod-fast-lane.service';
import { VodSlowLaneService } from './ffmpeg/vod-slow-lane.service';

import { VodTranscodePayload } from './ffmpeg/ffmpeg-utils';

@Controller()
export class AppController {
  private readonly logger = new Logger(AppController.name);
  private readonly lane = (process.env.PROCESS_LANE || 'all').toLowerCase();

  constructor(
    private readonly vodFastLane: VodFastLaneService,
    private readonly vodSlowLane: VodSlowLaneService,
  ) {}

  /** VOD upload pipeline — fast lane (480p HLS + thumbnail) */
  @EventPattern('vod.transcode.fast')
  async handleVodFastLane(
    @Payload() message: Record<string, unknown>,
    @Ctx() context: KafkaContext,
  ) {
    if (this.lane === 'slow') return;

    this.logger.log(`Received VOD fast-lane job: ${JSON.stringify(message)}`);

    const payload = (message.value ?? message) as VodTranscodePayload;
    const heartbeat = context.getHeartbeat();
    const heartbeatCallback = () => heartbeat();

    await this.vodFastLane.processFastLane(payload, heartbeatCallback);
  }

  /** VOD upload pipeline — slow lane (720p + 1080p adaptive CRF) */
  @EventPattern('vod.transcode.slow')
  async handleVodSlowLane(
    @Payload() message: Record<string, unknown>,
    @Ctx() context: KafkaContext,
  ) {
    if (this.lane === 'fast') return;

    this.logger.log(`Received VOD slow-lane job: ${JSON.stringify(message)}`);

    const payload = (message.value ?? message) as VodTranscodePayload;
    const heartbeat = context.getHeartbeat();
    const heartbeatCallback = () => heartbeat();

    try {
      await this.vodSlowLane.processSlowLane(payload, heartbeatCallback);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      this.logger.error(`Error in slow lane processing: ${errorMessage}`);
      throw err;
    }
  }
}
