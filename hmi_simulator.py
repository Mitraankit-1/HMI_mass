import aioredis
import aiofiles
import asyncio
import ast

async def producer(aredis_conn):
    file_path = 'hmi_db'
    async with aiofiles.open(file_path, 'r') as file:
        # Read and publish all existing lines in the file
        async for line in file:
            await asyncio.sleep(1)
            if line.strip():  # Check if the line is not empty
                try:
                    data_dict = ast.literal_eval(line)
                    await aredis_conn.publish("channel:sherpa_to_hmi_frontend", str(data_dict))
                except (ValueError, SyntaxError):
                    print("Failed to parse line:", line)

        # Move the pointer to the end of the file
        await file.seek(0, 2)

        # Monitor the file for new lines
        while True:
            await asyncio.sleep(1)
            line = await file.readline()
            if line:
                if line.strip():  # Check if the line is not empty
                    try:
                        data_dict = ast.literal_eval(line)
                        print(data_dict)
                        await aredis_conn.publish("channel:sherpa_to_hmi_frontend", str(data_dict))
                    except (ValueError, SyntaxError):
                        print("Failed to decode JSON from line:", line)
            else:
                await asyncio.sleep(1) 

async def consumer(aredis_conn):
    psub = aredis_conn.pubsub()
    await psub.subscribe("channel:hmi_frontend_to_sherpa")
    while True:
        message = await psub.get_message(ignore_subscribe_messages=True, timeout=2)
        if message is not None:
            print(message)


async def main():
    redis_url = 'redis://localhost:6379'
    aredis_conn = await aioredis.Redis.from_url(redis_url)
    print("connected to redis")
    rw = [asyncio.create_task(producer(aredis_conn)), asyncio.create_task(consumer(aredis_conn))]
    print("created tasks")

    try:
        await asyncio.gather(*rw)
    except Exception as e:
        [t.cancel() for t in rw]
        raise e
    finally:
        [t.cancel() for t in rw]
        await aredis_conn.close()
       