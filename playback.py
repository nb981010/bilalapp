import socket
import logging
import os
from typing import List, Optional
import time
import threading

logger = logging.getLogger("BilalServer.playback")


def get_local_ip() -> str:
    """Return the local IP address used to reach the network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_sonos_speakers(timeout: int = 5) -> List:
    """Discover Sonos speakers using SoCo. Returns empty list on error."""
    try:
        import soco
        zones = list(soco.discover(timeout=timeout) or [])
        return zones
    except ImportError:
        logger.error("SoCo library not found.")
        return []
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        return []


def choose_coordinator(speakers: List) -> Optional[object]:
    """Pick a coordinator (first speaker) or None."""
    if not speakers:
        return None
    return speakers[0]


def build_audio_url(filename: str, port: int = 5000) -> str:
    ip = get_local_ip()
    return f"http://{ip}:{port}/audio/{filename}"


def set_group_volume(coordinator, volume: int = 45):
    try:
        coordinator.group.volume = volume
    except Exception:
        pass


def play_uri(coordinator, audio_url: str):
    """Tell the coordinator to play the given URI."""
    coordinator.play_uri(audio_url)


def monitor_playback(coordinator):
    """Monitors playback and restores state after finish.

    This runs in a background thread and will unjoin group members when playback stops.
    """
    logger.info("Playback Monitor Started...")
    # Wait for it to actually start
    time.sleep(5)

    while True:
        try:
            info = coordinator.get_current_transport_info()
            state = info.get('current_transport_state')
            if state not in ('PLAYING', 'TRANSITIONING'):
                logger.info(f"Playback finished (State: {state}). Restoring...")
                # Ungroup Logic (Simple Restore)
                try:
                    members = list(coordinator.group.members)
                except Exception:
                    members = []

                for s in members:
                    if s != coordinator:
                        try:
                            s.unjoin()
                        except Exception:
                            pass
                break
        except Exception as e:
            logger.error(f"Monitor Error: {e}")
            break

        time.sleep(3)


def start_monitor(coordinator):
    t = threading.Thread(target=monitor_playback, args=(coordinator,))
    t.daemon = True
    t.start()


def group_zones(speakers: List) -> Optional[str]:
    """Group all speakers onto the elected coordinator (first found).

    Returns the coordinator.player_name on success, or None if no speakers.
    """
    if not speakers:
        return None

    coordinator = choose_coordinator(speakers)
    if not coordinator:
        return None

    logger.info(f"Elected Coordinator: {coordinator.player_name}")
    for s in speakers[1:]:
        logger.info(f"Joining {s.player_name} to {coordinator.player_name}")
        try:
            s.join(coordinator)
        except Exception as e:
            logger.warning(f"Failed to join {s.player_name}: {e}")

    return coordinator.player_name
