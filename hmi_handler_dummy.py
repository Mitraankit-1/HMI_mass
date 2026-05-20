import logging
import logging.config
import time

#ati imports
import hmi_utils as hu
from hmi_tcp_utils import ModbusTcpClient
import hmi_models as hmm
# import mule_comms.utils.log_utils as lu

# logging.config.dictConfig(lu.get_log_config_dict())

logger = logging.getLogger('hmi')

class Handler:
    def __init__(self):
        self.client = ModbusTcpClient(hmm.Const.MODBUS_IP, port=8888)

    def handle(self, msg):
        msg_handler = getattr(self, f"handle_{msg['type']}", None)

        if not msg_handler:
            # logger.error(f"no handler defined for {msg.type}")
            return

        response = msg_handler(msg)
        return response

    def handle_set_network_stats(self, msg):
        # self.switch_to_home()
        status = 1 if str(msg["connected_to_FM"]) == "True" else 0
        if self.client.write_coil(hmm.WriteAddresses.CONNECTED_TO_FM, status):
            logger.info("Successfully sent connected fm status")
        else:
            logger.error("Failed to send connected fm status")

    def handle_set_sherpa_status(self, msg):
        sherpa_name = msg["sherpa_name"]
        battery_status = int(msg["battery_status"])
        mode = msg["mode"]
        status_to_color = {
            (-1, 0): hmm.BatteryBar.EMPTY,
            (1, 10): hmm.BatteryBar.RED,
            (11, 20): hmm.BatteryBar.YELLOW,
            (21, 100): hmm.BatteryBar.GREEN
        }
        
        if mode == "fleet":
            self.switch_to_home()

        if self.client.write_string_to_registers(
            hmm.WriteAddresses.SHERPA_NAME, sherpa_name, 30
        ):
            logger.info("Successfully wrote sherpa name to register")

        color = hmm.BatteryBar.GREEN  # Default color
        for (low, high), color_option in status_to_color.items():
            if low <= battery_status <= high:
                color = color_option
                break

        # Write the color to the register and log the action
        if self.client.write_register(hmm.WriteAddresses.BATTERY_COLOUR_INDICATOR, color):
            logger.info(f"Battery bar set to {color}")

        if self.client.write_register(hmm.WriteAddresses.BATTERY_STATUS, battery_status):
            logger.info("Successfully wrote battery status to register")
        else:
            logger.info("Failed to write battery status to register")

        if battery_status <= 20 and mode != "error":
            self.switch_to_warning()
            if self.client.write_string_to_registers(
                hmm.WriteAddresses.WARNING_INFO, "Low Battery", 50
            ):
                logger.info("Low battery alert sent")
            else:
                logger.info("Failed to send low battery alert")

        if mode == "error":
            error_info = msg["error_info"]
            self.switch_to_error()
            if error_info == "obstacle Detected error":
                if self.client.write_register(
                    hmm.WriteAddresses.ERRORS, hmm.ImageTypes.SHOW_OBSTACLE_IMAGE
                ):
                    logger.info("Shown obstacle detected image")
            if self.client.write_register(
                    hmm.WriteAddresses.ERRORS, hmm.ImageTypes.HIDE_OBSTACLE_IMAGE
                ):
                    logger.info("Hided obstacle detected image")
            if self.client.write_string_to_registers(
                hmm.WriteAddresses.ERROR_INFO, error_info, 50
            ):
                logger.info(f"Successfully wrote error info : {error_info} to register")

    def handle_set_alerts(self, msg):
        self.reset_all_switch_registers()
        obstructed = str(msg.get('obstructed', ''))
        emergency_button = str(msg.get('emergency_button', ''))
        if emergency_button != "":
            self.switch_to_error()
            time.sleep(0.2)
            if self.client.write_string_to_registers(hmm.WriteAddresses.ERROR_INFO, emergency_button, 50):
                logger.info(f"Successfully wrote error info : {emergency_button} to register")
        else:
            self.reset_all_switch_registers()
            
        if obstructed != "":
            self.switch_to_warning()
            if self.client.write_register(hmm.WriteAddresses.WARNINGS, hmm.ImageTypes.SHOW_OBSTACLE_IMAGE):
                logger.info("Obstacle detection alert sent")
            else:
                logger.error("Failed to send obstacle detection alert")
            if self.client.write_string_to_registers(hmm.WriteAddresses.WARNING_INFO, obstructed, 50):
                logger.info(f"Successfully wrote error info : {obstructed} to register")
        # else:
        #     self.switch_to_home()
        
        
        # if obstructed != "" or emergency_button == "Emergency Button was pressed":
        #     if obstructed != "":
        #         self.switch_to_warning()
        #         if self.client.write_register(hmm.WriteAddresses.WARNINGS, hmm.ImageTypes.SHOW_OBSTACLE_IMAGE):
        #             logger.info("Obstacle detection alert sent")
        #         else:
        #             logger.error("Failed to send obstacle detection alert")
        #         if self.client.write_string_to_registers(hmm.WriteAddresses.WARNING_INFO, obstructed, 50):
        #             logger.info(f"Successfully wrote error info : {obstructed} to register")
        #     if emergency_button != "":
        #         self.switch_to_error()
        #         time.sleep(0.2)
        #         if self.client.write_string_to_registers(
        #             hmm.WriteAddresses.ERROR_INFO, emergency_button, 50
        #         ):
        #             logger.info(f"Successfully wrote error info : {emergency_button} to register")
        # else:
        #     self.switch_to_home()

    def handle_set_trip_description(self, msg):
        logger.info(f"Entered in trip description")
        status = str(msg["status"])
        next_station = msg["next_station"]
        waiting_for = msg["waiting_for"]

        if status == "en_route":
            if self.client.write_coil(hmm.WriteAddresses.EN_ROUTE, 1):
                logger.info("Set status to en_route")
        else:
            if self.client.write_coil(hmm.WriteAddresses.EN_ROUTE, 0):
                pass

        if self.client.write_string_to_registers(
            hmm.WriteAddresses.NEXT_STATION, next_station, 30
        ):
            logger.info(f"Successfully set next station to {next_station}")

        if waiting_for and status != "en_route":
            self.switch_to_warning()
            if self.client.write_register(
                    hmm.WriteAddresses.ERRORS, hmm.ImageTypes.HIDE_OBSTACLE_IMAGE
                ):
                    logger.info("Hided obstacle detected image")
            if self.client.write_string_to_registers(
                hmm.WriteAddresses.WARNING_INFO, waiting_for, 50
            ):
                logger.info(f"Successfully set warning : {waiting_for}")
        else:
            self.switch_to_home()

    def handle_set_trip_status(self, msg):
        stoppage_type = hu.shrink_message_type(msg["stoppages"]["type"])
        next_station = msg["trip_info"]["destination_name"]
        if self.client.write_string_to_registers(
            hmm.WriteAddresses.NEXT_STATION, next_station, 30
        ):
            logger.info(f"Successfully set next station to {next_station}")
        if stoppage_type == "detected_obstacle":
            self.switch_to_warning()
            if self.client.write_register(
                    hmm.WriteAddresses.ERRORS, hmm.ImageTypes.SHOW_OBSTACLE_IMAGE
                ):
                    logger.info("Shown obstacle detected image")
            if self.client.write_string_to_registers(
                hmm.WriteAddresses.WARNING_INFO, "Obstacle detected", 50
            ):
                logger.info("Successfully set obstacle detected warning")
            else:
                logger.info("Failed to set obstacle detected")
        else:
            self.switch_to_home()

    def switch_to_warning(self):
        self.client.write_register(0, 0)  # Home false
        self.client.write_register(9, 0)  # Error false
        time.sleep(0.2)
        self.client.write_register(7, 7)  # Warning true
        

    def switch_to_home(self):
        self.client.write_register(7, 0)  # Warning false
        self.client.write_register(9, 0)  # Error false
        time.sleep(0.2)
        self.client.write_register(0, 10)  # Home true

    def switch_to_error(self):
        self.client.write_register(0, 0)  # home false
        self.client.write_register(7, 0)  # Warning false
        time.sleep(0.2)
        self.client.write_register(9, 9)  # Error true
        
    def reset_all_switch_registers(self):
        self.client.write_register(0, 0)  # home false
        self.client.write_register(7, 0)  # Warning false
        self.client.write_register(9, 0)  # Error false
        self.client.write_register(14, 0) # EPO
    
    def switch_to_epo(self):
        self.client.write_register(0, 0)  # home false
        self.client.write_register(7, 0)  # Warning false
        self.client.write_register(9, 0)  # Error false
        self.client.write_register(14, 14) # EPO
        
