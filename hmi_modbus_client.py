import asyncio
import aioredis
import ast
import json
import logging
import logging.config
from dataclasses import asdict

# ati code imports
from ati.common.config import load_mule_config
from hmi_handler import Handler
import hmi_utils as hu
import hmi_models as hmm
from hmi_tcp_utils import ModbusTcpClient
import mule_comms.utils.log_utils as lu

logging.config.dictConfig(lu.get_log_config_dict())
logger = logging.getLogger("hmi")


async def modbus_reader(aredis_conn, handler):
    addresses_to_monitor = list(hmm.ReadAddresses().__dict__.values())
    previous_values = {addr: False for addr in addresses_to_monitor}
    client = ModbusTcpClient(hmm.Const.MODBUS_IP, port=8888)
    while True:
        for address in addresses_to_monitor:
            current_value = client.read_coil(address)
            if address == 550:
                current_value = client.read_register(address)
        
            if current_value is None:
                logger.error(
                    f"Error reading Modbus register {address}: {current_value}"
                )
                continue 

            if previous_values[address] != current_value:
                # Check if mode was recently changed and skip processing switch_mode changes
                if address == hmm.ReadAddresses.switch_mode and handler.check_recently_changed():
                    logger.info(f"Skipping switch_mode change processing - mode recently changed by handler")
                    previous_values[address] = current_value
                    continue
                    
                logger.info(
                    f"Value change detected at address {address}: {current_value}"
                )
                previous_values[address] = current_value
                data = hmm.Const.DATA_MODEL_MAPPING.get(address, {}).get(
                    current_value
                )
                if data:
                    await aredis_conn.publish(
                        "channel:hmi_frontend_to_sherpa", json.dumps(asdict(data))
                    )
        await asyncio.sleep(1)


async def modbus_writer(aredis_conn, handler):
    psub = aredis_conn.pubsub()
    await psub.subscribe("channel:sherpa_to_hmi_frontend")
    while True:
        message = await psub.get_message(ignore_subscribe_messages=True, timeout=2)
        if message is None:
            continue
        data = ast.literal_eval(message["data"].decode())
        msg_types = [
            "network_stats",
            "sherpa_status",
            "alerts",
            "peripheral_trip_description",
            "error",
            "trip_status",
            "trip_description",
            "sherpa_picking",
            "detected_obstacle",
            "mule_error",
        ]

        # Handle action-based messages (like terminate_trip)
        if 'action' in data:
            action = data['action']
            data['type'] = f'action_{action}'
            handler.handle(data)
        else:
            data['type'] = hu.shrink_message_type(data['type'])
            if data['type'] in msg_types:
                data['type'] = 'set_' + data['type']
                handler.handle(data)
            else:
                continue


async def main():
    logger.info("Started modbus server")
    config = load_mule_config()
    redis_url = config["redis"]["url"]

    # Handler created once — survives Redis reconnects so error_active / alert flags persist
    handler = Handler()

    while True:
        rw = []
        try:
            redis_conn = aioredis.Redis.from_url(redis_url)
            rw = [
                asyncio.create_task(modbus_writer(redis_conn, handler)),
                asyncio.create_task(modbus_reader(redis_conn, handler)),
            ]
            await asyncio.gather(*rw)
        except Exception as e:
            logger.error(f"Exception in modbus client: {e}")

        for t in rw:
            t.cancel()

        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())