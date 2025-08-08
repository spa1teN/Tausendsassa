# core/state.py
"""
Enhanced state management with timestamps and automatic cleanup.
Tracks which GUIDs have been posted and when, with weekly cleanup of old entries.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Set

class State:
    def __init__(self, path: Path):
        self.path = path
        # Changed from Set[str] to Dict[str, str] to store timestamps
        self._entries: Dict[str, str] = {}
        self._load_state()

    def _load_state(self):
        """Load state from file, handling both old and new format"""
        if not self.path.exists():
            return
            
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            
            # Handle old format (list of GUIDs) for backward compatibility
            if isinstance(data, list):
                # Convert old format to new format with current timestamp
                current_time = datetime.now(timezone.utc).isoformat()
                self._entries = {guid: current_time for guid in data}
                # Save in new format immediately
                self.save()
            
            # Handle new format (dict with timestamps)
            elif isinstance(data, dict):
                self._entries = data
            
        except Exception as e:
            # Corrupted file, start fresh
            print(f"Warning: Corrupted state file {self.path}, starting fresh: {e}")
            self.path.unlink(missing_ok=True)
            self._entries = {}

    def already_sent(self, guid: str) -> bool:
        """Check if GUID has already been sent"""
        return guid in self._entries

    def mark_sent(self, guid: str, timestamp: datetime = None) -> None:
        """Mark GUID as sent with optional timestamp"""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        self._entries[guid] = timestamp.isoformat()

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
            guid: timestamp 
            for guid, timestamp in self._entries.items()
            if timestamp > cutoff_iso
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
        
        day_count = sum(1 for ts in self._entries.values() if ts > day_ago.isoformat())
        week_count = sum(1 for ts in self._entries.values() if ts > week_ago.isoformat())
        
        return {
            "total": len(self._entries),
            "last_24h": day_count,
            "last_week": week_count
        }
