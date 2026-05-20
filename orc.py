import os
import asyncio
import hmi_simulator
import hmi_modbus_client

# os.environ['PYTHONASYNCIODEBUG'] = '1'

async def main():
    await asyncio.gather(
        hmi_simulator.main(),
        hmi_modbus_client.main()
    )

if __name__ == "__main__":
    asyncio.run(main())
