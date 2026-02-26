import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import {
  S3Client,
  PutObjectCommand,
  HeadBucketCommand,
  CreateBucketCommand,
  GetObjectCommand,
  PutBucketPolicyCommand,
  DeleteObjectCommand,
  DeleteObjectsCommand,
  ListObjectsV2Command,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

@Injectable()
export class S3Service {
  private s3Client: S3Client;
  private signingClient: S3Client;
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

    const publicHost = this.configService.get<string>(
      "STORAGE_PUBLIC_HOST",
      `minio:${minioPort}`,
    );
    const isIp = /^[0-9]+(\.[0-9]+){3}(:[0-9]+)?$/.test(publicHost);
    let publicEndpoint = publicHost;
    if (!publicHost.startsWith("http")) {
      publicEndpoint = isIp ? `http://${publicHost}` : `https://${publicHost}`;
    }

    this.signingClient = new S3Client({
      region: this.region,
      endpoint: publicEndpoint,
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

  private async setPublicBucketPolicy(bucket: string): Promise<void> {
    const policy = {
      Version: "2012-10-17",
      Statement: [
        {
          Sid: "PublicReadGetObject",
          Effect: "Allow",
          Principal: "*",
          Action: ["s3:GetObject"],
          Resource: [`arn:aws:s3:::${bucket}/*`],
        },
      ],
    };

    try {
      await this.s3Client.send(
        new PutBucketPolicyCommand({
          Bucket: bucket,
          Policy: JSON.stringify(policy),
        }),
      );
      this.logger.log(`Set public read policy for bucket ${bucket}`);
    } catch (e) {
      this.logger.error(`Failed to set bucket policy: ${e.message}`);
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
      await this.setPublicBucketPolicy(bucket);

      const command = new PutObjectCommand({
        Bucket: bucket,
        Key: filename,
        Body: body,
        ContentType: mimeType,
      });

      await this.s3Client.send(command);

      const endpoint = await this.signingClient.config.endpoint();
      const baseUrl = `${endpoint.protocol}//${endpoint.hostname}${endpoint.port ? `:${endpoint.port}` : ""}`;

      return `${baseUrl}/${bucket}/${filename}`;
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

    // Use the signing client so the signature matches the public Host header
    const signedUrl = await getSignedUrl(this.signingClient, command, {
      expiresIn: expiry,
    });

    return signedUrl;
  }

  async delete(
    bucket: string,
    key: string,
    isFolder: boolean = false,
  ): Promise<{ success: boolean; deletedCount: number }> {
    try {
      if (!isFolder) {
        this.logger.log(`Deleting file: ${key} from bucket: ${bucket}`);
        await this.s3Client.send(
          new DeleteObjectCommand({
            Bucket: bucket,
            Key: key,
          }),
        );
        return { success: true, deletedCount: 1 };
      }

      // Folder deletion (prefix-based)
      this.logger.log(`Deleting folder/prefix: ${key} from bucket: ${bucket}`);
      let deletedCount = 0;
      let continuationToken: string | undefined = undefined;

      do {
        const listCommand = new ListObjectsV2Command({
          Bucket: bucket,
          Prefix: key.endsWith("/") ? key : `${key}/`,
          ContinuationToken: continuationToken,
        });

        const listResponse = await this.s3Client.send(listCommand);

        if (listResponse.Contents && listResponse.Contents.length > 0) {
          const deleteParams = {
            Bucket: bucket,
            Delete: {
              Objects: listResponse.Contents.map((obj) => ({ Key: obj.Key })),
            },
          };

          await this.s3Client.send(new DeleteObjectsCommand(deleteParams));
          deletedCount += listResponse.Contents.length;
        }

        continuationToken = listResponse.NextContinuationToken;
      } while (continuationToken);

      this.logger.log(
        `Successfully deleted ${deletedCount} objects with prefix: ${key}`,
      );
      return { success: true, deletedCount };
    } catch (error) {
      this.logger.error(
        `Failed to delete ${isFolder ? "folder" : "file"} ${key} from ${bucket}: ${error.message}`,
      );
      return { success: false, deletedCount: 0 };
    }
  }
}
