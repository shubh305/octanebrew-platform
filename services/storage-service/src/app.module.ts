import { Module } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { StorageController } from "./storage.controller";
import { S3Service } from "./s3.service";

@Module({
  imports: [
    ConfigModule.forRoot({
      envFilePath: [".env", "../../.env"],
      isGlobal: true,
    }),
  ],
  controllers: [StorageController],
  providers: [S3Service],
})
export class AppModule {}
