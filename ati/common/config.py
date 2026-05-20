"""Mock ATI config module for loading configuration files"""
import tomli
from pathlib import Path


def load_mule_config(config_path: str = "config/config.toml"):
    """
    Load configuration from a TOML file.
    
    Args:
        config_path: Path to the TOML configuration file
        
    Returns:
        dict: Configuration dictionary
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        # Return default configuration
        return {
            "redis": {
                "url": "redis://localhost:6379"
            },
            "hmi": {
                "recovery": {
                    "station_name1": "Station 1",
                    "station_pose1": [0.0, 0.0, 0.0],
                    "station_name2": "Station 2",
                    "station_pose2": [1.0, 1.0, 0.0],
                    "station_name3": "Station 3",
                    "station_pose3": [2.0, 2.0, 0.0],
                    "station_name4": "Station 4",
                    "station_pose4": [3.0, 3.0, 0.0]
                }
            }
        }
    
    with open(config_file, "rb") as f:
        return tomli.load(f)
