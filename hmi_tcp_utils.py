from pyModbusTCP.client import ModbusClient
import logging
import logging.config
import mule_comms.utils.log_utils as lu

logging.config.dictConfig(lu.get_log_config_dict())

# Configure logging
logger = logging.getLogger('hmi')


class ModbusTcpClient:
    def __init__(self, ip_address, port=8888, unit=1):
        self.ip_address = ip_address
        self.port = port
        self.unit = unit
        self.client = ModbusClient(
            host=self.ip_address,
            port=self.port,
            unit_id=self.unit,
            auto_open=True,
            auto_close=True,
        )

    def read_coil(self, address):
        try:
            value = self.client.read_coils(address, 1)
            if value:
                return bool(value[0])
            else:
                logger.error(f"Error reading coil at address {address}")
                return None
        except Exception as e:
            logger.error(f"Exception at read_coil : {e}")
            return None

    def write_coil(self, address, value):
        try:
            success = self.client.write_single_coil(address, value)
            if success:
                return True
            else:
                logger.error(f"Error writing coil at address {address}")
                return False
        except Exception as e:
            logger.error(f"Exception at write_coil: {e}")
            return False

    def read_register(self, address):
        try:
            value = self.client.read_holding_registers(address, 1)
            if value:
                return value[0]
            else:
                logger.error(f"Error reading register at address {address}")
                return None
        except Exception as e:
            logger.error(f"Exception at read_register: {e}")
            return None

    def write_register(self, address, value):
        try:
            success = self.client.write_single_register(address, value)
            if success:
                return True
            else:
                logger.error(f"Error writing register at address {address}")
                return False
        except Exception as e:
            logger.error(f"Exception at write_register: {e}")
            return False

    def write_string_to_registers(self, address, string_value, length):
        try:
            byte_array = list(string_value.encode("utf-8"))
            self.client.write_multiple_registers(address, [0] * length)
            success = self.client.write_multiple_registers(address, byte_array)
            if success:
                return True
            else:
                logger.error(
                    f"Error writing string '{string_value}' to registers starting at address {address}"
                )
                return False
        except Exception as e:
            logger.error(f"Exception at write_string_to_registers: {e}")
            return False

    def read_string_from_registers(self, address, length):
        try:
            # Read the registers as a byte array
            byte_array = self.client.read_holding_registers(address, length)
            if byte_array:
                # Convert byte array to string
                string_value = bytes(byte_array).decode("utf-8")
                return string_value
            else:
                logger.error(
                    f"Error reading string from registers starting at address {address}"
                )
                return None
        except Exception as e:
            logger.error(f"Exception at read_string_from_registers: {e}")
            return None