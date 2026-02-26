import { Controller, Logger } from "@nestjs/common";
import { GrpcMethod } from "@nestjs/microservices";
import { S3Service } from "./s3.service";

interface UploadRequest {
  filename: string;
  data: Buffer;
  bucket: string;
  mimeType: string;
}

interface UploadResponse {
  url: string;
}

interface GetPresignedUrlRequest {
  bucket: string;
  key: string;
  expiry: number;
}

interface GetPresignedUrlResponse {
  url: string;
}

@Controller()
export class StorageController {
  private readonly logger = new Logger(StorageController.name);

  constructor(private readonly s3Service: S3Service) {}

  @GrpcMethod("StorageService", "Upload")
  async upload(data: UploadRequest): Promise<UploadResponse> {
    this.logger.log(
      `Received upload request for ${data.filename} in bucket ${data.bucket}`,
    );

    const url = await this.s3Service.uploadFile(
      data.bucket,
      data.filename,
      data.data,
      data.mimeType,
    );

    return { url };
  }

  @GrpcMethod("StorageService", "GetPresignedUrl")
  async getPresignedUrl(
    data: GetPresignedUrlRequest,
  ): Promise<GetPresignedUrlResponse> {
    const url = await this.s3Service.getPresignedUrl(
      data.bucket,
      data.key,
      data.expiry,
    );
    return { url };
  }

  @GrpcMethod("StorageService", "Delete")
  async delete(data: {
    bucket: string;
    key: string;
    isFolder: boolean;
  }): Promise<{ success: boolean; deletedCount: number }> {
    this.logger.log(
      `Received delete request for ${data.key} (isFolder: ${data.isFolder}) in bucket ${data.bucket}`,
    );
    return this.s3Service.delete(data.bucket, data.key, data.isFolder);
  }
}
