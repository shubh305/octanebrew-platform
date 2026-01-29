import { NestFactory } from "@nestjs/core";
import { MicroserviceOptions, Transport } from "@nestjs/microservices";
import { join } from "path";
import { AppModule } from "./app.module";

async function bootstrap() {
  const app = await NestFactory.createMicroservice<MicroserviceOptions>(
    AppModule,
    {
      transport: Transport.GRPC,
      options: {
        package: "storage",
        protoPath: join(__dirname, "storage.proto"),
        url: "0.0.0.0:50051",
      },
    },
  );
  await app.listen();
  console.log("Storage Service is listening on gRPC port 50051");
}
bootstrap();
