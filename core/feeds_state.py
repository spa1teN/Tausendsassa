# core/feeds_state.py
"""
Enhanced state management with timestamps, message tracking and automatic cleanup.
Tracks which GUIDs have been posted, when, and the corresponding Discord message IDs
for update functionality.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

class State:
    def __init__(self, path: Path):
        self.path = path
        # Changed to store: {guid: {"timestamp": str, "message_id": int, "channel_id": int}}
        self._entries: Dict[str, dict] = {}
        self._load_state()

    def _load_state(self):
        """Load state from file, handling old, intermediate and new formats"""
        if not self.path.exists():
            return
            
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            
            # Handle old format (list of GUIDs) for backward compatibility
            if isinstance(data, list):
                # Convert old format to new format with current timestamp
                current_time = datetime.now(timezone.utc).isoformat()
                self._entries = {
                    guid: {
                        "timestamp": current_time,
                        "message_id": None,
                        "channel_id": None
                    } for guid in data
                }
                # Save in new format immediately
                self.save()
            
            # Handle intermediate format (dict with timestamps only)
            elif isinstance(data, dict):
                # Check if it's the old timestamp-only format
                if data and isinstance(next(iter(data.values())), str):
                    # Convert timestamp-only format to full format
                    self._entries = {
                        guid: {
                            "timestamp": timestamp,
                            "message_id": None,
                            "channel_id": None
                        } for guid, timestamp in data.items()
                    }
                    self.save()
                else:
                    # Already in new format
                    self._entries = data
            
        except Exception as e:
            # Corrupted file, start fresh
            print(f"Warning: Corrupted state file {self.path}, starting fresh: {e}")
            self.path.unlink(missing_ok=True)
            self._entries = {}

    def already_sent(self, guid: str) -> bool:
        """Check if GUID has already been sent"""
        return guid in self._entries

    def get_message_info(self, guid: str) -> Optional[Tuple[int, int]]:
        """Get message_id and channel_id for a GUID if available"""
        entry = self._entries.get(guid)
        if entry and entry.get("message_id") and entry.get("channel_id"):
            return entry["message_id"], entry["channel_id"]
        return None

    def mark_sent(self, guid: str, message_id: int = None, channel_id: int = None, timestamp: datetime = None) -> None:
        """Mark GUID as sent with message info and timestamp"""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Convert datetime to ISO string for JSON serialization
        timestamp_str = timestamp.isoformat()
            
        # If entry exists, update it; otherwise create new
        if guid in self._entries:
            self._entries[guid].update({
                "timestamp": timestamp_str,  # Always store as string
                "message_id": message_id,
                "channel_id": channel_id
            })
        else:
            self._entries[guid] = {
                "timestamp": timestamp_str,  # Always store as string
                "message_id": message_id,
                "channel_id": channel_id
            }

    def save(self) -> None:
        """Save state to file"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('w', encoding='utf-8') as f:
                json.dump(self._entries, f, indent=2)
        except Exception as e:
            print(f"Error saving state to {self.path}: {e}")

    def cleanup_old_entries(self, max_age_days: int = 7) -> None:
        """Remove entries older than max_age_days (default 7 days)"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_iso = cutoff.isoformat()
        
        old_count = len(self._entries)
        
        # Filter out old entries
        self._entries = {
            guid: entry 
            for guid, entry in self._entries.items()
            if entry.get("timestamp", "") > cutoff_iso
        }
        
        new_count = len(self._entries)
        removed = old_count - new_count
        
        if removed > 0:
            print(f"Cleaned up {removed} old entries from state (older than {max_age_days} days)")
            self.save()

    def get_entry_count(self) -> int:
        """Get total number of tracked entries"""
        return len(self._entries)
        
    def get_stats(self) -> Dict[str, int]:
        """Get statistics about the state"""
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        
        day_count = sum(1 for entry in self._entries.values() 
                       if entry.get("timestamp", "") > day_ago.isoformat())
        week_count = sum(1 for entry in self._entries.values() 
                        if entry.get("timestamp", "") > week_ago.isoformat())
        
        return {
            "total": len(self._entries),
            "last_24h": day_count,
            "last_week": week_count
        }
