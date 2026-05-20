import json
import logging
import logging.config
import os
import time
import math

#ati imports
import hmi_utils as hu
from hmi_tcp_utils import ModbusTcpClient
import hmi_models as hmm
import mule_comms.utils.log_utils as lu

TRIP_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hmi_trip_state.json')

logging.config.dictConfig(lu.get_log_config_dict())
logger = logging.getLogger('hmi')

class Handler:
    def __init__(self):
        self.client = ModbusTcpClient(hmm.Const.MODBUS_IP, port=8888)
        self.alert = False
        self.error_active = False
        self.previous_mode = None
        self.bot_position = {"x": 0.0, "y": 0.0, "heading": 0.0}
        self.obstacles = []
        self.recently_changed = False
        self.mode_change_timestamp = 0.0
        self.connecting = False
        self.connecting_start_time = 0.0
        self.estop_release_time = 0.0
        self.last_trip_state = self._load_trip_state()
        self.startup_restore_pending = self.last_trip_state is not None

    def _load_trip_state(self):
        try:
            if os.path.exists(TRIP_STATE_FILE):
                with open(TRIP_STATE_FILE, 'r') as f:
                    state = json.load(f)
                logger.info(f"Loaded persisted trip state: {state}")
                return state
        except Exception as e:
            logger.warning(f"Failed to load trip state: {e}")
        return None

    def _save_trip_state(self, state):
        try:
            with open(TRIP_STATE_FILE, 'w') as f:
                json.dump(state, f)
            self.last_trip_state = state
            logger.info(f"Saved trip state: {state}")
        except Exception as e:
            logger.warning(f"Failed to save trip state: {e}")

    def _clear_trip_state(self):
        try:
            if os.path.exists(TRIP_STATE_FILE):
                os.remove(TRIP_STATE_FILE)
        except Exception as e:
            logger.warning(f"Failed to clear trip state: {e}")
        self.last_trip_state = None
        self.startup_restore_pending = False

    def _restore_trip_state(self):
        if not self.last_trip_state:
            self.client.write_register(9, 0)
            return
        try:
            screen = self.last_trip_state.get('screen')
            if screen == 'warning':
                waiting_for = self.last_trip_state.get('waiting_for', '')
                next_station = self.last_trip_state.get('next_station', '')
                self.switch_to_warning()
                if next_station:
                    self.client.write_string_to_registers(hmm.WriteAddresses.NEXT_STATION, next_station, 30)
                if waiting_for:
                    self.client.write_string_to_registers(hmm.WriteAddresses.WARNING_INFO, waiting_for, 50)
                logger.info(f"Restored trip state on startup: waiting_for='{waiting_for}', next_station='{next_station}'")
            else:
                self.client.write_register(9, 0)
        except Exception as e:
            logger.warning(f"Failed to restore trip state: {e}")
            self.client.write_register(9, 0)

    def _show_connecting(self):
        self.connecting = True
        self.connecting_start_time = time.time()
        self.switch_to_warning()
        self.client.write_string_to_registers(hmm.WriteAddresses.WARNING_INFO, "Connecting to Fleet Manager...", 50)
        logger.info("Showing 'Connecting to Fleet Manager...' screen")

    def set_recently_changed(self):
        """Set the recently_changed flag and timestamp"""
        self.recently_changed = True
        self.mode_change_timestamp = time.time()
        logger.info("Mode recently changed flag set")

    def check_recently_changed(self, timeout_seconds=5):
        """Check if mode was recently changed and reset flag if timeout passed"""
        if self.recently_changed:
            current_time = time.time()
            if current_time - self.mode_change_timestamp > timeout_seconds:
                self.recently_changed = False
                logger.info("Mode recently changed flag reset after timeout")
        return self.recently_changed

    def find_closest_point(self, x, y):
        """
        Find which of the 12 points around the origin is closest to the given [x, y] position.
        Points are separated by 30 degrees, starting from x-axis (0 degrees).
        :param x: X coordinate of the obstacle position
        :param y: Y coordinate of the obstacle position
        :return: Point index (0-11) representing the closest point
        """
        # Calculate angle in radians using atan2 (returns angle from -pi to pi)
        angle_rad = math.atan2(y, x)
        
        # Convert to degrees and normalize to 0-360 range
        angle_deg = math.degrees(angle_rad)
        if angle_deg < 0:
            angle_deg += 360
        
        angle_deg = angle_deg + 90
        if angle_deg >= 360:
            angle_deg -= 360
        
        # Map angle to one of 12 sectors (each 30 degrees)
        # Point 0: 0° (x-axis), Point 1: 30°, ..., Point 11: 330°
        point_index = int(round(angle_deg / 30.0)) % 12
        
        return point_index

    def write_obstacle_direction(self, x, y, base_address=None):
        """
        Write obstacle direction to Modbus addresses.
        Writes 1 to the address corresponding to the closest point, and 0 to all others.
        :param x: X coordinate of the obstacle position
        :param y: Y coordinate of the obstacle position
        :param base_address: Base address for the 12 continuous addresses (defaults to OBSTACLE_DIRECTION_BASE)
        :return: True if successful, False otherwise
        """
        if base_address is None:
            base_address = hmm.WriteAddresses.OBSTACLE_DIRECTION_BASE
        
        # Find which point is closest
        point_index = self.find_closest_point(x, y)
        
        angle_deg = math.degrees(math.atan2(y, x))
        if angle_deg < 0:
            angle_deg += 360
        
        angle_deg = angle_deg + 90
        if angle_deg >= 360:
            angle_deg -= 360
        
        logger.info(f"Obstacle at [{x}, {y}] - Closest point: {point_index} (angle: {angle_deg:.1f}°)")
        
        # Write 0 to all 12 addresses first
        all_success = True
        for i in range(12):
            address = base_address + i
            if not self.client.write_coil(address, False):
                all_success = False
                logger.error(f"Failed to write 0 to address {address}")
        
        # Write 1 to the closest point address
        target_address = base_address + point_index
        logger.info(f"Writing to target address: {target_address} (base: {base_address} + point_index: {point_index})")
        if self.client.write_coil(target_address, True):
            print(f"Successfully wrote 1 to address {target_address}")
        else:
            all_success = False
            logger.error(f"Failed to write 1 to address {target_address}")
        
        return all_success

    def handle(self, msg):
        # Check if message has 'type' or 'action' field
        if 'type' in msg:
            msg_type = msg['type']
            handler_name = f"handle_{msg_type}"
        elif 'action' in msg:
            msg_type = msg['action']
            handler_name = f"handle_action_{msg_type}"
        else:
            logger.warning(f"Message has neither 'type' nor 'action' field: {msg}")
            return None

        msg_handler = getattr(self, handler_name, None)

        if not msg_handler:
            logger.warning(f"No handler defined for {msg_type}. Message: {msg}")
            return None

        try:
            response = msg_handler(msg)
            return response
        except Exception as e:
            logger.error(f"Error handling message type {msg_type}: {str(e)}")
            return None

    def handle_set_network_stats(self, msg):
        status = 1 if str(msg["connected_to_FM"]) == "True" else 0
        if self.client.write_coil(hmm.WriteAddresses.CONNECTED_TO_FM, status):
            logger.info("Successfully sent connected fm status")
        else:
            logger.error("Failed to send connected fm status")

    def handle_set_sherpa_status(self, msg):
        sherpa_name = msg["sherpa_name"]
        battery_status = int(msg["battery_status"])
        mode = msg["mode"]

        if self.connecting and time.time() - self.connecting_start_time > 30:
            self.connecting = False
            self.switch_to_home()
            logger.info("Connecting timeout — switching to home screen")
        
        if self.client.write_string_to_registers(
            hmm.WriteAddresses.SHERPA_NAME, sherpa_name, 30
        ):
            logger.info("Successfully wrote sherpa name to register")

        if self.client.write_register(hmm.WriteAddresses.BATTERY_STATUS, battery_status):
            logger.info("Successfully wrote battery status to register")
        else:
            logger.info("Failed to write battery status to register")

        if 1 < battery_status <= 20 and mode != "error" and not self.alert and not self.error_active:
            if battery_status <= 10:
                self.switch_to_alert()
                if self.client.write_string_to_registers(hmm.WriteAddresses.ERROR_INFO, "Battery Critically Low", 90):
                    logger.info("Low battery alert sent")
                else:
                    logger.error("Failed to send low battery alert")
            else:
                self.switch_to_warning()
                if self.client.write_string_to_registers(hmm.WriteAddresses.WARNING_INFO, "Low Battery", 50):
                    logger.info("Low battery alert sent")
                else:
                    logger.error("Failed to send low battery alert")
                
        if mode == "fleet" and self.client.read_coil(7) == 1:
            if self.client.read_coil(7) == 1:
                logger.info("Loading switched to fleet mode ...")
                self.client.write_coil(11, 1)
                time.sleep(3)
                self.client.write_coil(11, 0)
            # Ensure mode is set to fleet
            if self.client.write_coil(hmm.ReadAddresses.switch_mode, 0):
                logger.info("Switched to fleet mode")
                self.set_recently_changed()
                self.client.write_coil(19, 0)
            if self.client.write_coil(7, 0):
                logger.info("fleet mode")
            
        if mode == "manual" and self.client.read_coil(7) == 0:
            if self.client.read_coil(7) == 0:
                logger.info("Loading switched to fleet mode ...")
                self.client.write_coil(12, 1)
                time.sleep(3)
                self.client.write_coil(12, 0)
                
            # Ensure mode is set to manual
            if self.client.write_coil(hmm.ReadAddresses.switch_mode, 1):
                logger.info("Switched to manual mode")
                self.set_recently_changed()
                self.client.write_coil(19, 1)
            if self.client.write_coil(7, 1):
                logger.info("manual mode")
                
        if self.previous_mode != mode:
            if self.error_active:
                if self.previous_mode == "error" or mode == "manual":
                    self.error_active = False
                    if mode == "manual":
                        self._clear_trip_state()
                    logger.info(f"Error cleared: mode changed from {self.previous_mode} to {mode}")
            self.previous_mode = mode
            if not self.error_active:
                if mode == 'fleet':
                    if self.startup_restore_pending or self.last_trip_state:
                        self._restore_trip_state()
                        self.startup_restore_pending = False
                    else:
                        self._show_connecting()
                else:
                    self.client.write_register(9, 0)
    
    def handle_set_alerts(self, msg):
        emergency_button = str(msg.get('emergency_button', ''))
        if emergency_button == "Emergency Button was pressed":
            self.alert = True
            self.switch_to_alert()
            if self.client.write_string_to_registers(hmm.WriteAddresses.ERROR_INFO, emergency_button, 50):
                logger.info(f"Successfully wrote error info : {emergency_button} to register")
            else:
                logger.error(f"Failed to write error info : {emergency_button} to register")
        else:
            logger.info(f"Emergency button disengaged (error_active={self.error_active})")
            self.alert = False
            self.estop_release_time = time.time()
            if self.error_active:
                self.switch_to_error()
                logger.info("Returning to error screen after emergency button release")
            else:
                self.switch_to_home()
                logger.info("Returned to home screen after emergency button release")
            
    def handle_set_mule_error(self, msg):
        if not self.alert:
            recovery_message = msg["recovery_message"]
            error_code = msg["error_code"]

            if (time.time() - self.estop_release_time < 10.0 and
                    'can' in error_code.lower()):
                logger.info(f"Suppressing CAN error within 10s of e-stop release: {error_code}")
                return

            if not self.error_active:
                self.error_active = True
                self.switch_to_error()
            if self.client.write_string_to_registers(hmm.WriteAddresses.ERROR_INFO, recovery_message, 90):
                logger.info(f"Successfully wrote error info : {recovery_message} to register")
            else:
                logger.error(f"Failed to write error info : {recovery_message} to register ")

            if self.client.write_string_to_registers(280, error_code, 20):
                logger.info(f"Successfully wrote error code : {error_code} to register")
            else:
                logger.error(f"Failed to write error code : {error_code} to register ")
        else:
            logger.info("Error alert already triggered")

    def handle_set_trip_description(self, msg):
        if self.error_active:
            status = str(msg.get("status", ""))
            waiting_for = str(msg.get("waiting_for", "")).strip()
            if status == "en_route" and not waiting_for:
                logger.info("Mule resumed en_route — clearing error state")
                self.error_active = False
                self._clear_trip_state()
            else:
                logger.info(f"Skipping trip_description (status={status}) — mule error is active")
                return

        self.connecting = False

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
            self._save_trip_state({'screen': 'warning', 'waiting_for': waiting_for, 'next_station': next_station})
            self.startup_restore_pending = False
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
            self._clear_trip_state()
            self.switch_to_home()

    def handle_set_trip_status(self, msg):
        if self.error_active:
            logger.info("Skipping trip_status screen update — mule error is active")
            return

        # Handle stoppages as either a list or a dict
        stoppages = msg.get("stoppages", {})
        if isinstance(stoppages, list) and len(stoppages) > 0:
            stoppage_data = stoppages[0]
        elif isinstance(stoppages, dict):
            stoppage_data = stoppages
        else:
            logger.warning(f"Invalid stoppages format in trip_status: {stoppages}")
            return
        type_value = stoppage_data.get("type", "")
        first_two_words = " ".join(type_value.split()[:2])
        stoppage_type = hu.shrink_message_type(first_two_words)
        next_station = msg["trip_info"]["destination_name"]
        if self.client.write_string_to_registers(
            hmm.WriteAddresses.NEXT_STATION, next_station, 30
        ):
            logger.info(f"Successfully set next station to {next_station}")
        if stoppage_type == "detected_obstacle":
            self.switch_to_warning()
            
            if self.client.write_coil(512, 1):
                logger.info("Shown obstacle detected image")
            else:
                logger.error("Failed to show obstacle detected image")
            
            try:
                extra_info = stoppage_data.get("extra_info", {})
                local_obstacle = extra_info.get("local_obstacle")
                print(f"local_obstacle: {local_obstacle}")
                
                if local_obstacle is not None and len(local_obstacle) >= 2:
                    x = float(local_obstacle[0])
                    y = float(local_obstacle[1])
                    # logger.info(f"Extracted local_obstacle from trip_status: [{x}, {y}]")
                    
                    distance_meters = math.sqrt(x**2 + y**2)
                    distance_cm = int(distance_meters * 100)
                    
                    logger.info(f"Calculated obstacle distance: {distance_meters:.2f}m ({distance_cm}cm)")
                    
                    self.write_obstacle_direction(x, y)
                    
                    # coordinates_msg = f"[{x:.2f}, {y:.2f}]"
                    # if self.client.write_string_to_registers(
                    #     hmm.WriteAddresses.OBSTACLE_COORDINATES, coordinates_msg, 50
                    # ):
                    #     logger.info(f"Successfully wrote obstacle coordinates to OBSTACLE_COORDINATES: {coordinates_msg}")
                    # else:
                    #     logger.error("Failed to write obstacle coordinates to OBSTACLE_COORDINATES")
                    
                    warning_msg = f"Distance {distance_meters:.2f} m"
                    if self.client.write_string_to_registers(
                        hmm.WriteAddresses.OBSTACLE_DISTANCE, warning_msg, 16
                    ):
                        logger.info(f"Successfully set obstacle warning with distance: {warning_msg}")
                    else:
                        logger.error("Failed to set obstacle warning message")
                else:
                    logger.warning(f"local_obstacle not found or invalid in trip_status message: {local_obstacle}")
                    # Set basic warning even if coordinates are missing
                    if self.client.write_string_to_registers(
                        hmm.WriteAddresses.WARNING_INFO, "", 50
                    ):
                        logger.info("Successfully set basic obstacle detected warning")
            except (KeyError, ValueError, TypeError, IndexError) as e:
                logger.error(f"Error extracting local_obstacle from trip_status: {e}")
                # Set basic warning on error
                if self.client.write_string_to_registers(
                    hmm.WriteAddresses.WARNING_INFO, "", 50
                ):
                    logger.info("Successfully set basic obstacle detected warning")
        else:
            # Set coils 500-511 to 0
            for coil_address in range(500, 513):
                self.client.write_coil(coil_address, 0)
    
            self.switch_to_home()

    def handle_action_terminate_trip(self, msg):
        """
        Handle terminate_trip action messages
        """
        trip_id = msg.get('trip_id')
        self.client.write_coil(17, 0)
        self.client.write_register(0, 0)
        logger.info(f"Received terminate_trip action - Trip ID: {trip_id}")

    def switch_to_warning(self):
        ok = all([
            self.client.write_register(0, 0),
            self.client.write_register(9, 0),
            self.client.write_register(10, 0),
            self.client.write_register(7, 7),
        ])
        if not ok:
            logger.error("switch_to_warning: one or more register writes failed")

    def switch_to_home(self):
        ok = all([
            self.client.write_register(7, 0),
            self.client.write_register(9, 0),
            self.client.write_register(10, 0),
            self.client.write_register(0, 10),
        ])
        if not ok:
            logger.error("switch_to_home: one or more register writes failed")
        for coil_address in range(500, 513):
            self.client.write_coil(coil_address, 0)

    def switch_to_error(self):
        ok = all([
            self.client.write_register(0, 0),
            self.client.write_register(7, 0),
            self.client.write_register(10, 0),
            self.client.write_register(9, 9),
        ])
        if not ok:
            logger.error("switch_to_error: one or more register writes failed")
        for coil_address in range(500, 513):
            self.client.write_coil(coil_address, 0)

    def switch_to_alert(self):
        ok = all([
            self.client.write_register(0, 0),
            self.client.write_register(7, 0),
            self.client.write_register(9, 0),
            self.client.write_register(10, 10),
        ])
        if not ok:
            logger.error("switch_to_alert: one or more register writes failed")
        for coil_address in range(500, 513):
            self.client.write_coil(coil_address, 0)

    def update_bot_position(self, x: float, y: float, heading: float):
        """Update bot's current position"""
        self.bot_position = {"x": x, "y": y, "heading": heading}
        logger.info(f"Bot position updated: ({x:.2f}, {y:.2f}), heading: {heading:.2f}°")

    def calculate_distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """Calculate Euclidean distance between two points"""
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    def calculate_angle(self, bot_x: float, bot_y: float, obstacle_x: float, obstacle_y: float, bot_heading: float) -> float:
        """Calculate angle from bot to obstacle relative to bot's heading"""
        # Calculate angle from bot to obstacle
        dx = obstacle_x - bot_x
        dy = obstacle_y - bot_y
        angle_to_obstacle = math.degrees(math.atan2(dy, dx))
        
        # Calculate relative angle considering bot's heading
        relative_angle = angle_to_obstacle - bot_heading
        
        # Normalize angle to [-180, 180]
        while relative_angle > 180:
            relative_angle -= 360
        while relative_angle < -180:
            relative_angle += 360
            
        return relative_angle

    def process_obstacle_detection(self, obstacle_data: dict) -> dict:
        """Process incoming obstacle detection data"""
        try:
            # Extract obstacle coordinates
            obstacle_x = obstacle_data.get('x_coordinate', 0.0)
            obstacle_y = obstacle_data.get('y_coordinate', 0.0)
            obstacle_id = obstacle_data.get('obstacle_id', f"obs_{int(time.time())}")
            confidence = obstacle_data.get('confidence', 1.0)
            obstacle_type = obstacle_data.get('obstacle_type', 'unknown')
            
            # Calculate distance from bot to obstacle
            distance = self.calculate_distance(
                self.bot_position["x"], self.bot_position["y"],
                obstacle_x, obstacle_y
            )
            
            # Calculate angle relative to bot's heading
            angle = self.calculate_angle(
                self.bot_position["x"], self.bot_position["y"],
                obstacle_x, obstacle_y, self.bot_position["heading"]
            )
            
            # Create obstacle data
            obstacle = {
                "obstacle_id": obstacle_id,
                "x_coordinate": obstacle_x,
                "y_coordinate": obstacle_y,
                "distance": distance,
                "angle": angle,
                "confidence": confidence,
                "timestamp": time.time(),
                "obstacle_type": obstacle_type
            }
            
            # Add to obstacles list
            self.obstacles.append(obstacle)
            
            # Keep only recent obstacles (last 100)
            if len(self.obstacles) > 100:
                self.obstacles = self.obstacles[-100:]
            
            logger.info(f"Obstacle detected: {obstacle}")
            return obstacle
            
        except Exception as e:
            logger.error(f"Error processing obstacle detection: {e}")
            return None

    def get_obstacle_info_string(self, obstacle: dict) -> str:
        """Generate formatted obstacle information string"""
        return (f"Obstacle {obstacle['obstacle_id']}: "
                f"Distance: {obstacle['distance']:.2f}m, "
                f"Angle: {obstacle['angle']:.1f}°, "
                f"Position: ({obstacle['x_coordinate']:.2f}, {obstacle['y_coordinate']:.2f}), "
                f"Type: {obstacle['obstacle_type']}, "
                f"Confidence: {obstacle['confidence']:.2f}")

    def handle_set_obstacle_detection(self, msg):
        """Handle obstacle detection with coordinates and distance"""
        try:
            obstacle = self.process_obstacle_detection(msg)
            if not obstacle:
                return False
            
            # Switch to warning state
            self.switch_to_warning()
            
            # Show obstacle image
            if self.client.write_register(
                hmm.WriteAddresses.ERRORS, hmm.ImageTypes.SHOW_OBSTACLE_IMAGE
            ):
                logger.info("Shown obstacle detected image")
            else:
                logger.error("Failed to show obstacle detected image")
            
            # Create detailed obstacle information
            obstacle_info = self.get_obstacle_info_string(obstacle)
            
            # Write obstacle information to HMI
            if self.client.write_string_to_registers(
                hmm.WriteAddresses.WARNING_INFO, obstacle_info, 50
            ):
                logger.info(f"Successfully set obstacle warning: {obstacle_info}")
                return True
            else:
                logger.error("Failed to set obstacle warning")
                return False
                
        except Exception as e:
            logger.error(f"Error handling obstacle detection message: {e}")
            return False

    def handle_set_bot_position(self, msg):
        """Handle bot position updates"""
        try:
            x = msg.get('x', 0.0)
            y = msg.get('y', 0.0)
            heading = msg.get('heading', 0.0)
            self.update_bot_position(x, y, heading)
            logger.info(f"Bot position updated from message: ({x}, {y}), heading: {heading}")
        except Exception as e:
            logger.error(f"Error updating bot position: {e}")

    def get_closest_obstacle(self) -> dict:
        """Get the closest obstacle to the bot"""
        if not self.obstacles:
            return None
        
        return min(self.obstacles, key=lambda obs: obs['distance'])

    def get_obstacles_in_range(self, max_distance: float) -> list:
        """Get all obstacles within specified distance"""
        return [obs for obs in self.obstacles if obs['distance'] <= max_distance]

    def clear_obstacles(self):
        """Clear all obstacles and switch to home state"""
        self.obstacles.clear()
        self.switch_to_home()
        logger.info("Cleared all obstacles")