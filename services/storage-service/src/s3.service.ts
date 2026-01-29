import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import {
  S3Client,
  PutObjectCommand,
  HeadBucketCommand,
  CreateBucketCommand,
  GetObjectCommand,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

@Injectable()
export class S3Service {
  private s3Client: S3Client;
  private readonly logger = new Logger(S3Service.name);
  private readonly endpoint: string;
  private readonly region: string;

  constructor(private configService: ConfigService) {
    const accessKeyId = this.configService.get<string>("MINIO_ROOT_USER");
    const secretAccessKey = this.configService.get<string>(
      "MINIO_ROOT_PASSWORD",
    );
    const minioHost = this.configService.get<string>("MINIO_ENDPOINT", "minio");
    const minioPort = this.configService.get<string>("MINIO_PORT", "9000");

    this.endpoint = `http://${minioHost}:${minioPort}`;
    this.region = "us-east-1";

    this.s3Client = new S3Client({
      region: this.region,
      endpoint: this.endpoint,
      forcePathStyle: true,
      credentials: {
        accessKeyId,
        secretAccessKey,
      },
    });
  }

  private async ensureBucketExists(bucket: string): Promise<void> {
    try {
      await this.s3Client.send(new HeadBucketCommand({ Bucket: bucket }));
    } catch (error) {
      if (
        error.name === "NotFound" ||
        error.$metadata?.httpStatusCode === 404
      ) {
        this.logger.log(`Bucket ${bucket} not found. Creating...`);
        await this.s3Client.send(new CreateBucketCommand({ Bucket: bucket }));
        this.logger.log(`Bucket ${bucket} created successfully.`);
      } else {
        throw error;
      }
    }
  }

  async uploadFile(
    bucket: string,
    filename: string,
    body: Buffer,
    mimeType: string,
  ): Promise<string> {
    try {
      await this.ensureBucketExists(bucket);

      const command = new PutObjectCommand({
        Bucket: bucket,
        Key: filename,
        Body: body,
        ContentType: mimeType,
      });

      await this.s3Client.send(command);

      return `${bucket}/${filename}`;
    } catch (error) {
      this.logger.error(
        `Failed to upload ${filename} to ${bucket}: ${error.message}`,
      );
      throw error;
    }
  }

  async getPresignedUrl(
    bucket: string,
    key: string,
    expiry: number = 3600,
  ): Promise<string> {
    const objectKey = key.startsWith(`${bucket}/`)
      ? key.split(`${bucket}/`)[1]
      : key;

    const command = new GetObjectCommand({
      Bucket: bucket,
      Key: objectKey,
    });

    const signedUrl = await getSignedUrl(this.s3Client, command, {
      expiresIn: expiry,
    });

    // Replace internal MinIO host with public host
    const minioHost = this.configService.get<string>("MINIO_ENDPOINT", "minio");
    const minioPort = this.configService.get<string>("MINIO_PORT", "9000");
    const internalOrigin = `http://${minioHost}:${minioPort}`;

    const publicHost = this.configService.get<string>(
      "STORAGE_PUBLIC_HOST",
      internalOrigin,
    );

    if (publicHost === internalOrigin) {
      return signedUrl;
    }

    const isIp = /^[0-9]+(\.[0-9]+){3}(:[0-9]+)?$/.test(publicHost);
    const protocol = isIp ? "http" : "https";

    // Replace the internal origin with the public one
    return signedUrl.replace(internalOrigin, `${protocol}://${publicHost}`);
  }
}
