from dataclasses import dataclass
from typing import Dict, List, Union
from ati.common.config import load_mule_config
config = load_mule_config("config/config.toml")
station_data = config["hmi"]["recovery"]
station1_name = station_data["station_name1"]
station1_pose = station_data["station_pose1"]
station2_name = station_data["station_name2"]
station2_pose = station_data["station_pose2"]
station3_name = station_data["station_name3"]
station3_pose = station_data["station_pose3"]
station4_name = station_data["station_name4"]
station4_pose = station_data["station_pose4"]


@dataclass
class ReadAddresses:
    switch_mode: int = 0x0012
    restart_sherpa: int = 0x0006
    recovery: int = 550


@dataclass
class SwitchModeValues:
    fleet: int = 0x0000
    manual: int = 0x0001


@dataclass
class RestartSherpaValues:
    true: int = 0x0000
    false: int = 0x0001

@dataclass
class RecoveryValues:
    station1: int = 1
    station2: int = 2
    station3: int = 3
    station4: int = 4

@dataclass
class SwitchMode:
    mode: str
    type: str = "switch_mode"


@dataclass
class RestartSherpa:
    type: str = "restart_mule_docker"

@dataclass
class Recovery:
    station_name: str
    pose: List[float]  # [-8.901, 2.828, -1.571]
    type: str = "reset_pose"


@dataclass
class BatteryBar:
    EMPTY: int = 0
    RED: int = 10
    YELLOW: int = 20
    GREEN: int = 80


@dataclass
class ImageTypes:
    SHOW_OBSTACLE_IMAGE: int = 1
    HIDE_OBSTACLE_IMAGE: int = 0



@dataclass
class WriteAddresses:
    CONNECTED_TO_FM: int = 0x0001
    SHERPA_NAME: int = 0x0190  # LW400
    BATTERY_COLOUR_INDICATOR: int = 0x0002
    BATTERY_STATUS: int = 0x0003
    WARNINGS: int = 0x0005  # LB
    NEXT_STATION: int = 0x00F0  # LW240
    ERRORS: int = 0x0004
    EN_ROUTE: int = 0x0000
    WARNING_INFO: int = 0x0064
    ERROR_INFO: int = 0x0096
    OBSTACLE_DIRECTION_BASE: int = 500  
    OBSTACLE_DISTANCE: int = 515
    OBSTACLE_VISIBILITY: int = 512 
    # OBSTACLE_COORDINATES: int = 535
class Const:
    MODBUS_IP: str = "192.168.35.100"
    DATA_MODEL_MAPPING: Dict[int, Dict[int, Union[SwitchMode, RestartSherpa, Recovery]]] = {
        ReadAddresses.switch_mode: {
            SwitchModeValues.manual: SwitchMode(mode="manual"),
            SwitchModeValues.fleet: SwitchMode(mode="fleet")
        },
        ReadAddresses.restart_sherpa: {
            RestartSherpaValues.true: RestartSherpa(),
            RestartSherpaValues.false: RestartSherpa()
        },
        ReadAddresses.recovery: {
            RecoveryValues.station1: Recovery(station_name=station1_name, pose=station1_pose),
            RecoveryValues.station2: Recovery(station_name=station2_name, pose=station2_pose),
            RecoveryValues.station3: Recovery(station_name=station3_name, pose=station3_pose),
            RecoveryValues.station4: Recovery(station_name=station4_name, pose=station4_pose)
        }
    }