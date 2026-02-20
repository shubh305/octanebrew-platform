import { Controller, Logger } from '@nestjs/common';
import {
  EventPattern,
  Payload,
  Ctx,
  KafkaContext,
} from '@nestjs/microservices';
import { VodFastLaneService } from './ffmpeg/vod-fast-lane.service';
import { VodSlowLaneService } from './ffmpeg/vod-slow-lane.service';
import {
  ClipTranscodeService,
  ClipTranscodePayload,
} from './ffmpeg/clip-transcode.service';

import { VodTranscodePayload } from './ffmpeg/ffmpeg-utils';

@Controller()
export class AppController {
  private readonly logger = new Logger(AppController.name);
  private readonly lane = (process.env.PROCESS_LANE || 'all').toLowerCase();

  constructor(
    private readonly vodFastLane: VodFastLaneService,
    private readonly vodSlowLane: VodSlowLaneService,
    private readonly clipTranscodeWorker: ClipTranscodeService,
  ) {}

  /** VOD upload pipeline — fast lane (480p HLS + thumbnail) */
  @EventPattern('vod.transcode.fast')
  async handleVodFastLane(
    @Payload() message: Record<string, unknown>,
    @Ctx() context: KafkaContext,
  ) {
    if (this.lane === 'slow') {
      await this.commitOffset(context);
      return;
    }

    this.logger.log(`Received VOD fast-lane job: ${JSON.stringify(message)}`);

    const payload = (message.value ?? message) as VodTranscodePayload;
    const heartbeat = context.getHeartbeat();
    const heartbeatCallback = () => heartbeat();

    await this.vodFastLane.processFastLane(payload, heartbeatCallback);
    await this.commitOffset(context);
  }

  /** VOD upload pipeline — slow lane (720p + 1080p adaptive CRF) */
  @EventPattern('vod.transcode.slow')
  async handleVodSlowLane(
    @Payload() message: Record<string, unknown>,
    @Ctx() context: KafkaContext,
  ) {
    if (this.lane === 'fast') {
      await this.commitOffset(context);
      return;
    }

    this.logger.log(`Received VOD slow-lane job: ${JSON.stringify(message)}`);

    const payload = (message.value ?? message) as VodTranscodePayload;
    const heartbeat = context.getHeartbeat();
    const heartbeatCallback = () => heartbeat();

    try {
      await this.vodSlowLane.processSlowLane(payload, heartbeatCallback);
      await this.commitOffset(context);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      this.logger.error(`Error in slow lane processing: ${errorMessage}`);
      throw err;
    }
  }

  /** Clip transcode pipeline — */
  @EventPattern('clip.transcode')
  async handleClipTranscode(
    @Payload() message: Record<string, unknown>,
    @Ctx() context: KafkaContext,
  ) {
    if (this.lane === 'fast') {
      await this.commitOffset(context);
      return;
    }

    this.logger.log(`Received clip transcode job: ${JSON.stringify(message)}`);

    const payload = (message.value ?? message) as ClipTranscodePayload;
    const heartbeat = context.getHeartbeat();
    const heartbeatCallback = () => heartbeat();

    try {
      await this.clipTranscodeWorker.processClipTranscode(
        payload,
        heartbeatCallback,
      );
      await this.commitOffset(context);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      this.logger.error(`Error in clip transcode processing: ${errorMessage}`);
      throw err;
    }
  }

  /** Explicitly commit the current message's offset to advance the consumer group. */
  private async commitOffset(context: KafkaContext): Promise<void> {
    try {
      const topic = context.getTopic();
      const partition = context.getPartition();
      const { offset } = context.getMessage();
      const consumer = context.getConsumer();
      const nextOffset = (parseInt(offset, 10) + 1).toString();
      await consumer.commitOffsets([{ topic, partition, offset: nextOffset }]);
      this.logger.debug(
        `[${topic}] Committed offset ${nextOffset} (partition ${partition})`,
      );
    } catch (err) {
      this.logger.warn(
        `Offset commit failed (non-fatal): ${(err as Error).message}`,
      );
    }
  }
}
