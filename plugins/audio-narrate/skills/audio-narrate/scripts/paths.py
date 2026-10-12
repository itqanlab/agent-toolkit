"""Where audio-narrate keeps its engines and voices: outside the skill folder, so the
skill stays small and read-only, and a reinstall does not throw away 120 MB of voices.

AUDIO_NARRATE_HOME wins. Otherwise <AGENT_TOOLKIT_HOME>/audio-narrate, and
AGENT_TOOLKIT_HOME defaults to ~/.itqan-agent-toolkit, the toolkit's own folder.
"""
import os


def home():
    explicit = os.environ.get("AUDIO_NARRATE_HOME", "").strip()
    if explicit:
        return os.path.expanduser(explicit)
    root = os.environ.get("AGENT_TOOLKIT_HOME", "").strip() or "~/.itqan-agent-toolkit"
    return os.path.join(os.path.expanduser(root), "audio-narrate")


def voices_dir():
    return os.path.join(home(), "voices")
