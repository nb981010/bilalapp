import socket
import logging
import os
from typing import List, Optional
import time
import threading

logger = logging.getLogger("BilalServer.playback")

# Track active monitor threads to prevent resource exhaustion
ACTIVE_MONITOR_THREADS = {}
MAX_MONITOR_THREADS = 3
MONITOR_LOCK = threading.Lock()


def get_local_ip() -> str:
    """Return the local IP address used to reach the network."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return ip
    except Exception as e:
        logger.warning(f"Could not determine local IP: {e}")
        return "127.0.0.1"
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def get_sonos_speakers(timeout: int = 5, max_retries: int = 3) -> List:
    """Discover Sonos speakers using SoCo with retry logic.

    If the environment variable ``SONOS_HOST`` is set (e.g. "192.168.2.50")
    multicast discovery is skipped and a direct SoCo connection to that IP is
    returned.  Useful when the server is on a different subnet or multicast is
    blocked.

    Retries with exponential backoff on network errors.
    Returns empty list only after all retries exhausted.
    """
    try:
        import soco
    except ImportError:
        logger.error("SoCo library not found.")
        return []

    # Direct-IP bypass: skip multicast when SONOS_HOST env var is set.
    sonos_host = os.environ.get('SONOS_HOST', '').strip()
    if sonos_host:
        try:
            speaker = soco.SoCo(sonos_host)
            _ = speaker.player_name  # validate reachability
            logger.info(f"SONOS_HOST set: direct connection to {sonos_host} ({speaker.player_name})")
            return [speaker]
        except Exception as e:
            logger.warning(f"SONOS_HOST={sonos_host} unreachable ({e}); falling back to multicast discovery")
    
    retry_delays = [0, 2, 5]  # seconds between retries
    
    for attempt in range(max_retries):
        try:
            zones = list(soco.discover(timeout=timeout) or [])
            if zones:
                logger.info(f"Discovered {len(zones)} Sonos zone(s)")
                return zones
            else:
                logger.warning(f"Discovery attempt {attempt + 1}/{max_retries}: no zones found")
        except Exception as e:
            logger.warning(f"Discovery attempt {attempt + 1}/{max_retries} failed: {e}")
        
        # Wait before retry (except on last attempt)
        if attempt < max_retries - 1:
            delay = retry_delays[attempt]
            if delay > 0:
                time.sleep(delay)
    
    logger.error(f"Failed to discover Sonos speakers after {max_retries} attempts")
    return []


def choose_coordinator(speakers: List) -> Optional[object]:
    """Pick a coordinator (first speaker that is actually reachable) or None.
    
    Validates coordinator is responsive before returning.
    """
    if not speakers:
        return None
    
    for speaker in speakers:
        try:
            # Validate speaker is reachable by checking its status
            _ = speaker.player_name  # This will fail if unreachable
            logger.info(f"Selected coordinator: {speaker.player_name}")
            return speaker
        except Exception as e:
            logger.warning(f"Speaker {getattr(speaker, 'ip_address', 'unknown')} unreachable: {e}")
            continue
    
    logger.error("No reachable speakers found to be coordinator")
    return None


def build_audio_url(filename: str, port: int = 5000) -> str:
    ip = get_local_ip()
    return f"http://{ip}:{port}/audio/{filename}"


def set_group_volume(coordinator, volume: int = 75):
    try:
        coordinator.group.volume = volume
    except Exception:
        pass


def play_uri(coordinator, audio_url: str):
    """Tell the coordinator to play the given URI."""
    coordinator.play_uri(audio_url)


def monitor_playback(coordinator, shutdown_event):
    """Monitors playback and restores state after finish.

    This runs in a background thread and will unjoin group members when playback stops.
    Uses shutdown_event for graceful termination.
    """
    thread_id = threading.current_thread().ident
    logger.info(f"Playback Monitor Started (thread {thread_id})...")
    
    # Wait for it to actually start
    for _ in range(5):
        if shutdown_event.is_set():
            logger.info("Monitor shutdown requested before playback start")
            return
        time.sleep(1)

    while not shutdown_event.is_set():
        try:
            info = coordinator.get_current_transport_info()
            state = info.get('current_transport_state')
            if state not in ('PLAYING', 'TRANSITIONING'):
                logger.info(f"Playback finished (State: {state}). Restoring...")
                # Ungroup Logic (Simple Restore)
                try:
                    members = list(coordinator.group.members)
                except Exception as e:
                    logger.warning(f"Could not get group members: {e}")
                    members = []

                for s in members:
                    if s != coordinator:
                        try:
                            s.unjoin()
                            logger.debug(f"Unjoined {getattr(s, 'player_name', 'unknown')}")
                        except Exception as e:
                            logger.warning(f"Failed to unjoin speaker: {e}")
                break
        except Exception as e:
            logger.warning(f"Monitor Error: {e}")
            break

        # Check every 3 seconds
        for _ in range(3):
            if shutdown_event.is_set():
                break
            time.sleep(1)
    
    logger.info(f"Playback Monitor Stopped (thread {thread_id})")
    
    # Remove self from active threads
    with MONITOR_LOCK:
        if thread_id in ACTIVE_MONITOR_THREADS:
            del ACTIVE_MONITOR_THREADS[thread_id]


def start_monitor(coordinator):
    """Start a monitor thread for playback, with thread limit and cleanup."""
    global ACTIVE_MONITOR_THREADS
    
    # Clean up completed threads first
    with MONITOR_LOCK:
        completed_threads = [tid for tid, (thread, _) in ACTIVE_MONITOR_THREADS.items() if not thread.is_alive()]
        for tid in completed_threads:
            thread, event = ACTIVE_MONITOR_THREADS[tid]
            try:
                thread.join(timeout=1)
            except Exception:
                pass
            del ACTIVE_MONITOR_THREADS[tid]
            logger.debug(f"Cleaned up completed monitor thread {tid}")
    
    # Check thread limit (for Raspberry Pi resource constraints)
    with MONITOR_LOCK:
        if len(ACTIVE_MONITOR_THREADS) >= MAX_MONITOR_THREADS:
            logger.warning(f"Monitor thread limit reached ({MAX_MONITOR_THREADS}), stopping oldest thread")
            # Stop oldest thread
            oldest_tid = list(ACTIVE_MONITOR_THREADS.keys())[0]
            _, event = ACTIVE_MONITOR_THREADS[oldest_tid]
            event.set()  # Signal shutdown
    
    # Create shutdown event for this monitor
    shutdown_event = threading.Event()
    
    # Start monitor thread (non-daemon for proper cleanup)
    t = threading.Thread(target=monitor_playback, args=(coordinator, shutdown_event), name="AzanMonitor")
    t.daemon = False  # Allow graceful cleanup
    t.start()
    
    # Track thread
    with MONITOR_LOCK:
        ACTIVE_MONITOR_THREADS[t.ident] = (t, shutdown_event)
    
    logger.debug(f"Started monitor thread {t.ident} (total active: {len(ACTIVE_MONITOR_THREADS)})")


def shutdown_all_monitors():
    """Shutdown all active monitor threads gracefully."""
    global ACTIVE_MONITOR_THREADS
    
    logger.info("Shutting down all monitor threads...")
    
    with MONITOR_LOCK:
        for tid, (thread, event) in list(ACTIVE_MONITOR_THREADS.items()):
            logger.info(f"Stopping monitor thread {tid}")
            event.set()
    
    # Wait for threads to complete (with timeout)
    with MONITOR_LOCK:
        for tid, (thread, _) in list(ACTIVE_MONITOR_THREADS.items()):
            try:
                thread.join(timeout=5)
            except Exception as e:
                logger.warning(f"Error joining thread {tid}: {e}")
        
        ACTIVE_MONITOR_THREADS.clear()
    
    logger.info("All monitor threads shut down")


def group_zones(speakers: List) -> Optional[str]:
    """Group all speakers onto the elected coordinator (first found).

    Returns the coordinator.player_name on success, or None if no speakers.
    
    Strategy to avoid UPnP 501 errors:
    1. Ungrouping all speakers first (except coordinator) to clear existing groups
    2. Wait for Sonos system to settle after ungrouping
    3. Check if speakers are already in target group before joining
    4. Join speakers with retry logic for transient failures
    """
    if not speakers:
        return None

    coordinator = choose_coordinator(speakers)
    if not coordinator:
        return None

    logger.info(f"Elected Coordinator: {coordinator.player_name}")
    
    # Step 1: Ungrouping all non-coordinator speakers to clear existing groups
    logger.info("Ungrouping all speakers to clear existing groups...")
    for s in speakers:
        if s.player_name == coordinator.player_name:
            continue
        try:
            # Check if speaker is in a group (more than 1 member means grouped)
            if len(s.group.members) > 1:
                s.unjoin()
                logger.info(f"Unjoined {s.player_name} from existing group")
            else:
                logger.debug(f"{s.player_name} already standalone")
        except Exception as e:
            logger.warning(f"Failed to unjoin {s.player_name}: {e}")
    
    # Step 2: Brief pause to let Sonos system settle after ungrouping
    # Sonos needs time to process group state changes
    time.sleep(1.5)
    
    # Step 3: Join speakers to coordinator with group membership check and retry
    for s in speakers:
        if s.player_name == coordinator.player_name:
            continue
        
        # Check if already in target group (skip if so)
        try:
            if coordinator in s.group.members:
                logger.debug(f"{s.player_name} already in target group, skipping")
                continue
        except Exception:
            pass
        
        logger.info(f"Joining {s.player_name} to {coordinator.player_name}")
        
        # Try joining with retry (up to 2 attempts for transient failures)
        for attempt in range(2):
            try:
                s.join(coordinator)
                logger.debug(f"Successfully joined {s.player_name} (attempt {attempt + 1})")
                break
            except Exception as e:
                if attempt == 0:
                    # First attempt failed, wait briefly and retry
                    logger.debug(f"Join attempt 1 failed for {s.player_name}, retrying...")
                    time.sleep(1)
                else:
                    # Final attempt failed, log warning
                    logger.warning(f"Failed to join {s.player_name}: {e}")

    return coordinator.player_name
